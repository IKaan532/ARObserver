from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.api import alerts, checks, targets
from app.database import Base, engine
from app import models
from app.scheduler import start_scheduler, stop_scheduler
from app.web import router as web_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="ARObserver", lifespan=lifespan)
app.include_router(targets.router)
app.include_router(checks.router)
app.include_router(alerts.router)
app.include_router(web_router)


@app.get("/health")
def health():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok"}
