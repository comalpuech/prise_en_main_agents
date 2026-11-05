"""Agent 2 — analyse des cours (moyennes, volatilité)."""

import logging
from functools import cache
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.graph.state import CompiledStateGraph

from market_analyst.config import get_settings
from market_analyst.llm import get_llm
from market_analyst.state import AnalystState
from market_analyst.tools.market import get_market_metrics

logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "market_data.md"


@cache
def build_market_data_agent() -> CompiledStateGraph:
    """Agent LangChain utilisant le même fournisseur/modèle que l'Agent 1."""
    return create_agent(
        get_llm(),
        tools=[get_market_metrics],
        system_prompt=PROMPT_PATH.read_text(encoding="utf-8"),
        name="market_data_agent",
    )


def market_data_agent(state: AnalystState) -> AnalystState:
    """Analyse les cours et produit les indicateurs; remplit `metrics`.

    Prompt : prompts/market_data.md
    """
    ticker = state.get("ticker", "").strip().upper()
    days = state.get("lookback_days", get_settings().default_lookback_days)
    if not ticker or days <= 0:
        raise ValueError("Un ticker et une période strictement positive sont requis")
    task = (
        f"Actif : {state.get('company') or ticker}\n"
        f"Ticker : {ticker}\nPériode : {days} derniers jours calendaires\n"
        "Appelle get_market_metrics avec exactement ce ticker et cette période."
    )
    result = build_market_data_agent().invoke(
        {"messages": [HumanMessage(task)]}, config={"recursion_limit": 10}
    )
    # L'artefact est produit par Python, jamais par le texte final du LLM.
    for message in reversed(result["messages"]):
        if not isinstance(message, ToolMessage) or message.name != "get_market_metrics":
            continue
        artifact = message.artifact
        if (
            message.status == "success"
            and isinstance(artifact, dict)
            and artifact.get("ticker") == ticker
            and artifact.get("lookback_days") == days
        ):
            return {"metrics": artifact["metrics"]}
    logger.warning("L'agent n'a pas appelé l'outil avec les paramètres demandés")
    return {"metrics": {}}


if __name__ == "__main__":
    import json
    import sys

    print(
        json.dumps(
            market_data_agent(
                {
                    "ticker": sys.argv[1] if len(sys.argv) > 1 else "NVDA",
                    "lookback_days": int(sys.argv[2]) if len(sys.argv) > 2 else 7,
                }
            ),
            indent=2,
            ensure_ascii=False,
        )
    )
