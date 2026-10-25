"""Seed: четыре роли MVP

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-25

Роли — AI_AGENTS_SPEC.md §4.2.

Виды в этот seed не входят. Таблица species создана в 0001 и остаётся
пустой, пока в doc_v2/IMPLEMENTATION_PLAN.md §8 строка «Список 50 видов»
не закрыта орнитологом (пакет CLOUD-001). Загрузка из
data/species/species.csv — отдельной миграцией после этого.
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

ROLES = (
    ("super_admin", "Полный доступ: пользователи, клиенты, устройства, настройки"),
    ("lead_ornithologist", "Верификация видов и очереди Unknown, справочник видов"),
    ("field_engineer", "Устройства, установка, журнал обслуживания"),
    ("b2b_client", "Чтение данных только своего client_id"),
)


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    rows = ",\n".join(f"({_quote(name)}, {_quote(desc)})" for name, desc in ROLES)
    op.execute(
        f"INSERT INTO roles (name, description) VALUES\n{rows}\n"
        "ON CONFLICT (name) DO NOTHING"
    )


def downgrade() -> None:
    names = ", ".join(_quote(name) for name, _ in ROLES)
    op.execute(f"DELETE FROM roles WHERE name IN ({names})")
