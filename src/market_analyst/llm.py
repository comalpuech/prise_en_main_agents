"""Fabrique du modèle de chat partagé par les agents (agnostique du fournisseur)."""

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from market_analyst.config import get_settings


def get_llm(temperature: float = 0.0) -> BaseChatModel:
    """Retourne le ChatModel configuré via `langchain.chat_models.init_chat_model`.

    Fournisseur par défaut : Google AI Studio (Gemini, offre gratuite), clé dans
    GOOGLE_API_KEY. Changer LLM_MODEL suffit pour basculer de fournisseur.
    """
    return init_chat_model(get_settings().llm_model, temperature=temperature)
