from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    elasticsearch_url: str = "http://localhost:9200"
    elasticsearch_user: str = "elastic"
    elasticsearch_password: str = "changeme"
    data_path: str = "../data"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
