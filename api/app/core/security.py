"""パスワード（Argon2id）と簡易セッショントークン生成。

WebAuthn/passkey は別ファイル（後続実装）。今は username+password でログインし、
セッション ID を Cookie に載せて DB に保存する。
"""

import secrets

from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _pwd_context.verify(password, password_hash)
    except Exception:
        return False


def generate_session_token() -> str:
    """URL safe 32 byte トークン（DB に保存される ID 兼用）。"""
    return secrets.token_urlsafe(32)
