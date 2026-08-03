from fastapi import FastAPI
from sqlalchemy import text

from app.database import Base, SessionLocal, engine
from app import models
from app.targets_loader import sync_targets

app = FastAPI(title="ARObserver")


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        sync_targets(db)


@app.get("/health")
def health():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok"}
