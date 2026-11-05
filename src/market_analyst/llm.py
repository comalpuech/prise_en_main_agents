"""Fabrique du modèle de chat partagé par les agents (agnostique du fournisseur)."""

from langchain_core.language_models import BaseChatModel


def get_llm(temperature: float = 0.0) -> BaseChatModel:
    """Retourne le ChatModel configuré via `langchain.chat_models.init_chat_model`.

    Fournisseur par défaut : Google AI Studio (Gemini, offre gratuite), clé dans
    GOOGLE_API_KEY. Changer LLM_MODEL suffit pour basculer de fournisseur.
    """
    raise NotImplementedError
