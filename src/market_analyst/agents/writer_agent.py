"""Agent 3 — rédacteur de la note d'analyse."""

"""Agent 3 — rédacteur de la note d'analyse."""

import os
from dotenv import load_dotenv
from langchain.agents import create_agent

from market_analyst.state import AnalystState

load_dotenv()

def build_writer():
    """Construit l'agent rédacteur, utilisable seul."""
    # TODO 1 : renvoie create_agent(...) avec :
    #   - model : la variable LLM_MODEL
    #   - tools : une liste vide pour l'instant
    #   - system_prompt : une phrase qui décrit son rôle de rédacteur
    ...


def writer_agent(state: AnalystState) -> AnalystState:
    """Synthétise `news` + `metrics` en note Markdown ; remplit `report`."""
    raise NotImplementedError  # on s'en occupe à la toute fin


if __name__ == "__main__":
    agent = build_writer()

    # TODO 2 : appelle agent.invoke(...)
    #   Attention : un agent ne prend PAS une simple chaîne.
    #   Il prend un dictionnaire avec une clé "messages" qui contient une liste de messages.
    resultat = ...

    # TODO 3 : affiche resultat entièrement, puis seulement le dernier message