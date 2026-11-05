"""Agent 1 — veille d'actualités sur une entreprise."""

from functools import cache
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from market_analyst.config import get_settings
from market_analyst.llm import get_llm
from market_analyst.state import AnalystState, NewsItem
from market_analyst.tools.news import search_news

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "news.md"


class NewsArticle(BaseModel):
    """Miroir Pydantic de `NewsItem` (plus fiable que TypedDict en sortie structurée)."""

    title: str = Field(description="Titre d'origine de l'article")
    source: str = Field(description="Média, recopié depuis l'outil")
    url: str = Field(description="URL, recopiée exactement depuis l'outil")
    published_at: str = Field(
        description="Date ISO, recopiée exactement depuis l'outil"
    )
    summary: str = Field(
        description="Synthèse en français qui conserve tous les faits et chiffres clés"
    )


class NewsDigest(BaseModel):
    articles: list[NewsArticle] = Field(
        description="Articles retenus, du plus récent au plus ancien"
    )


@cache
def build_news_agent() -> CompiledStateGraph:
    """Agent ReAct : appelle `search_news`, puis renvoie un `NewsDigest` structuré."""
    return create_agent(
        get_llm(),
        tools=[search_news],
        system_prompt=PROMPT_PATH.read_text(encoding="utf-8"),
        response_format=NewsDigest,
        name="news_agent",
    )


def news_agent(state: AnalystState) -> AnalystState:
    """Collecte et résume les actualités récentes; remplit `news`.

    Prompt : prompts/news.md

    Ne renvoie que la clé `news` : le nœud tourne en parallèle de `market_data_agent`,
    et deux écritures concurrentes d'une même clé sans reducer feraient échouer le graphe.
    """
    company = state.get("company") or state.get("ticker") or state["request"]
    ticker = state.get("ticker", "")
    lookback_days = state.get("lookback_days") or get_settings().default_lookback_days

    task = (
        f"Actif : {company}\n"
        f"Ticker : {ticker or 'inconnu'}\n"
        f"Période : {lookback_days} derniers jours"
    )
    result = build_news_agent().invoke({"messages": [HumanMessage(task)]})
    digest: NewsDigest = result["structured_response"]

    # Garde-fou anti-hallucination : on ne garde que les URLs réellement renvoyées par l'outil.
    tool_output = "\n".join(
        str(m.content) for m in result["messages"] if isinstance(m, ToolMessage)
    )
    return {
        "news": [
            NewsItem(**article.model_dump())
            for article in digest.articles
            if article.url and article.url in tool_output
        ]
    }
