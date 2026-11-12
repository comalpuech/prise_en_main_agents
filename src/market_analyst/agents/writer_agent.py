"""Agent 3 — rédacteur de la note d'analyse."""

from pathlib import Path

from langchain.agents import create_agent

from market_analyst.llm import get_llm
from market_analyst.state import AnalystState

# agents/writer_agent.py → parent = agents/ → parent = market_analyst/
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "writer.md"
SYSTEM_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")


def build_writer():
    """Construit l'agent rédacteur, utilisable seul.

    Le modèle vient de `get_llm()` (LLM_MODEL du .env, sinon la valeur par défaut
    de config.py), comme pour les autres agents.
    """
    model = get_llm(timeout=30, max_retries=1)
    return create_agent(model=model, tools=[], system_prompt=SYSTEM_PROMPT)


def writer_agent(state: AnalystState) -> AnalystState:
    """Synthétise `news` + `metrics` en note Markdown ; remplit `report`."""
    raise NotImplementedError  # on s'en occupe plus tard


if __name__ == "__main__":
    print(f"Prompt chargé ({len(SYSTEM_PROMPT)} caractères) depuis {PROMPT_PATH}\n")

    agent = build_writer()

    question = (
        "FAITS :\n"
        "- Résultats trimestriels au-dessus des attentes.\n\n"
        "CHIFFRES :\n"
        "- Ticker : NVDA\n"
        "- Cours début de semaine : 182.40 $\n"
        "- Cours fin de semaine : 191.75 $\n"
        "- Volatilité 30 jours : 41 %\n\n"
        "Rédige la note d'analyse."
    )

    resultat = agent.invoke(
        {"messages": [{"role": "user", "content": question}]}
    )

    print(resultat["messages"][-1].text)