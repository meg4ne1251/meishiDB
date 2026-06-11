"""パスワードハッシュとセッショントークン生成（純粋ロジック）。"""

from app.core.security import generate_session_token, hash_password, verify_password


def test_hash_password_is_not_plaintext():
    h = hash_password("password123")
    assert h != "password123"
    assert h.startswith("$argon2")


def test_hash_password_is_salted_and_unique():
    assert hash_password("samepass") != hash_password("samepass")


def test_verify_password_roundtrip():
    h = hash_password("correct horse battery")
    assert verify_password("correct horse battery", h) is True
    assert verify_password("wrong", h) is False


def test_verify_password_handles_garbage_hash():
    # 不正なハッシュでも例外を投げず False を返す
    assert verify_password("anything", "not-a-real-hash") is False
    assert verify_password("anything", "") is False


def test_generate_session_token_unique_and_urlsafe():
    tokens = {generate_session_token() for _ in range(100)}
    assert len(tokens) == 100
    for t in tokens:
        # token_urlsafe(32) はおおむね 43 文字
        assert len(t) >= 40
        assert all(c.isalnum() or c in "-_" for c in t)
