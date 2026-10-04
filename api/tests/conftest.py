"""pytest 共通フィクスチャ。

テストは **実 PostgreSQL** に対して走らせる。CITEXT / JSONB / INET / ARRAY /
``gen_random_uuid()`` といった Postgres 専用機能をモデルが多用しており、SQLite では
忠実に再現できないため。Docker で ``postgres:16`` を 1 コンテナだけ起動し、
セッション全体で使い回す。

ポイント:
- engine / SessionLocal を ``NullPool`` 版に差し替える。pytest-asyncio の
  function スコープのイベントループをまたいで asyncpg コネクションが再利用されると
  「Future attached to a different loop」で落ちるため、コネクションを毎回開閉する。
- 各テストの前に全テーブルを TRUNCATE して分離する（アプリは本物の commit をする）。
- 認証は httpx AsyncClient の cookie jar に任せる。register/login で Set-Cookie が
  保存され、以降のリクエストで自動送出される。
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import time
from uuid import uuid4

import pytest

# --- DB 接続情報を「app を import する前に」確定させる ---------------------------
# app.core.db は import 時に DATABASE_URL から engine を作るので、ここで固定する。
_PG_PORT = int(os.environ.get("MEISHI_TEST_PG_PORT", "54330"))
_PG_USER = "meishi"
_PG_PASSWORD = "meishi"
_PG_DB = "meishi_test"
_CONTAINER = f"meishidb_test_pg_{_PG_PORT}"

DATABASE_URL = (
    f"postgresql+asyncpg://{_PG_USER}:{_PG_PASSWORD}@127.0.0.1:{_PG_PORT}/{_PG_DB}"
)
_PSYCOPG_DSN = f"postgresql://{_PG_USER}:{_PG_PASSWORD}@127.0.0.1:{_PG_PORT}/{_PG_DB}"

os.environ.setdefault("DATABASE_URL", DATABASE_URL)
os.environ["DATABASE_URL"] = DATABASE_URL
os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890")
os.environ["APP_ENV"] = "development"
# サービス系は既定で「未設定 = no-op」。テストで必要な時だけ monkeypatch する。
for _k in (
    "MEILISEARCH_URL",
    "MINIO_ENDPOINT",
    "GEOCODER_URL",
    "SCANNER_API_TOKEN",
    "SCANNER_OWNER_EMAIL",
):
    os.environ.pop(_k, None)


ALL_TABLES = [
    "audit_logs",
    "card_shares",
    "favorites",
    "card_memos",
    "card_tags",
    "card_fields",
    "cards",
    "tags",
    "sessions",
    "webauthn_credentials",
    "users",
]


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], check=check, capture_output=True, text=True)


def _docker_available() -> bool:
    try:
        _docker("info")
        return True
    except Exception:
        return False


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _start_container() -> None:
    _docker("rm", "-f", _CONTAINER, check=False)
    _docker(
        "run",
        "-d",
        "--rm",
        "--name",
        _CONTAINER,
        "-e",
        f"POSTGRES_USER={_PG_USER}",
        "-e",
        f"POSTGRES_PASSWORD={_PG_PASSWORD}",
        "-e",
        f"POSTGRES_DB={_PG_DB}",
        "-p",
        f"{_PG_PORT}:5432",
        "postgres:16",
    )


def _wait_ready(timeout: float = 60.0) -> None:
    import asyncpg

    async def _try() -> bool:
        try:
            conn = await asyncpg.connect(_PSYCOPG_DSN)
            await conn.close()
            return True
        except Exception:
            return False

    deadline = time.time() + timeout
    while time.time() < deadline:
        if asyncio.run(_try()):
            return
        time.sleep(0.5)
    raise RuntimeError("PostgreSQL test container did not become ready in time")


@pytest.fixture(scope="session", autouse=True)
def _database():
    """セッション全体で 1 つの Postgres を用意し、スキーマを作る。"""
    external_pg = _port_in_use(_PG_PORT)
    if not external_pg and not _docker_available():
        pytest.skip("Docker is required for the API test suite (postgres:16)")

    started_here = False
    if not external_pg:
        _start_container()
        started_here = True
        _wait_ready()
    else:
        # 既に起動済み（CI で外部 Postgres を当てる等）。ready だけ確認。
        _wait_ready()

    # --- engine / SessionLocal を NullPool 版に差し替える ---
    # NOTE: スキーマは Alembic マイグレーションで作る。モデル定義の datetime 列は
    # timezone 指定が無く Base.metadata.create_all だと TIMESTAMP WITHOUT TIME ZONE に
    # なってしまい、アプリが tz-aware な値を入れて落ちる。本番（= マイグレーション）の
    # スキーマと一致させるため、ここでも upgrade head を使う。
    from pathlib import Path

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    import app.core.db as dbmod
    import app.models  # noqa: F401  (モデルを metadata に登録)

    test_engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    dbmod.engine = test_engine
    dbmod.SessionLocal = async_sessionmaker(
        test_engine, expire_on_commit=False, class_=dbmod.AsyncSession
    )

    async def _reset_schema() -> None:
        # 外部 Postgres を当てた場合などに備えて public スキーマを作り直す。
        reset_engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
        async with reset_engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        await reset_engine.dispose()

    asyncio.run(_reset_schema())

    # Alembic マイグレーションを head まで適用（env.py が自前で asyncio.run するので
    # ここは sync コンテキストから呼ぶ）。
    from alembic import command
    from alembic.config import Config

    api_root = Path(__file__).resolve().parent.parent
    alembic_cfg = Config(str(api_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(api_root / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(alembic_cfg, "head")

    yield

    asyncio.run(test_engine.dispose())
    if started_here:
        _docker("rm", "-f", _CONTAINER, check=False)


@pytest.fixture(autouse=True)
def _clean_tables(_database):
    """各テスト前に全テーブルを空にする。"""
    from sqlalchemy import text

    import app.core.db as dbmod

    async def _truncate() -> None:
        async with dbmod.engine.begin() as conn:
            await conn.execute(
                text(
                    "TRUNCATE TABLE "
                    + ", ".join(ALL_TABLES)
                    + " RESTART IDENTITY CASCADE"
                )
            )

    asyncio.run(_truncate())
    # webauthn のオンメモリ challenge も毎テストでクリア
    try:
        from app.routers import webauthn as wa

        wa._CHALLENGES.clear()
    except Exception:
        pass
    yield


# ----------------------------- アプリ / クライアント -----------------------------


@pytest.fixture(scope="session")
def app(_database):
    from app.main import create_app

    return create_app()


@pytest.fixture
async def client_factory(app):
    """cookie jar が独立した AsyncClient を必要なだけ作るファクトリ。"""
    from httpx import ASGITransport, AsyncClient

    clients: list[AsyncClient] = []

    def _make() -> AsyncClient:
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(c)
        return c

    yield _make

    for c in clients:
        await c.aclose()


@pytest.fixture
async def client(client_factory):
    """未認証のクライアント。"""
    return client_factory()


@pytest.fixture
async def make_user(client_factory):
    """ユーザーを register して、認証済みクライアントと user JSON を返すファクトリ。

    最初に作られたユーザーは admin、以降は member（アプリの仕様）。
    """

    async def _make(
        email: str | None = None,
        password: str = "password123",
        display_name: str | None = None,
    ):
        email = email or f"user_{uuid4().hex[:10]}@example.com"
        display_name = display_name or email.split("@")[0]
        c = client_factory()
        r = await c.post(
            "/api/auth/register",
            json={"email": email, "display_name": display_name, "password": password},
        )
        assert r.status_code == 201, r.text
        return c, r.json()

    return _make


@pytest.fixture
async def admin(make_user):
    """先頭ユーザー（= admin）。(client, user)。"""
    return await make_user(email="admin@example.com", display_name="Admin")


@pytest.fixture
async def db():
    """テスト側から DB を直接覗くためのセッション。"""
    import app.core.db as dbmod

    async with dbmod.SessionLocal() as session:
        yield session
