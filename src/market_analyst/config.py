"""Configuration chargée depuis l'environnement (.env)."""

from functools import lru_cache

from dotenv import load_dotenv
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_model: str = "google_genai:gemini-2.5-flash"  # "<provider>:<model>"
    google_model: str = ""
    default_lookback_days: int = 7

    @model_validator(mode="after")
    def resolve_google_model(self) -> "Settings":
        """LLM_MODEL explicite reste prioritaire sur le raccourci GOOGLE_MODEL."""
        model = self.google_model.strip()
        if model and "llm_model" not in self.model_fields_set:
            if ":" in model and not model.startswith("google_genai:"):
                raise ValueError("GOOGLE_MODEL doit désigner un modèle Google Gemini")
            name = model.removeprefix("google_genai:").strip()
            if not name:
                raise ValueError("GOOGLE_MODEL doit contenir un nom de modèle")
            self.llm_model = f"google_genai:{name}"
        return self


@lru_cache
def get_settings() -> Settings:
    # Exporte aussi le .env dans os.environ : les SDK des fournisseurs LLM
    # y lisent leur clé (GOOGLE_API_KEY, OPENAI_API_KEY…).
    load_dotenv()
    return Settings()
