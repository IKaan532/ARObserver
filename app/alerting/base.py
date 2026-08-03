from abc import ABC, abstractmethod

from app.models import Alert


class Notifier(ABC):
    @abstractmethod
    def send(self, alert: Alert) -> None:
        raise NotImplementedError
