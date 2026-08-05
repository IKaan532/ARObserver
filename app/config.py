from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "sqlite:///./data/arobserver.db"
    targets_file: str = "targets.yaml"
    display_timezone: str = "Europe/Istanbul"
    log_level: str = "INFO"
    retention_days: int = 90
    default_check_interval_minutes: int = 5
    alert_fail_threshold: int = 3
    cert_expiry_warn_days: str = "30,14,7"

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""

    @property
    def cert_expiry_warn_days_list(self) -> list[int]:
        return [int(value) for value in self.cert_expiry_warn_days.split(",") if value]


settings = Settings()

SCORING_VERSION = 4

SCORE_CATEGORIES = {
    "tls_certificate": {"label": "TLS Sertifika Geçerliliği", "max_points": 25},
    "security_headers": {"label": "Güvenlik Başlıkları", "max_points": 30},
    "tls_protocol": {"label": "TLS Sürümü ve Şifre", "max_points": 15},
    "https_redirect": {"label": "HTTPS Yönlendirme", "max_points": 10},
    "content_integrity": {"label": "İçerik Bütünlüğü", "max_points": 10},
    "info_leak": {"label": "Bilgi Sızıntısı", "max_points": 5},
    "compression": {"label": "Sıkıştırma", "max_points": 5},
}

TLS_CERTIFICATE_RULES = {
    "https_not_used": {"points": 25, "message": "Hedef HTTPS kullanmıyor"},
    "invalid_chain": {"points": 15, "message": "TLS sertifika zinciri geçersiz"},
    "expired": {"points": 25, "message": "TLS sertifikasının süresi dolmuş"},
    "expiring_under_7_days": {"points": 15, "message": "TLS sertifikasının bitişine {days} günden az kaldı"},
    "expiring_under_14_days": {"points": 10, "message": "TLS sertifikasının bitişine {days} günden az kaldı"},
    "expiring_under_30_days": {"points": 5, "message": "TLS sertifikasının bitişine {days} gün kaldı"},
}

SECURITY_HEADER_RULES = {
    "Strict-Transport-Security": {"points": 8, "message": "Strict-Transport-Security başlığı eksik"},
    "Content-Security-Policy": {"points": 8, "message": "Content-Security-Policy başlığı eksik"},
    "X-Content-Type-Options": {"points": 5, "message": "X-Content-Type-Options başlığı eksik"},
    "X-Frame-Options": {"points": 5, "message": "X-Frame-Options başlığı eksik"},
    "Referrer-Policy": {"points": 2, "message": "Referrer-Policy başlığı eksik"},
    "Permissions-Policy": {"points": 2, "message": "Permissions-Policy başlığı eksik"},
}

TLS_PROTOCOL_RULES = {
    "https_not_used": {"points": 15, "message": "Hedef HTTPS kullanmıyor"},
    "weak_protocol": {"points": 10, "message": "TLS 1.0 veya 1.1 kabul ediliyor"},
    "no_tls13": {"points": 3, "message": "TLS 1.3 desteklenmiyor"},
    "weak_cipher": {"points": 5, "message": "Zayıf şifre takımı kullanılıyor ({cipher})"},
}

HTTPS_REDIRECT_RULES = {
    "not_redirecting": {"points": 10, "message": "HTTP, HTTPS'e yönlendirilmiyor"},
}

CONTENT_INTEGRITY_RULES = {
    "critical_change": {"points": 10, "message": "Sayfa başlığı veya H1 metni temel çizgiden değişti"},
}

INFO_LEAK_RULES = {
    "version_leak": {"points": 5, "message": "{header} başlığı sürüm bilgisi sızdırıyor"},
}

COMPRESSION_RULES = {
    "no_compression": {"points": 5, "message": "Yanıt sıkıştırılmıyor (Content-Encoding yok)"},
}

CERT_EXPIRY_SCORE_WARN_DAYS = 30

LETTER_GRADE_THRESHOLDS = [
    (90, "A"),
    (80, "B"),
    (70, "C"),
    (60, "D"),
    (0, "F"),
]
