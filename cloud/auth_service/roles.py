"""Роли MVP и права, которые попадают в claim `permissions`.

Роли — AI_AGENTS_SPEC.md §4.2, их строки лежат в таблице roles (миграция
0004). Набор прав — черновик для ревью Lead Backend и CTO: он собран из
сценариев doc_v2/roles/06_GIS.md (B2B-клиент не видит очередь Unknown и
флот, полевой инженер видит флот) и списка роутеров AI_AGENTS_SPEC.md §4.3.
Права зашиты в код, а не в БД: смена набора — это смена контракта.
"""

from enum import StrEnum


class Role(StrEnum):
    SUPER_ADMIN = "super_admin"
    LEAD_ORNITHOLOGIST = "lead_ornithologist"
    FIELD_ENGINEER = "field_engineer"
    B2B_CLIENT = "b2b_client"


class Permission(StrEnum):
    USERS_MANAGE = "users:manage"
    CLIENTS_MANAGE = "clients:manage"
    DEVICES_READ = "devices:read"
    DEVICES_WRITE = "devices:write"
    MAINTENANCE_WRITE = "maintenance:write"
    TELEMETRY_READ = "telemetry:read"
    EVENTS_READ = "events:read"
    TRACKS_READ = "tracks:read"
    SPECIES_READ = "species:read"
    SPECIES_WRITE = "species:write"
    UNKNOWN_QUEUE_READ = "unknown_queue:read"
    UNKNOWN_QUEUE_VERIFY = "unknown_queue:verify"
    EXPORT_READ = "export:read"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.SUPER_ADMIN: frozenset(Permission),
    Role.LEAD_ORNITHOLOGIST: frozenset(
        {
            Permission.DEVICES_READ,
            Permission.EVENTS_READ,
            Permission.TRACKS_READ,
            Permission.SPECIES_READ,
            Permission.SPECIES_WRITE,
            Permission.UNKNOWN_QUEUE_READ,
            Permission.UNKNOWN_QUEUE_VERIFY,
            Permission.EXPORT_READ,
        }
    ),
    Role.FIELD_ENGINEER: frozenset(
        {
            Permission.DEVICES_READ,
            Permission.DEVICES_WRITE,
            Permission.MAINTENANCE_WRITE,
            Permission.TELEMETRY_READ,
            Permission.EVENTS_READ,
            Permission.TRACKS_READ,
            Permission.SPECIES_READ,
        }
    ),
    Role.B2B_CLIENT: frozenset(
        {
            Permission.EVENTS_READ,
            Permission.TRACKS_READ,
            Permission.SPECIES_READ,
            Permission.EXPORT_READ,
        }
    ),
}

# Роли, чьи данные ограничены своим client_id (@require_scope("client")).
CLIENT_SCOPED_ROLES: frozenset[Role] = frozenset({Role.B2B_CLIENT})


def permissions_for(role: Role) -> list[str]:
    """Права роли в стабильном порядке — так они ложатся в JWT."""
    return sorted(p.value for p in ROLE_PERMISSIONS[role])
