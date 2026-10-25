"""Claims access-токена: sub, email, role, client_id, permissions, exp."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from .roles import Role, permissions_for


@dataclass(frozen=True)
class JWTClaims:
    sub: UUID
    email: str
    role: Role
    client_id: UUID | None
    permissions: tuple[str, ...] = field(default=())
    exp: datetime | None = None

    @classmethod
    def for_user(cls, user_id: UUID, email: str, role: Role, client_id: UUID | None) -> "JWTClaims":
        return cls(
            sub=user_id,
            email=email,
            role=role,
            client_id=client_id,
            permissions=tuple(permissions_for(role)),
        )

    def has_permissions(self, *perms: str) -> bool:
        return set(perms) <= set(self.permissions)
