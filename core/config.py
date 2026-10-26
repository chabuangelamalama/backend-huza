from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/huza"
    secret_key: str = "dev-only-secret-key-change-me-before-deploying"
    jwt_algorithm: str = "HS256"


@lru_cache
def get_settings() -> Settings:
    return Settings()
