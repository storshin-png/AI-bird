"""Команды стенда.

    python -m auth_service keys                  # пара RSA в auth_service/keys/
    python -m auth_service create-user --email admin@aibird.local --role super_admin

Пароль спрашивается в терминале. Без терминала берётся из переменной
AIBIRD_NEW_PASSWORD.
"""

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path
from uuid import UUID

from .config import DEFAULT_KEYS_DIR, Settings
from .passwords import WeakPasswordError, hash_password
from .roles import Role
from .store import SqlAuthStore, UnknownRole, UserAlreadyExists
from .tokens import write_key_pair


def _read_password() -> str:
    env = os.environ.get("AIBIRD_NEW_PASSWORD")
    if env:
        return env
    first = getpass.getpass("Пароль: ")
    second = getpass.getpass("Повторите пароль: ")
    if first != second:
        raise SystemExit("Пароли не совпали")
    return first


async def _create_user(args, store_factory=SqlAuthStore.from_url) -> UUID:
    settings = Settings.from_env()
    role = Role(args.role)
    client_id = UUID(args.client_id) if args.client_id else None
    if role is Role.B2B_CLIENT and client_id is None:
        raise SystemExit("Для роли b2b_client нужен --client-id")
    password_hash = hash_password(_read_password())
    store = store_factory(settings.database_url)
    try:
        return await store.create_user(args.email.strip(), password_hash, role, client_id, args.full_name)
    finally:
        await store.close()


def main(argv: list[str] | None = None, store_factory=SqlAuthStore.from_url) -> int:
    parser = argparse.ArgumentParser(prog="python -m auth_service")
    sub = parser.add_subparsers(dest="command", required=True)

    keys = sub.add_parser("keys", help="создать пару ключей RS256")
    keys.add_argument("--out", type=Path, default=DEFAULT_KEYS_DIR)
    keys.add_argument("--bits", type=int, default=3072)
    keys.add_argument("--force", action="store_true", help="перезаписать существующие ключи")

    user = sub.add_parser("create-user", help="добавить пользователя")
    user.add_argument("--email", required=True)
    user.add_argument("--role", required=True, choices=[r.value for r in Role])
    user.add_argument("--client-id")
    user.add_argument("--full-name")

    args = parser.parse_args(argv)

    if args.command == "keys":
        try:
            priv, pub = write_key_pair(args.out, args.bits, overwrite=args.force)
        except FileExistsError as exc:
            print(f"{exc}. Чтобы заменить, добавьте --force", file=sys.stderr)
            return 1
        print(f"Закрытый ключ: {priv}\nПубличный ключ: {pub}")
        return 0

    try:
        user_id = asyncio.run(_create_user(args, store_factory))
    except WeakPasswordError as exc:
        print(f"Пароль не подходит: {exc}", file=sys.stderr)
        return 1
    except UserAlreadyExists:
        print(f"Пользователь {args.email} уже есть", file=sys.stderr)
        return 1
    except UnknownRole as exc:
        print(f"Роли {exc} нет в таблице roles: примените миграции (alembic upgrade head)", file=sys.stderr)
        return 1
    print(f"Создан пользователь {args.email}, id {user_id}")
    return 0
