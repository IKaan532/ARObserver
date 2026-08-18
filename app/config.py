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
    deepcheck_service_url: str = "http://deepcheck:8001"
    admin_password_hash: str = ""
    storage_secret: str = ""

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    ct_log_check_enabled: bool = False

    user_agent: str = "ARObserver/1.0 (+https://arnavutkoy.bel.tr)"
    check_retry_delays_seconds: str = "5,15"
    canary_url: str = "https://www.google.com"
    scheduler_jitter_seconds: int = 30

    @property
    def cert_expiry_warn_days_list(self) -> list[int]:
        return [int(value) for value in self.cert_expiry_warn_days.split(",") if value]

    @property
    def check_retry_delays_seconds_list(self) -> list[float]:
        return [float(value) for value in self.check_retry_delays_seconds.split(",") if value]


settings = Settings()

SCORING_VERSION = 8

SCORE_CATEGORIES = {
    "tls_certificate": {"label": "TLS Sertifika Geçerliliği", "max_points": 25},
    "security_headers": {"label": "Güvenlik Başlıkları", "max_points": 30},
    "tls_protocol": {"label": "TLS Sürümü ve Şifre", "max_points": 15},
    "https_redirect": {"label": "HTTPS Yönlendirme", "max_points": 10},
    "content_integrity": {"label": "İçerik Bütünlüğü", "max_points": 10},
    "info_leak": {"label": "Bilgi Sızıntısı", "max_points": 5},
    "compression": {"label": "Sıkıştırma", "max_points": 5},
    "cookie_security": {"label": "Çerez Güvenliği", "max_points": 10},
    "dns_hygiene": {"label": "DNS Hijyeni", "max_points": 10},
}

TLS_CERTIFICATE_RULES = {
    "https_not_used": {"points": 25, "message": "Hedef HTTPS kullanmıyor"},
    "invalid_chain": {"points": 15, "message": "TLS sertifika zinciri geçersiz"},
    "expired": {"points": 25, "message": "TLS sertifikasının süresi dolmuş"},
    "expiring_under_7_days": {"points": 15, "message": "TLS sertifikasının bitişine {days} günden az kaldı"},
    "expiring_under_14_days": {"points": 10, "message": "TLS sertifikasının bitişine {days} günden az kaldı"},
    "expiring_under_30_days": {"points": 5, "message": "TLS sertifikasının bitişine {days} gün kaldı"},
    "weak_signature": {"points": 10, "message": "Sertifika SHA-1 imza kullanıyor"},
    "weak_key": {"points": 10, "message": "Sertifika anahtar uzunluğu {bits} bit (2048 bitten az)"},
}

MOZILLA_OBSERVATORY_STS_MISSING_POINTS = 7
MOZILLA_OBSERVATORY_CSP_MISSING_POINTS = 7
MOZILLA_OBSERVATORY_XFO_MISSING_POINTS = 6
MOZILLA_OBSERVATORY_XCTO_MISSING_POINTS = 4
MOZILLA_OBSERVATORY_REFERRER_POLICY_MISSING_POINTS = 3
MOZILLA_OBSERVATORY_PERMISSIONS_POLICY_MISSING_POINTS = 3

SECURITY_HEADER_RULES = {
    "Strict-Transport-Security": {"points": MOZILLA_OBSERVATORY_STS_MISSING_POINTS, "message": "Strict-Transport-Security başlığı eksik"},
    "Content-Security-Policy": {"points": MOZILLA_OBSERVATORY_CSP_MISSING_POINTS, "message": "Content-Security-Policy başlığı eksik"},
    "X-Frame-Options": {"points": MOZILLA_OBSERVATORY_XFO_MISSING_POINTS, "message": "X-Frame-Options başlığı eksik"},
    "X-Content-Type-Options": {"points": MOZILLA_OBSERVATORY_XCTO_MISSING_POINTS, "message": "X-Content-Type-Options başlığı eksik"},
    "Referrer-Policy": {"points": MOZILLA_OBSERVATORY_REFERRER_POLICY_MISSING_POINTS, "message": "Referrer-Policy başlığı eksik"},
    "Permissions-Policy": {"points": MOZILLA_OBSERVATORY_PERMISSIONS_POLICY_MISSING_POINTS, "message": "Permissions-Policy başlığı eksik"},
}

