from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "System Monitor"
    app_env: str = "development"
    api_docs_enabled: bool = True
    database_url: str = ""
    supabase_db_url: str = ""
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_auth_timeout_seconds: int = 8
    ingest_api_token: str = ""
    require_admin_auth: bool = True
    admin_username: str = ""
    admin_password: str = ""
    allowed_hosts: str = "localhost,127.0.0.1"
    heartbeat_timeout_seconds: int = 120
    alert_cpu_threshold: float = 90.0
    alert_memory_threshold: float = 90.0
    alert_disk_threshold: float = 90.0
    alert_cooldown_seconds: int = 300
    alert_webhook_url: str = ""
    alert_email_to: str = ""
    alert_email_from: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    smtp_timeout_seconds: int = 8
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    cors_allow_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()
