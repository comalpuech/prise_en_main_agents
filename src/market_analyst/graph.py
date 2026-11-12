"""Assemblage du graphe multi-agents.

    START -> parse_request -> [news_agent, market_data_agent] -> writer_agent -> END

Les agents 1 et 2 sont indépendants et peuvent tourner en parallèle (fan-out),
l'agent 3 attend leurs deux sorties (fan-in).
"""

import re
from functools import cache
from pathlib import Path

from langchain_core.runnables import Runnable
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
<<<<<<< HEAD
from pydantic import BaseModel, Field
=======
from langgraph.store.base import BaseStore
>>>>>>> origin/main

from market_analyst.agents.market_data_agent import market_data_agent
from market_analyst.agents.news_agent import news_agent
from market_analyst.agents.writer_agent import writer_agent
from market_analyst.config import get_settings
<<<<<<< HEAD
from market_analyst.llm import get_llm
=======
from market_analyst.memory.store import build_store
>>>>>>> origin/main
from market_analyst.state import AnalystState

PROMPT_PATH = Path(__file__).parent / "prompts" / "parse_request.md"
# Symboles Yahoo : NVDA, BRK-B, MC.PA, BTC-USD, ^GSPC (indice), EURUSD=X, GC=F…
TICKER_RE = re.compile(r"\^?[A-Z0-9]+(?:[.\-=][A-Z0-9]+)*")
MAX_DAYS = 3650


class RequestError(ValueError):
    """Demande ambiguë ou invalide, affichable sans exposer d'erreur SDK."""


class ParsedRequest(BaseModel):
    """Interprétation de la demande par le LLM (sortie structurée)."""

    ticker: str = Field(description="Symbole Yahoo Finance, vide si `error`")
    company: str = Field(description="Nom usuel de l'entreprise ou de l'actif")
    lookback_days: int | None = Field(
        default=None, description="Période en jours calendaires, null si non précisée"
    )
    error: str | None = Field(
        default=None, description="Raison en français si la demande est inexploitable"
    )


@cache
def build_request_parser() -> Runnable:
    """LLM à sortie structurée qui transforme la demande en `ParsedRequest`."""
    return get_llm().with_structured_output(ParsedRequest)


def _interpret(request: str) -> ParsedRequest:
    system = PROMPT_PATH.read_text(encoding="utf-8")
    try:
        parsed = build_request_parser().invoke([("system", system), ("human", request)])
    except Exception as exc:
        raise RuntimeError(
            "Échec de l'interprétation de la demande : vérifiez le modèle, "
            "les quotas et le réseau"
        ) from exc
    if not isinstance(parsed, ParsedRequest):
        raise RequestError("Demande non interprétable : précisez l'actif et la période")
    if parsed.error:
        raise RequestError(parsed.error)
    return parsed


def parse_request(state: AnalystState) -> AnalystState:
    """Extrait ticker / entreprise / période de la demande, en langage naturel.

    Le LLM interprète la demande (n'importe quelle entreprise ou crypto, n'importe
    quelle formulation de la période). Python valide ensuite le résultat. Le ticker
    et la période passés explicitement (CLI `--ticker`, `--days`) sont prioritaires ;
    sans demande, aucun appel au LLM n'est fait.
    """
    request = (state.get("request") or "").strip()
    ticker = (state.get("ticker") or "").strip().upper()
    days = state.get("lookback_days")
    company = ""

    if request:
        parsed = _interpret(request)
        ticker = ticker or parsed.ticker.strip().upper()
        company = parsed.company.strip()
        if days is None:
            days = parsed.lookback_days
    if not ticker:
        raise RequestError(
            "Actif absent : précisez une entreprise, une crypto ou un ticker "
            "(ex. « point sur Apple », --ticker AAPL)"
        )
    if len(ticker) > 20 or not TICKER_RE.fullmatch(ticker):
        raise RequestError(f"Format de ticker invalide : {ticker[:20]}")

    if days is None:
        days = get_settings().default_lookback_days
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= MAX_DAYS:
        raise RequestError(
            f"La période doit être un entier entre 1 et {MAX_DAYS} jours"
        )
    return {"ticker": ticker, "company": company or ticker, "lookback_days": days}


def build_graph(store: BaseStore | None = None) -> CompiledStateGraph:
    """Construit et compile le StateGraph.

    Le Store (mémoire partagée entre les exécutions) est créé ici, à la racine :
    LangGraph l'injecte ensuite dans les nœuds, les agents et leurs outils.
    """
    graph = StateGraph(AnalystState)
    graph.add_node("parse_request", parse_request)
    graph.add_node("news_agent", news_agent)
    graph.add_node("market_data_agent", market_data_agent)
    graph.add_node("writer_agent", writer_agent)
    graph.add_edge(START, "parse_request")
    graph.add_edge("parse_request", "news_agent")
    graph.add_edge("parse_request", "market_data_agent")
    graph.add_edge(["news_agent", "market_data_agent"], "writer_agent")
    graph.add_edge("writer_agent", END)
    return graph.compile(store=store if store is not None else build_store())
