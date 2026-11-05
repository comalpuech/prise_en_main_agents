"""Configuration chargée depuis l'environnement (.env)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_model: str = "google_genai:gemini-2.5-flash"  # "<provider>:<model>"
    default_lookback_days: int = 7


def get_settings() -> Settings:
    # TODO: mettre en cache (functools.lru_cache)
    raise NotImplementedError
