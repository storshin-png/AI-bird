"""REST устройств, ТО и телеметрии на PostgreSQL."""

import uuid
from datetime import UTC, datetime, timedelta

from auth_service import Permission

from .conftest import bearer, needs_db

pytestmark = needs_db
BASE = "/api/v1/devices"


def admin(tokens):
    return bearer(tokens, "super_admin")


def test_auth_required(api, tokens, db):
    assert api.get(BASE).status_code == 401
    r = api.get(BASE, headers=bearer(tokens, "b2b_client", uuid.uuid4()))
    assert r.status_code == 403 and r.json()["detail"] == "insufficient_permissions"
    r = api.post(BASE, json={"device_id": db.dev("x")}, headers=bearer(tokens, "lead_ornithologist"))
    assert r.status_code == 403


def test_create_get_patch_delete(api, tokens, db):
    cid = db.client()
    dev = db.dev("crud")
    body = {"device_id": dev, "name": "Стенд 1", "client_id": str(cid), "latitude": 53.41, "longitude": 58.98,
            "orientation_deg": 12.5, "installed_at": "2026-10-20T08:00:00Z", "firmware_version": "0.1.0"}
    r = api.post(BASE, json=body, headers=bearer(tokens, "field_engineer"))
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["device_id"] == dev and d["status"] == "registered"
    assert (d["latitude"], d["longitude"]) == (53.41, 58.98) and d["client_id"] == str(cid)

    assert api.post(BASE, json=body, headers=admin(tokens)).json()["detail"] == "device_exists"
    assert api.get(f"{BASE}/{dev}", headers=admin(tokens)).json()["name"] == "Стенд 1"

    r = api.patch(f"{BASE}/{dev}", json={"status": "active", "latitude": 53.5, "longitude": 59.1},
                  headers=admin(tokens))
    assert r.status_code == 200 and r.json()["status"] == "active" and r.json()["latitude"] == 53.5
    r = api.patch(f"{BASE}/{dev}", json={"latitude": None, "longitude": None}, headers=admin(tokens))
    assert r.json()["latitude"] is None
    assert api.patch(f"{BASE}/{dev}", json={}, headers=admin(tokens)).status_code == 200

    assert api.delete(f"{BASE}/{dev}", headers=admin(tokens)).status_code == 204
    assert api.get(f"{BASE}/{dev}", headers=admin(tokens)).status_code == 404
    assert api.delete(f"{BASE}/{dev}", headers=admin(tokens)).status_code == 404
    assert api.patch(f"{BASE}/{dev}", json={"name": "x"}, headers=admin(tokens)).status_code == 404


def test_validation_errors(api, tokens, db):
    h = admin(tokens)
    assert api.post(BASE, json={"device_id": "-bad"}, headers=h).status_code == 422
    assert api.post(BASE, json={"device_id": db.dev("a"), "latitude": 1}, headers=h).status_code == 422
    assert api.post(BASE, json={"device_id": db.dev("a"), "latitude": 91, "longitude": 0}, headers=h).status_code == 422
    r = api.post(BASE, json={"device_id": db.dev("a"), "client_id": str(uuid.uuid4())}, headers=h)
    assert r.status_code == 422 and r.json()["detail"] == "unknown_client"
    dev = db.device("v")
    assert api.patch(f"{BASE}/{dev}", json={"latitude": 1}, headers=h).status_code == 422
    assert api.patch(f"{BASE}/{dev}", json={"status": None}, headers=h).status_code == 422
    r = api.patch(f"{BASE}/{dev}", json={"client_id": str(uuid.uuid4())}, headers=h)
    assert r.status_code == 422


def test_cannot_delete_device_with_data(api, tokens, db):
    dev = db.device("data")
    db.exec("INSERT INTO telemetry (timestamp_utc, device_id) VALUES (now(), :d)", d=dev)
    r = api.delete(f"{BASE}/{dev}", headers=admin(tokens))
    assert r.status_code == 409 and r.json()["detail"] == "device_has_data"


def test_list_and_geojson(api, tokens, db):
    a = db.device("a", lat=53.4, lon=59.0)
    b = db.device("b", status="retired")
    c = db.device("c", lat=None, lon=None)
    h = admin(tokens)
    listed = api.get(BASE, params={"limit": 500}, headers=h).json()
    ids = {d["device_id"] for d in listed["items"]}
    assert {a, b, c} <= ids and listed["limit"] == 500
    retired = api.get(BASE, params={"status": "retired", "limit": 500}, headers=h).json()["items"]
    assert b in {d["device_id"] for d in retired} and a not in {d["device_id"] for d in retired}
    geo = api.get(BASE, params={"format": "geojson", "limit": 500}, headers=h).json()
    assert geo["type"] == "FeatureCollection"
    feats = {f["id"]: f for f in geo["features"]}
    assert feats[a]["geometry"] == {"type": "Point", "coordinates": [59.0, 53.4]}
    assert feats[c]["geometry"] is None and feats[a]["properties"]["status"] == "active"


