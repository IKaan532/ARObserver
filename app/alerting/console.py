from app.alerting.base import AlertPayload, Notifier


class ConsoleNotifier(Notifier):
    def send(self, alert: AlertPayload) -> None:
        print(f"[ARObserver] {alert.alert_type} - hedef #{alert.target_id}: {alert.message}")
