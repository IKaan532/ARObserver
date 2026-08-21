import ipaddress
import socket
from urllib.parse import urlparse

import httpx

from app.alerting.base import AlertPayload, Notifier
from app.config import settings

REQUEST_TIMEOUT = 10.0


def _reject_reason_for_hostname(hostname: str) -> str | None:
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return "Webhook alan adı çözümlenemedi."
    for info in addr_infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return "Webhook hedefi özel/yerel bir ağ adresine çözümleniyor, engellendi."
    return None


class WebhookNotifier(Notifier):
    def send(self, alert: AlertPayload) -> None:
        hostname = (urlparse(settings.webhook_url).hostname or "").lower()
        if not hostname:
            raise ValueError("WEBHOOK_URL geçersiz.")
        reject_reason = _reject_reason_for_hostname(hostname)
        if reject_reason:
            raise ValueError(reject_reason)

        payload = {
            "alert_id": alert.id,
            "alert_type": alert.alert_type,
            "target_id": alert.target_id,
            "message": alert.message,
            "created_at": alert.created_at.isoformat(),
        }
        response = httpx.post(settings.webhook_url, json=payload, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
