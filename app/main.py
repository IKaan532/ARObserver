import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI
from nicegui import ui
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from app.api import alerts, checks, targets
from app.auth import AuthMiddleware
from app.config import settings
from app.database import Base, engine, sync_schema
from app import models
from app.scheduler import start_scheduler, stop_scheduler
import app.ui.pages  # noqa: F401 registers NiceGUI page routes

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    sync_schema()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="ARObserver", lifespan=lifespan)
app.include_router(targets.router)
app.include_router(checks.router)
app.include_router(alerts.router)


@app.get("/health")
def health():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok"}


storage_secret = settings.storage_secret
if not storage_secret:
    storage_secret = secrets.token_urlsafe(32)
    logger.warning(
        "STORAGE_SECRET ayarlanmamış! Geçici bir değer üretildi — her yeniden başlatmada "
        "tüm oturumlar sonlanacak. Kalıcı olması için .env dosyasına STORAGE_SECRET ekleyin."
    )

# AuthMiddleware önce (iç katman), SessionMiddleware sonra (dış katman) eklenir ki
# istek AuthMiddleware'e ulaşmadan önce oturum çözümlenmiş olsun. NiceGUI, ui.run_with
# kendi iç uygulamasını (core.app) bu app'a alt-mount eder ve SessionMiddleware'i
# zaten burada (parent_app'ta) bulduğu için kendi ayrı bir tanesini eklemez — tek
# oturum çerezi paylaşılır.
app.add_middleware(AuthMiddleware)
app.add_middleware(SessionMiddleware, secret_key=storage_secret)

ui.run_with(app, title="ARObserver", language="tr", storage_secret=storage_secret)
