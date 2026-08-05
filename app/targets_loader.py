from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Target


def read_targets_yaml(path: str | None = None) -> list[dict]:
    yaml_path = Path(path or settings.targets_file)
    if not yaml_path.exists():
        return []
    with yaml_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    return data.get("targets", [])


def seed_targets_if_empty(db: Session, path: str | None = None) -> None:
    if db.query(Target).first() is not None:
        return

    for definition in read_targets_yaml(path):
        db.add(
            Target(
                name=definition["name"],
                url=definition["url"],
                interval_minutes=definition.get("interval_minutes", settings.default_check_interval_minutes),
                tags=definition.get("tags", []),
                expected_keyword=definition.get("expected_keyword"),
            )
        )
    db.commit()
