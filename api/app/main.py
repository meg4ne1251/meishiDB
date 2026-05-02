from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import configure_logging, log
from app.routers import auth, cards, export, scanner, search, tags, users, webauthn
from app.services import storage


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info("api.startup", env=get_settings().app_env)
    try:
        storage.ensure_buckets()
    except Exception as e:
        log.warning("storage.bootstrap_failed", error=str(e))
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="meishiDB API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router, prefix="/api")
    app.include_router(webauthn.router, prefix="/api")
    app.include_router(cards.router, prefix="/api")
    app.include_router(tags.router, prefix="/api")
    app.include_router(users.router, prefix="/api")
    app.include_router(search.router, prefix="/api")
    app.include_router(export.router, prefix="/api")
    app.include_router(scanner.router, prefix="/api")
    return app


app = create_app()
