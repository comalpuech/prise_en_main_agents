"""État partagé circulant dans le graphe LangGraph."""

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class NewsItem(TypedDict):
    title: str
    source: str
    url: str
    published_at: str
    summary: str


class MarketMetrics(TypedDict, total=False):
    last_close: float
    weekly_return_pct: float
    sma_short: float
    sma_long: float
    volatility_annualized: float


class AnalystState(TypedDict, total=False):
    request: str  # « Fais-moi un point sur Nvidia cette semaine »
    ticker: str  # ex. "NVDA" ou "BTC-USD"
    company: str
    lookback_days: int
    news: list[NewsItem]  # sortie agent 1
    metrics: MarketMetrics  # sortie agent 2
    report: str  # sortie agent 3 (Markdown)
    messages: Annotated[list[AnyMessage], add_messages]
