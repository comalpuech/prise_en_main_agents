"""Agent 3 — rédacteur de la note d'analyse."""

from market_analyst.state import AnalystState


def writer_agent(state: AnalystState) -> AnalystState:
    """Synthétise `news` + `metrics` en note Markdown; remplit `report`.

    Prompt : prompts/writer.md
    """
    raise NotImplementedError
