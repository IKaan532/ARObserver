from fastapi import FastAPI
from sqlalchemy import text

from app.database import engine

app = FastAPI(title="ARObserver")


@app.get("/health")
def health():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok"}
