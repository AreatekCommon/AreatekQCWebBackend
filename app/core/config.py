from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    backend_host: str = Field(default="127.0.0.1", alias="BACKEND_HOST")
    backend_port: int = Field(default=8000, alias="BACKEND_PORT")

    jwt_secret: str = Field(default="change_me", alias="JWT_SECRET")
    initial_admin_login: str = Field(default="admin", alias="INITIAL_ADMIN_LOGIN")
    initial_admin_password: str = Field(default="change_me", alias="INITIAL_ADMIN_PASSWORD")

    debug: bool = Field(default=True, alias="DEBUG")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()