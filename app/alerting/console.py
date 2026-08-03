from app.alerting.base import Notifier
from app.models import Alert


class ConsoleNotifier(Notifier):
    def send(self, alert: Alert) -> None:
        print(f"[ARObserver] {alert.alert_type} - hedef #{alert.target_id}: {alert.message}")
