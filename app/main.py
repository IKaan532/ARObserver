from fastapi import FastAPI
from sqlalchemy import text

from app.database import Base, engine
from app import models

app = FastAPI(title="ARObserver")


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok"}
