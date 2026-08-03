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


def sync_targets(db: Session, path: str | None = None) -> None:
    yaml_by_url = {definition["url"]: definition for definition in read_targets_yaml(path)}
    existing_by_url = {target.url: target for target in db.query(Target).all()}

    for url, definition in yaml_by_url.items():
        target = existing_by_url.get(url)
        interval = definition.get("interval_minutes", settings.default_check_interval_minutes)
        tags = definition.get("tags", [])
        if target is None:
            db.add(Target(name=definition["name"], url=url, interval_minutes=interval, tags=tags))
        else:
            target.name = definition["name"]
            target.interval_minutes = interval
            target.tags = tags

    for url, target in existing_by_url.items():
        if url not in yaml_by_url:
            db.delete(target)

    db.commit()
