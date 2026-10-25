"""Хеширование паролей bcrypt.

Passlib не используется: проект не обновляется с 2020 года и ломается на
bcrypt 4.1+. Функции bcrypt hashpw/checkpw/gensalt стабильны во всех
версиях.

bcrypt учитывает только первые 72 байта пароля. Длиннее не принимаем,
чтобы два разных пароля с общим началом не давали один хеш.
"""

import bcrypt

MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = 10
BCRYPT_ROUNDS = 12

# Хеш для выравнивания времени ответа, когда пользователя нет.
_DUMMY_HASH = bcrypt.hashpw(b"aibird-dummy-password", bcrypt.gensalt(BCRYPT_ROUNDS))


class WeakPasswordError(ValueError):
    pass


def validate_new_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(f"Пароль короче {MIN_PASSWORD_LENGTH} символов")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise WeakPasswordError(f"Пароль длиннее {MAX_PASSWORD_BYTES} байт в UTF-8")


def hash_password(password: str, rounds: int = BCRYPT_ROUNDS) -> str:
    validate_new_password(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds)).decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    """Сверяет пароль. Без хеша тратит то же время и возвращает False."""
    raw = password.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        raw = raw[:MAX_PASSWORD_BYTES]
        too_long = True
    else:
        too_long = False
    if not password_hash:
        bcrypt.checkpw(raw, _DUMMY_HASH)
        return False
    try:
        ok = bcrypt.checkpw(raw, password_hash.encode("ascii"))
    except ValueError:
        return False
    return ok and not too_long
