from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", env_prefix="COLLECTOR_", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    data_dir: Path = BACKEND_ROOT / "data"
    public_origin: str = "http://localhost:3722"
    cookie_secure: bool | None = None
    session_hours: int = Field(default=168, ge=1, le=720)
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: SecretStr | None = None
    max_body_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)

    @model_validator(mode="after")
    def validate_origin(self):
        self.public_origin = self.public_origin.rstrip("/")
        url = urlsplit(self.public_origin)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.path
            or url.query
            or url.fragment
            or url.username
            or url.password
        ):
            raise ValueError("COLLECTOR_PUBLIC_ORIGIN must be an origin, e.g. https://collector.example.com")
        uses_https = url.scheme == "https"
        if self.cookie_secure is None:
            self.cookie_secure = uses_https
        elif self.cookie_secure != uses_https:
            raise ValueError("COLLECTOR_COOKIE_SECURE must be true for HTTPS and false for HTTP")
        return self

    @property
    def database_path(self) -> Path:
        return self.data_dir.resolve() / "collector.db"
