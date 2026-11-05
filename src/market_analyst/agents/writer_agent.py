"""Agent 3 — rédacteur de la note d'analyse."""

"""Agent 3 — rédacteur de la note d'analyse."""

import os
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model

from market_analyst.state import AnalystState

load_dotenv()

def build_writer():
    model = init_chat_model(
        os.getenv("LLM_MODEL"),
        timeout=30,
        max_retries=0,   # pas de nouvelle tentative : on veut voir l'erreur
    )
    return create_agent(model=model, tools=[], system_prompt="...")


def writer_agent(state: AnalystState) -> AnalystState:
    """Synthétise `news` + `metrics` en note Markdown ; remplit `report`."""
    raise NotImplementedError  # on s'en occupe plus tard


if __name__ == "__main__":
    agent = build_writer()

    question = (
        "Voici des infos sur NVDA : résultats au-dessus des attentes, "
        "cours passé de 182.40 $ à 191.75 $ cette semaine, volatilité de 41 %. "
        "Rédige une courte note d'analyse."
    )

    resultat = agent.invoke(
        {"messages": [{"role": "user", "content": question}]}
    )

    # 1) Tout le contenu, pour comprendre la structure
    print(resultat)

    # 2) Seulement la réponse finale : le dernier message de la liste
    print("\n===== NOTE =====\n")
    print(resultat["messages"][-1].text)