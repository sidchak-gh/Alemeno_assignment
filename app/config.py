from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://txnuser:txnpass@db:5432/txndb"
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/0"
    gemini_api_key: str = ""

    # these brands only operate in India — a USD charge here is a red flag
    domestic_merchants: list[str] = [
        "Swiggy",
        "Ola",
        "IRCTC",
        "Jio Recharge",
        "HDFC ATM",
        "Zomato",
        "BookMyShow",
    ]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
