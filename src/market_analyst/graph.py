"""Assemblage du graphe multi-agents.

    START -> parse_request -> [news_agent, market_data_agent] -> writer_agent -> END

Les agents 1 et 2 sont indépendants et peuvent tourner en parallèle (fan-out),
l'agent 3 attend leurs deux sorties (fan-in).
"""

import re

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from market_analyst.agents.market_data_agent import market_data_agent
from market_analyst.agents.news_agent import news_agent
from market_analyst.agents.writer_agent import writer_agent
from market_analyst.config import get_settings
from market_analyst.state import AnalystState


class RequestError(ValueError):
    """Demande ambiguë ou invalide, affichable sans exposer d'erreur SDK."""


def parse_request(state: AnalystState) -> AnalystState:
    """Résout Nvidia ou un ticker explicite, sans deviner d'autres entreprises."""
    request = state.get("request", "").strip()
    known_nvidia = bool(re.search(r"\bnvidia\b", request, re.IGNORECASE))
    symbols = set(
        re.findall(
            r"(?<![\w.-])\$?([A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)*)(?![\w-]|\.\w)", request
        )
    )
    symbols -= {
        "FAIS",
        "MOI",
        "UN",
        "POINT",
        "SUR",
        "CETTE",
        "SEMAINE",
        "LES",
        "DERNIERS",
        "JOURS",
        "ANALYSE",
        "TICKER",
        "ET",
    }
    # Les marqueurs explicites acceptent aussi les symboles en minuscules.
    symbols.update(
        s.upper()
        for s in re.findall(
            r"(?:\$|\bticker\s*[:=]?\s+)([a-zA-Z][a-zA-Z0-9]*(?:[.-][a-zA-Z0-9]+)*)",
            request,
            re.IGNORECASE,
        )
    )
    provided = state.get("ticker", "").strip().upper()
    if provided:
        symbols.add(provided)
    if known_nvidia:
        symbols.discard("NVIDIA")
        symbols.add("NVDA")
    if len(symbols) != 1:
        raise RequestError(
            "Actif absent ou ambigu : indiquez un seul ticker explicite "
            "(ex. --ticker NVDA, $NVDA ou ticker NVDA). "
            "Seul le nom Nvidia est reconnu sans ticker."
        )
    ticker = symbols.pop()
    if (
        not re.fullmatch(r"[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)*", ticker)
        or len(ticker) > 20
    ):
        raise RequestError("Format de ticker invalide")

    if re.search(r"\d+[.,]\d+\s+(?:derniers?\s+)?jours?\b", request, re.IGNORECASE):
        raise RequestError("La période doit être un nombre entier de jours")
    periods = {
        int(n)
        for n in re.findall(
            r"(?<!\w)(-?\d+)\s+(?:derniers?\s+)?jours?\b", request, re.IGNORECASE
        )
    }
    if re.search(r"\bsemaine\b", request, re.IGNORECASE):
        periods.add(7)
    if len(periods) > 1:
        raise RequestError("Période ambiguë : indiquez une seule durée en jours")
    days = state.get("lookback_days")
    if days is None:
        if not periods and re.search(
            r"\b(mois|ans?|années?|hier|aujourd'hui)\b", request, re.IGNORECASE
        ):
            raise RequestError(
                "Période non prise en charge : indiquez une durée en jours"
            )
        days = next(iter(periods), get_settings().default_lookback_days)
    elif periods and days not in periods:
        raise RequestError("La durée explicite contredit la période de la demande")
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 3650:
        raise RequestError("La période doit être un entier entre 1 et 3650 jours")
    return {
        "ticker": ticker,
        "company": "Nvidia" if ticker == "NVDA" else ticker,
        "lookback_days": days,
    }


def build_graph() -> CompiledStateGraph:
    """Construit et compile le StateGraph."""
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
    return graph.compile()
