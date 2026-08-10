from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

connect_args = {}
if settings.database_url.startswith("sqlite"):
    db_path = settings.database_url.split("///")[-1]
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def sync_schema() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        existing_columns = {column["name"] for column in inspector.get_columns(table.name)}
        missing_columns = [column for column in table.columns if column.name not in existing_columns]
        if missing_columns:
            with engine.begin() as connection:
                for column in missing_columns:
                    column_type = column.type.compile(dialect=engine.dialect)
                    connection.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column_type}'))
                    if column.default is not None and column.default.is_scalar:
                        connection.execute(
                            text(f'UPDATE "{table.name}" SET "{column.name}" = :value WHERE "{column.name}" IS NULL'),
                            {"value": column.default.arg},
                        )

        existing_indexes = {index["name"] for index in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name not in existing_indexes:
                index.create(bind=engine)
