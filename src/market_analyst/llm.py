"""Fabrique du modèle de chat partagé par les agents (agnostique du fournisseur)."""

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from market_analyst.config import get_settings


def get_llm(temperature: float = 0.0, **kwargs) -> BaseChatModel:
    """Retourne le ChatModel configuré via `langchain.chat_models.init_chat_model`.

    Fournisseur par défaut : Google AI Studio (Gemini, offre gratuite), clé dans
    GOOGLE_API_KEY. Changer LLM_MODEL suffit pour basculer de fournisseur.
    Délai et nombre de tentatives par défaut : LLM_TIMEOUT_S et LLM_MAX_RETRIES
    (.env). `kwargs` est transmis tel quel à `init_chat_model` et les remplace.
    """
    settings = get_settings()
    kwargs.setdefault("timeout", settings.llm_timeout_s)
    kwargs.setdefault("max_retries", settings.llm_max_retries)
    return init_chat_model(settings.llm_model, temperature=temperature, **kwargs)
