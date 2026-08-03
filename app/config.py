from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "sqlite:///./data/arobserver.db"
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
