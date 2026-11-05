"""Configuration chargée depuis l'environnement (.env)."""

from functools import lru_cache

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_model: str = "google_genai:gemini-2.5-flash"  # "<provider>:<model>"
    default_lookback_days: int = 7


@lru_cache
def get_settings() -> Settings:
    # Exporte aussi le .env dans os.environ : les SDK des fournisseurs LLM
    # y lisent leur clé (GOOGLE_API_KEY, OPENAI_API_KEY…).
    load_dotenv()
    return Settings()
