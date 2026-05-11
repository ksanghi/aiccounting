"""Settings — read from environment / .env file."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    database_url: str = "sqlite:///./licenses.db"
    admin_token: str = "change-me"
    max_machines_per_key: int = 3
    server_version: str = "1.0.0"


settings = Settings()
