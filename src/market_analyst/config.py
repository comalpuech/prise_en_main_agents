"""Configuration chargée depuis l'environnement (.env)."""

from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_model: str = "google_genai:gemini-2.5-flash"  # "<provider>:<model>"
    google_model: str = ""
    default_lookback_days: int = 7
    # Appels LLM : un pipeline en fait 6 à 8, une erreur 503 passagère ne doit pas
    # tout arrêter. Les SDK réessaient avec un délai croissant.
    llm_timeout_s: float = 30
    llm_max_retries: int = 4
    # Store LangGraph (mémoire des agents) : fichier SQLite relatif au dossier
    # courant, ou ":memory:" (perdu à la sortie) ; jamais vide
    memory_store_path: str = Field(default="data/memory.db", min_length=1)
    # Durée de vie d'un souvenir depuis sa dernière écriture
    memory_ttl_days: int = Field(default=30, gt=0)

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