MOZILLA_OBSERVATORY_HSTS_SHORT_MAX_AGE_POINTS = 2
MOZILLA_OBSERVATORY_HSTS_MISSING_SUBDOMAINS_POINTS = 1
HSTS_RECOMMENDED_MIN_MAX_AGE_SECONDS = 15552000

HSTS_RULES = {
    "short_max_age": {
        "points": MOZILLA_OBSERVATORY_HSTS_SHORT_MAX_AGE_POINTS,
        "message": "HSTS max-age süresi 180 günden az",
    },
    "missing_include_subdomains": {
        "points": MOZILLA_OBSERVATORY_HSTS_MISSING_SUBDOMAINS_POINTS,
        "message": "HSTS includeSubDomains yönergesi eksik",
    },
}

MOZILLA_OBSERVATORY_CSP_UNSAFE_INLINE_POINTS = 3
MOZILLA_OBSERVATORY_CSP_UNSAFE_EVAL_POINTS = 2
MOZILLA_OBSERVATORY_CSP_MISSING_DEFAULT_SRC_POINTS = 2

CSP_RULES = {
    "unsafe_inline": {
        "points": MOZILLA_OBSERVATORY_CSP_UNSAFE_INLINE_POINTS,
        "message": "CSP 'unsafe-inline' kaynağına izin veriyor",
    },
    "unsafe_eval": {
        "points": MOZILLA_OBSERVATORY_CSP_UNSAFE_EVAL_POINTS,
        "message": "CSP 'unsafe-eval' kaynağına izin veriyor",
    },
    "missing_default_src": {
        "points": MOZILLA_OBSERVATORY_CSP_MISSING_DEFAULT_SRC_POINTS,
        "message": "CSP default-src yönergesi eksik",
    },
}

LETTER_GRADE_CEILING_WEAK_TLS_VERSION = "C"
LETTER_GRADE_CEILING_WEAK_CIPHER = "D"
LETTER_GRADE_CEILING_NO_FORWARD_SECRECY = "C"
LETTER_GRADE_CEILING_INVALID_CERTIFICATE = "F"

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

COOKIE_SECURITY_RULES = {
    "missing_secure": {"points": 4, "message": "Bir veya daha fazla çerezde Secure bayrağı eksik"},
    "missing_httponly": {"points": 3, "message": "Bir veya daha fazla çerezde HttpOnly bayrağı eksik"},
    "weak_samesite": {"points": 3, "message": "Bir veya daha fazla çerezde SameSite eksik veya None"},
}

DNS_HYGIENE_RULES = {
    "missing_spf": {"points": 4, "message": "SPF (TXT) kaydı bulunamadı"},
    "missing_dmarc": {"points": 4, "message": "DMARC (TXT, _dmarc) kaydı bulunamadı"},
    "missing_caa": {"points": 2, "message": "CAA kaydı bulunamadı"},
}

CERT_EXPIRY_SCORE_WARN_DAYS = 30

KNOWN_TRACKER_DOMAINS = [
    "google-analytics.com",
    "googletagmanager.com",
    "doubleclick.net",
    "googlesyndication.com",
    "googleadservices.com",
    "facebook.net",
    "connect.facebook.net",
    "hotjar.com",
    "clarity.ms",
    "sentry.io",
    "cloudflareinsights.com",
    "criteo.com",
    "adnxs.com",
    "scorecardresearch.com",
    "mixpanel.com",
    "segment.io",
    "amplitude.com",
    "yandex.ru",
    "matomo.cloud",
    "hs-analytics.net",
]

LETTER_GRADE_THRESHOLDS = [
    (90, "A"),
    (80, "B"),
    (70, "C"),
    (60, "D"),
    (0, "F"),
]
