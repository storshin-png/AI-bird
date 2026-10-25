"""require_role, require_permission, require_scope на маленьком приложении."""

from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Column, MetaData, Table, Uuid, select
from sqlalchemy.dialects import postgresql

from auth_service import ClientScope, JWTClaims, Permission, Role, require_permission, require_role, require_scope

meta = MetaData()
events = Table("events", meta, Column("event_id", Uuid), Column("client_id", Uuid))

ACME, OTHER = uuid4(), uuid4()
ROWS = [{"event_id": uuid4(), "client_id": ACME}, {"event_id": uuid4(), "client_id": OTHER}]


@pytest.fixture
def api(tokens):
    app = FastAPI()
    app.state.tokens = tokens

    @app.get("/admin")
    async def admin(claims=Depends(require_role(Role.SUPER_ADMIN))):
        return {"ok": claims.email}

    @app.get("/devices")
    async def devices(claims=Depends(require_permission(Permission.DEVICES_READ))):
        return {"ok": True}

    @app.get("/events")
    async def list_events(scope: ClientScope = Depends(require_scope("client"))):
        # Тот же фильтр, что пойдёт в SQL, применяем к строкам в памяти.
        return [str(r["event_id"]) for r in ROWS if scope.allows(r["client_id"])]

    with TestClient(app) as c:
        yield c


def _token(tokens, role, client_id=None):
    claims = JWTClaims.for_user(uuid4(), f"{role}@aibird.local", Role(role), client_id)
    return {"Authorization": f"Bearer {tokens.issue_access(claims).token}"}


def test_role_guard(api, tokens):
    assert api.get("/admin", headers=_token(tokens, "super_admin")).status_code == 200
    r = api.get("/admin", headers=_token(tokens, "field_engineer"))
    assert r.status_code == 403 and r.json()["detail"] == "insufficient_role"
    assert api.get("/admin").status_code == 401


def test_expired_token_is_401(api, tokens, clock):
    clock.advance(-2 * 3600)
    assert api.get("/admin", headers=_token(tokens, "super_admin")).status_code == 401


def test_permission_guard(api, tokens):
    assert api.get("/devices", headers=_token(tokens, "field_engineer")).status_code == 200
    r = api.get("/devices", headers=_token(tokens, "b2b_client", ACME))
    assert r.status_code == 403 and r.json()["detail"] == "insufficient_permissions"


def test_b2b_sees_only_own_client(api, tokens):
    own = api.get("/events", headers=_token(tokens, "b2b_client", ACME)).json()
    assert own == [str(ROWS[0]["event_id"])]
    other = api.get("/events", headers=_token(tokens, "b2b_client", OTHER)).json()
    assert other == [str(ROWS[1]["event_id"])]


def test_internal_roles_see_all(api, tokens):
    for role in ("super_admin", "lead_ornithologist", "field_engineer"):
        assert len(api.get("/events", headers=_token(tokens, role)).json()) == 2


def test_b2b_without_client_sees_nothing(api, tokens):
    r = api.get("/events", headers=_token(tokens, "b2b_client", None))
    assert r.status_code == 403 and r.json()["detail"] == "client_not_assigned"


def _compile(stmt):
    return stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})


def test_scope_adds_where_client_id():
    b2b = ClientScope(JWTClaims.for_user(uuid4(), "c@x", Role.B2B_CLIENT, ACME))
    sql = str(_compile(b2b.apply(select(events), events.c.client_id)))
    assert "WHERE events.client_id = " in sql and ACME.hex in sql.replace("-", "")
    fragment, params = b2b.sql("e.client_id")
    assert fragment == "e.client_id = :jwt_client_id" and params == {"jwt_client_id": ACME}


def test_scope_noop_for_admin():
    admin = ClientScope(JWTClaims.for_user(uuid4(), "a@x", Role.SUPER_ADMIN, None))
    assert "WHERE" not in str(_compile(admin.apply(select(events), events.c.client_id)))
    assert admin.sql() == ("TRUE", {})
    assert admin.allows(None) and admin.allows(OTHER)


def test_factories_validate_arguments():
    with pytest.raises(ValueError):
        require_scope("region")
    with pytest.raises(ValueError):
        require_role()
    with pytest.raises(ValueError):
        require_permission()
    with pytest.raises(ValueError):
        require_role("nobody")
