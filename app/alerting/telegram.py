import httpx

from app.alerting.base import Notifier
from app.config import settings
from app.models import Alert

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
REQUEST_TIMEOUT = 10.0


class TelegramNotifier(Notifier):
    def send(self, alert: Alert) -> None:
        url = TELEGRAM_API_URL.format(token=settings.telegram_bot_token)
        text = f"[ARObserver] {alert.alert_type} — hedef #{alert.target_id}: {alert.message}"
        response = httpx.post(
            url,
            json={"chat_id": settings.telegram_chat_id, "text": text},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
