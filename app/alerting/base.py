from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AlertPayload:
    id: int
    alert_type: str
    target_id: int
    message: str
    created_at: datetime


class Notifier(ABC):
    @abstractmethod
    def send(self, alert: AlertPayload) -> None:
        raise NotImplementedError
