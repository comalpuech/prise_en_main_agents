"""Agent 1 — veille d'actualités sur une entreprise."""

from market_analyst.state import AnalystState


def news_agent(state: AnalystState) -> AnalystState:
    """Collecte et résume les actualités récentes; remplit `news`.

    Prompt : prompts/news.md
    """
    raise NotImplementedError
