"""Assemblage du graphe multi-agents.

    START -> parse_request -> [news_agent, market_data_agent] -> writer_agent -> END

Les agents 1 et 2 sont indépendants et peuvent tourner en parallèle (fan-out),
l'agent 3 attend leurs deux sorties (fan-in).
"""

from langgraph.graph.state import CompiledStateGraph

from market_analyst.state import AnalystState


def parse_request(state: AnalystState) -> AnalystState:
    """Extrait ticker / entreprise / période depuis la requête utilisateur."""
    raise NotImplementedError


def build_graph() -> CompiledStateGraph:
    """Construit et compile le StateGraph."""
    raise NotImplementedError
