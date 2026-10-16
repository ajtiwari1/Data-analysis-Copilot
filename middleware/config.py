from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    postgres_host: str = "localhost"
    postgres_db: str = "marketing_intelligence"
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_port: int = Field(default=5432, gt=0, le=65535)
    database_url: str | None = None
    session_ttl_seconds: int = Field(default=60 * 60 * 24 * 30, gt=0)
    session_cookie_secure: bool = True
    frontend_origin: str = "http://localhost:5173"

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)


settings = Settings()
