"""refresh_tokens для модуля авторизации

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-25

AI_AGENTS_SPEC.md §4.2: refresh token хранится в БД и отзывается при
logout. В таблице лежит только jti токена (идентификатор из JWT), сам
токен не хранится.

При /refresh старый токен отзывается и заменяется новым (replaced_by).
Повторное предъявление отозванного токена отзывает все токены
пользователя: так обнаруживается кража refresh-токена.
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE refresh_tokens (
            jti         UUID PRIMARY KEY,
            user_id     UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            issued_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at  TIMESTAMPTZ NOT NULL,
            revoked_at  TIMESTAMPTZ,
            replaced_by UUID,
            CHECK (expires_at > issued_at)
        )
        """
    )
    op.execute(
        "CREATE INDEX refresh_tokens_user_active_idx ON refresh_tokens (user_id) "
        "WHERE revoked_at IS NULL"
    )
    op.execute("CREATE INDEX refresh_tokens_expires_idx ON refresh_tokens (expires_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS refresh_tokens")
