"""Модуль авторизации AI-bird: вход по email и паролю, JWT RS256, RBAC.

Другие сервисы работают с ним только через JWT: проверяют подпись по
публичному ключу (файл или /api/v1/auth/.well-known/jwks.json) и читают
claims. Внутрь модуля и в его таблицы они не ходят.

Спецификация — doc_v2/AI_AGENTS_SPEC.md §4.2.
"""

from .claims import JWTClaims
from .deps import ClientScope, get_current_claims, require_permission, require_role, require_scope
from .provider import AuthProvider, InvalidCredentials, PasswordAuthProvider, PasswordCredentials
from .roles import ROLE_PERMISSIONS, Permission, Role

__all__ = [
    "AuthProvider",
    "ClientScope",
    "InvalidCredentials",
    "JWTClaims",
    "PasswordAuthProvider",
    "PasswordCredentials",
    "Permission",
    "ROLE_PERMISSIONS",
    "Role",
    "get_current_claims",
    "require_permission",
    "require_role",
    "require_scope",
]