def test_client_scope_on_sql(api, tokens, db):
    mine, other = db.client(), db.client()
    own = db.device("own", client_id=mine)
    foreign = db.device("foreign", client_id=other)
    # Клиенту с правом чтения устройств (такого нет в черновике прав) — только свои строки.
    h = bearer(tokens, "b2b_client", mine, permissions=[Permission.DEVICES_READ, Permission.TELEMETRY_READ])
    ids = {d["device_id"] for d in api.get(BASE, params={"limit": 500}, headers=h).json()["items"]}
    assert own in ids and foreign not in ids
    assert api.get(f"{BASE}/{foreign}", headers=h).status_code == 404
    assert api.get(f"{BASE}/{foreign}/telemetry", headers=h).status_code == 404
    assert api.get(f"{BASE}/{own}/telemetry", headers=h).status_code == 200


def test_maintenance(api, tokens, db):
    dev = db.device("mnt")
    h = bearer(tokens, "field_engineer")
    r = api.post(f"{BASE}/{dev}/maintenance", headers=h,
                 json={"performed_at": "2026-10-21T10:00:00Z", "kind": "calibration", "orientation_deg": 3.0,
                       "notes": "компас"})
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "calibration" and r.json()["performed_by"] is None
    api.post(f"{BASE}/{dev}/maintenance", headers=h, json={"performed_at": "2026-10-22T10:00:00Z", "kind": "battery"})
    logs = api.get(f"{BASE}/{dev}/maintenance", headers=h).json()
    assert [m["kind"] for m in logs] == ["battery", "calibration"]
    assert api.post(f"{BASE}/{dev}/maintenance", headers=bearer(tokens, "lead_ornithologist"),
                    json={"performed_at": "2026-10-22T10:00:00Z", "kind": "battery"}).status_code == 403
    assert api.post(f"{BASE}/{db.dev('none')}/maintenance", headers=h,
                    json={"performed_at": "2026-10-22T10:00:00Z", "kind": "battery"}).status_code == 404
    assert api.post(f"{BASE}/{dev}/maintenance", headers=h,
                    json={"performed_at": "2026-10-22T10:00:00Z", "kind": "wash"}).status_code == 422


def test_telemetry_timeseries_with_cursor(api, tokens, db):
    dev = db.device("ts")
    start = datetime(2026, 10, 20, tzinfo=UTC)
    for i in range(7):
        db.exec("INSERT INTO telemetry (timestamp_utc, device_id, battery_v) VALUES (:t, :d, :b)",
                t=start + timedelta(hours=i), d=dev, b=3.0 + i / 10)
    h = bearer(tokens, "field_engineer")
    url = f"{BASE}/{dev}/telemetry"
    page1 = api.get(url, params={"limit": 3}, headers=h).json()
    assert [p["battery_v"] for p in page1["items"]] == [3.0, 3.1, 3.2] and page1["next_cursor"]
    page2 = api.get(url, params={"limit": 3, "cursor": page1["next_cursor"]}, headers=h).json()
    page3 = api.get(url, params={"limit": 3, "cursor": page2["next_cursor"]}, headers=h).json()
    assert [p["battery_v"] for p in page2["items"] + page3["items"]] == [3.3, 3.4, 3.5, 3.6]
    assert page3["next_cursor"] is None
    window = api.get(url, params={"from": "2026-10-20T02:00:00Z", "to": "2026-10-20T04:00:00Z"}, headers=h).json()
    assert [p["battery_v"] for p in window["items"]] == [3.2, 3.3]
    assert api.get(url, params={"cursor": "%%%"}, headers=h).status_code == 400
    assert api.get(url, params={"from": "2026-10-20T02:00:00"}, headers=h).status_code == 422
    assert api.get(url, headers=bearer(tokens, "lead_ornithologist")).status_code == 403
    assert api.get(f"{BASE}/{db.dev('none')}/telemetry", headers=h).status_code == 404


def test_health_docs_cors(api):
    assert api.get("/healthz").json() == {"status": "ok"}
    assert "/api/v1/devices/{device_id}/telemetry" in api.get("/openapi.json").json()["paths"]
    r = api.options(BASE, headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
