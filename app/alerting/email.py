import smtplib
from email.message import EmailMessage

from app.alerting.base import AlertPayload, Notifier
from app.config import settings


class EmailNotifier(Notifier):
    def send(self, alert: AlertPayload) -> None:
        message = EmailMessage()
        message["Subject"] = f"ARObserver uyarısı: {alert.alert_type}"
        message["From"] = settings.smtp_from
        message["To"] = settings.smtp_to
        message.set_content(alert.message)

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as client:
            client.starttls()
            if settings.smtp_username:
                client.login(settings.smtp_username, settings.smtp_password)
            client.send_message(message)
