"""REST устройств, журнала обслуживания и телеметрии.

Все эндпоинты защищены JWT (auth_service). Права — auth_service/roles.py:
devices:read, devices:write, maintenance:write, telemetry:read.
B2B-клиент видит только устройства своего client_id (require_scope).
"""

import base64
import binascii
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import AwareDatetime, BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from auth_service import ClientScope, JWTClaims, Permission, require_permission, require_scope

from .payloads import DEVICE_ID_RE

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])

DeviceStatus = Literal["registered", "active", "maintenance", "retired"]
MaintenanceKind = Literal["installation", "inspection", "repair", "battery", "calibration", "removal", "other"]
Latitude = Annotated[float, Field(ge=-90, le=90)]
Longitude = Annotated[float, Field(ge=-180, le=180)]
Orientation = Annotated[float, Field(ge=0, lt=360)]

can_read = require_permission(Permission.DEVICES_READ)
can_write = require_permission(Permission.DEVICES_WRITE)
can_maintain = require_permission(Permission.MAINTENANCE_WRITE)
can_read_telemetry = require_permission(Permission.TELEMETRY_READ)
client_scope = require_scope("client")


class DeviceIn(BaseModel):
    device_id: str = Field(pattern=DEVICE_ID_RE.pattern)
    name: str | None = Field(default=None, max_length=200)
    client_id: UUID | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    orientation_deg: Orientation | None = None
    installed_at: AwareDatetime | None = None
    status: DeviceStatus = "registered"
    firmware_version: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _both_coords(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude и longitude задаются вместе")
        return self


class DevicePatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    client_id: UUID | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    orientation_deg: Orientation | None = None
    installed_at: AwareDatetime | None = None
    status: DeviceStatus | None = None
    firmware_version: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _both_coords(self):
        given = self.model_fields_set
        if ("latitude" in given) != ("longitude" in given):
            raise ValueError("latitude и longitude меняются вместе")
        if "status" in given and self.status is None:
            raise ValueError("status не может быть пустым")
        return self


class Device(BaseModel):
    id: UUID
    device_id: str
    name: str | None
    client_id: UUID | None
    latitude: float | None
    longitude: float | None
    orientation_deg: float | None
    installed_at: datetime | None
    status: str
    firmware_version: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class DeviceList(BaseModel):
    items: list[Device]
    limit: int
    offset: int


class MaintenanceIn(BaseModel):
    performed_at: AwareDatetime
    kind: MaintenanceKind
    orientation_deg: Orientation | None = None
    notes: str | None = Field(default=None, max_length=2000)


class Maintenance(BaseModel):
    id: UUID
    device_id: str
    performed_by: UUID | None
    performed_at: datetime
    kind: str
    orientation_deg: float | None
    notes: str | None
    created_at: datetime


class TelemetryPoint(BaseModel):
    id: UUID
    timestamp_utc: datetime
    battery_v: float | None
    temperature_c: float | None
    bird_flag: bool | None
    bird_probability: float | None
    azimuth_geo_deg: float | None
    azimuth_confidence: float | None
    track_id: str | None
    quality_flag: str | None
    event_id: UUID | None


class TelemetryPage(BaseModel):
    device_id: str
    items: list[TelemetryPoint]
    next_cursor: str | None


_DEVICE_COLUMNS = """
    d.id, d.device_id, d.name, d.client_id,
    ST_Y(d.installation_geo::geometry) AS latitude, ST_X(d.installation_geo::geometry) AS longitude,
    d.orientation_deg, d.installed_at, d.status, d.firmware_version, d.notes, d.created_at, d.updated_at
"""


def _engine(request: Request):
    return request.app.state.engine


def _device(row) -> Device:
    return Device.model_validate(dict(row._mapping))


async def _get_device(conn, device_id: str, scope: ClientScope) -> Device:
    where, params = scope.sql("d.client_id")
    row = (
        await conn.execute(
            text(f"SELECT {_DEVICE_COLUMNS} FROM devices d WHERE d.device_id = :device_id AND {where}"),
            {"device_id": device_id, **params},
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="device_not_found")
    return _device(row)


def _point(lat, lon) -> str | None:
    if lat is None:
        return None
    return f"SRID=4326;POINT({lon} {lat})"


@router.get("", response_model=None)
async def list_devices(
    request: Request,
    claims: JWTClaims = Depends(can_read),
    scope: ClientScope = Depends(client_scope),
    status_filter: DeviceStatus | None = Query(default=None, alias="status"),
    format: Literal["json", "geojson"] = "json",
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Список датчиков. format=geojson — FeatureCollection точек установки для карты."""
    where, params = scope.sql("d.client_id")
    sql = f"SELECT {_DEVICE_COLUMNS} FROM devices d WHERE {where}"
    if status_filter:
        sql += " AND d.status = :status"
        params["status"] = status_filter
    sql += " ORDER BY d.device_id LIMIT :limit OFFSET :offset"
    async with _engine(request).connect() as conn:
        rows = (await conn.execute(text(sql), {**params, "limit": limit, "offset": offset})).all()
    devices = [_device(r) for r in rows]
    if format == "geojson":
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": d.device_id,
                    "geometry": None
                    if d.latitude is None
                    else {"type": "Point", "coordinates": [d.longitude, d.latitude]},
                    "properties": d.model_dump(mode="json", exclude={"latitude", "longitude"}),
                }
                for d in devices
            ],
        }
    return DeviceList(items=devices, limit=limit, offset=offset)


@router.get("/{device_id}", response_model=Device)
async def get_device(
    device_id: str, request: Request, claims=Depends(can_read), scope: ClientScope = Depends(client_scope)
):
    async with _engine(request).connect() as conn:
        return await _get_device(conn, device_id, scope)


@router.post("", response_model=Device, status_code=status.HTTP_201_CREATED)
async def create_device(body: DeviceIn, request: Request, claims=Depends(can_write)):
    async with _engine(request).begin() as conn:
        try:
            await conn.execute(
                text(
                    """
                    INSERT INTO devices (device_id, name, client_id, installation_geo, orientation_deg,
                                         installed_at, status, firmware_version, notes)
                    VALUES (:device_id, :name, :client_id, CAST(:geo AS geography), :orientation_deg,
                            :installed_at, :status, :firmware_version, :notes)
                    """
                ),
                {**body.model_dump(exclude={"latitude", "longitude"}), "geo": _point(body.latitude, body.longitude)},
            )
        except IntegrityError as exc:
            raise _integrity(exc) from exc
        return await _get_device(conn, body.device_id, ClientScope(claims))


@router.patch("/{device_id}", response_model=Device)
async def update_device(device_id: str, body: DevicePatch, request: Request, claims=Depends(can_write)):
    changes = body.model_dump(exclude_unset=True)
    sets, params = [], {"device_id": device_id}
    if "latitude" in changes:
        sets.append("installation_geo = CAST(:geo AS geography)")
        params["geo"] = _point(changes.pop("latitude"), changes.pop("longitude"))
    for key, value in changes.items():
        sets.append(f"{key} = :{key}")
        params[key] = value
    async with _engine(request).begin() as conn:
        if sets:
            try:
                result = await conn.execute(
                    text(f"UPDATE devices SET {', '.join(sets)}, updated_at = now() WHERE device_id = :device_id"),
                    params,
                )
            except IntegrityError as exc:
                raise _integrity(exc) from exc
            if result.rowcount == 0:
                raise HTTPException(status.HTTP_404_NOT_FOUND, detail="device_not_found")
        return await _get_device(conn, device_id, ClientScope(claims))


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(device_id: str, request: Request, claims=Depends(can_write)):
    """Удаляет датчик без данных. Датчик с событиями или телеметрией — 409: его списывают status=retired."""
    async with _engine(request).begin() as conn:
        try:
            result = await conn.execute(text("DELETE FROM devices WHERE device_id = :d"), {"d": device_id})
        except IntegrityError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="device_has_data") from exc
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="device_not_found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _integrity(exc: IntegrityError) -> HTTPException:
    msg = str(exc.orig)
    if "devices_device_id_key" in msg:
        return HTTPException(status.HTTP_409_CONFLICT, detail="device_exists")
    if "client_id" in msg:
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="unknown_client")
    return HTTPException(status.HTTP_409_CONFLICT, detail="conflict")


# --- журнал обслуживания -------------------------------------------------

@router.get("/{device_id}/maintenance", response_model=list[Maintenance])
async def list_maintenance(
    device_id: str,
    request: Request,
    claims=Depends(can_read),
    scope: ClientScope = Depends(client_scope),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    async with _engine(request).connect() as conn:
        await _get_device(conn, device_id, scope)
        rows = (
            await conn.execute(
                text(
                    "SELECT * FROM maintenance_logs WHERE device_id = :d "
                    "ORDER BY performed_at DESC LIMIT :limit OFFSET :offset"
                ),
                {"d": device_id, "limit": limit, "offset": offset},
            )
        ).all()
    return [Maintenance.model_validate(dict(r._mapping)) for r in rows]


@router.post("/{device_id}/maintenance", response_model=Maintenance, status_code=status.HTTP_201_CREATED)
async def add_maintenance(
    device_id: str, body: MaintenanceIn, request: Request, claims: JWTClaims = Depends(can_maintain)
):
    async with _engine(request).begin() as conn:
        await _get_device(conn, device_id, ClientScope(claims))
        row = (
            await conn.execute(
                text(
                    """
                    INSERT INTO maintenance_logs (device_id, performed_by, performed_at, kind, orientation_deg, notes)
                    VALUES (:d, (SELECT id FROM users WHERE id = :uid), :performed_at, :kind, :orientation_deg, :notes)
                    RETURNING *
                    """
                ),
                {"d": device_id, "uid": claims.sub, **body.model_dump()},
            )
        ).first()
    return Maintenance.model_validate(dict(row._mapping))


# --- телеметрия ----------------------------------------------------------

def _encode_cursor(ts: datetime, row_id: UUID) -> str:
    return base64.urlsafe_b64encode(f"{ts.isoformat()}|{row_id}".encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        ts, row_id = raw.split("|")
        return datetime.fromisoformat(ts), UUID(row_id)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_cursor") from exc


@router.get("/{device_id}/telemetry", response_model=TelemetryPage)
async def device_telemetry(
    device_id: str,
    request: Request,
    claims=Depends(can_read_telemetry),
    scope: ClientScope = Depends(client_scope),
    from_: AwareDatetime | None = Query(default=None, alias="from"),
    to: AwareDatetime | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    cursor: str | None = None,
):
    """Таймсерия телеметрии из TimescaleDB по возрастанию времени. Курсор — из next_cursor."""
    sql = (
        "SELECT id, timestamp_utc, battery_v, temperature_c, bird_flag, bird_probability, azimuth_geo_deg, "
        "azimuth_confidence, track_id, quality_flag, event_id FROM telemetry WHERE device_id = :d"
    )
    params: dict = {"d": device_id, "limit": limit + 1}
    if from_:
        sql += " AND timestamp_utc >= :from_"
        params["from_"] = from_
    if to:
        sql += " AND timestamp_utc < :to"
        params["to"] = to
    if cursor:
        params["c_ts"], params["c_id"] = _decode_cursor(cursor)
        sql += " AND (timestamp_utc, id) > (:c_ts, :c_id)"
    sql += " ORDER BY timestamp_utc, id LIMIT :limit"
    async with _engine(request).connect() as conn:
        await _get_device(conn, device_id, scope)
        rows = (await conn.execute(text(sql), params)).all()
    items = [TelemetryPoint.model_validate(dict(r._mapping)) for r in rows[:limit]]
    next_cursor = _encode_cursor(items[-1].timestamp_utc, items[-1].id) if len(rows) > limit else None
    return TelemetryPage(device_id=device_id, items=items, next_cursor=next_cursor)
