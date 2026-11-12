"""Tests hors-ligne de l'agent rédacteur (LLM mocké, aucun appel réseau)."""

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from pydantic import Field

from market_analyst import config, llm
from market_analyst.agents import writer_agent as writer_module
from market_analyst.agents.writer_agent import SYSTEM_PROMPT, build_writer, writer_agent
from market_analyst.state import MarketMetrics, NewsItem

NOTE = "# NVDA : semaine en hausse\n## Résumé\nLe cours progresse."


class SpyChatModel(GenericFakeChatModel):
    """Faux modèle qui renvoie des réponses prédéfinies et garde les messages reçus."""

    seen: list[list[BaseMessage]] = Field(default_factory=list)

    def _generate(self, messages, *args: Any, **kwargs: Any):
        self.seen.append(list(messages))
        return super()._generate(messages, *args, **kwargs)


def spy_model(*replies: str) -> SpyChatModel:
    return SpyChatModel(messages=iter([AIMessage(r) for r in replies]))


# --- Construction de l'agent -------------------------------------------------


def test_build_writer_uses_shared_llm_factory(monkeypatch):
    calls: list[dict] = []

    def fake_get_llm(**kwargs):
        calls.append(kwargs)
        return spy_model(NOTE)

    monkeypatch.setattr(writer_module, "get_llm", fake_get_llm)

    build_writer()

    assert calls == [{}]  # délai et tentatives viennent de la config commune


def test_get_llm_falls_back_to_default_model_without_env(monkeypatch, tmp_path):
    """Sans LLM_MODEL ni .env, le modèle par défaut de config.py est utilisé (pas None)."""
    received: dict = {}

    def fake_init_chat_model(model, **kwargs):
        received.update(model=model, **kwargs)
        return spy_model(NOTE)

    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("GOOGLE_MODEL", raising=False)
    monkeypatch.chdir(tmp_path)  # aucun .env lisible par pydantic-settings
    monkeypatch.setattr(config, "load_dotenv", lambda: None)  # ni par python-dotenv
    monkeypatch.setattr(llm, "init_chat_model", fake_init_chat_model)
    config.get_settings.cache_clear()
    try:
        llm.get_llm()
    finally:
        config.get_settings.cache_clear()

    assert received == {
        "model": config.Settings.model_fields["llm_model"].default,
        "temperature": 0.0,
        "timeout": config.Settings.model_fields["llm_timeout_s"].default,
        "max_retries": config.Settings.model_fields["llm_max_retries"].default,
    }


def test_writer_sends_system_prompt_and_returns_model_text(monkeypatch):
    model = spy_model(NOTE)
    monkeypatch.setattr(writer_module, "get_llm", lambda **_: model)

    result = build_writer().invoke(
        {"messages": [{"role": "user", "content": "FAITS : ...\nRédige la note."}]}
    )

    assert result["messages"][-1].text == NOTE
    (sent,) = model.seen  # un seul appel au LLM : pas d'outil, pas de boucle
    assert isinstance(sent[0], SystemMessage)
    assert sent[0].content == SYSTEM_PROMPT
    assert "Rédige la note." in sent[-1].content


# --- Prompt système ----------------------------------------------------------


def test_prompt_defines_note_format_and_guardrails():
    for section in (
        "## Résumé",
        "## Points clés",
        "## Risques",
        "## Limites de l'analyse",
    ):
        assert section in SYSTEM_PROMPT
    assert "350 mots maximum" in SYSTEM_PROMPT
    assert "Aucun conseil d'achat ou de vente" in SYSTEM_PROMPT
    assert "QUE les informations fournies" in SYSTEM_PROMPT


# --- Nœud du graphe ----------------------------------------------------------

NEWS = [
    NewsItem(
        title="Nvidia beats estimates",
        source="Reuters",
        url="https://reuters.com/nvda",
        published_at="2026-11-04T18:29:00Z",
        summary="Résultats trimestriels au-dessus des attentes.",
    )
]
METRICS = MarketMetrics(
    last_close=191.75,
    weekly_return_pct=5.13,
    sma_short=185.2,
    sma_long=172.9,
    volatility_annualized=41.0,
)
STATE = {
    "request": "Fais-moi un point sur Nvidia cette semaine",
    "ticker": "NVDA",
    "company": "Nvidia",
    "lookback_days": 7,
    "news": NEWS,
    "metrics": METRICS,
}
GOOD_NOTE = (
    "# NVDA : clôture à 191.75 sur 7 jours\n## Résumé\nLe cours varie de 5,13 %.\n"
    "## Points clés\n- Résultats au-dessus des attentes (Reuters, 4 novembre 2026)."
)


def test_writer_agent_publishes_llm_note(monkeypatch):
    model = spy_model(GOOD_NOTE)
    monkeypatch.setattr(writer_module, "get_llm", lambda **_: model)

    out = writer_agent(STATE)

    assert out == {"report": GOOD_NOTE}
    # le LLM a reçu les faits et les chiffres de l'état, mis en forme
    sent = model.seen[0][-1].content
    assert "Nvidia beats estimates" in sent
    assert "Résultats trimestriels au-dessus des attentes." in sent
    assert '"Dernière clôture ajustée": "191.75"' in sent
    assert '"Moyenne mobile 20 séances": "172.90"' in sent


def test_writer_retries_once_when_numbers_are_invented(monkeypatch):
    invented = "# NVDA\n## Résumé\nObjectif de cours : 250 $."
    model = spy_model(invented, GOOD_NOTE)
    monkeypatch.setattr(writer_module, "get_llm", lambda **_: model)

    out = writer_agent(STATE)

    assert out == {"report": GOOD_NOTE}
    assert len(model.seen) == 2
    feedback = model.seen[1][-1].content
    assert "250" in feedback


def test_writer_flags_numbers_still_unverified(monkeypatch):
    invented = "# NVDA\n## Résumé\nObjectif de cours : 250 $."
    monkeypatch.setattr(
        writer_module, "get_llm", lambda **_: spy_model(invented, invented)
    )

    report = writer_agent(STATE)["report"]

    assert report.startswith(invented)
    assert "Contrôle automatique" in report
    assert "250" in report.split("Contrôle automatique")[1]


def test_writer_lists_missing_metrics_for_llm(monkeypatch):
    model = spy_model("# NVDA\n## Résumé\nPeu de données.")
    monkeypatch.setattr(writer_module, "get_llm", lambda **_: model)

    writer_agent(
        {"ticker": "NVDA", "news": NEWS, "metrics": {"sma_short": float("nan")}}
    )

    sent = model.seen[0][-1].content
    assert '"indicateurs": {}' in sent
    assert "Moyenne mobile 5 séances" in sent.split("indicateurs_indisponibles")[1]
    assert "nan" not in sent.lower().split("indicateurs_indisponibles")[0]


def test_writer_missing_data_needs_no_llm(monkeypatch):
    def forbidden(**kwargs):
        raise AssertionError("Rien à rédiger")

    monkeypatch.setattr(writer_module, "get_llm", forbidden)
    report = writer_agent({"ticker": "NVDA", "news": [], "metrics": {}})["report"]
    assert "Aucune actualité" in report
    assert "Indicateurs indisponibles" in report
    assert "Moyenne mobile 20 séances" in report


def test_writer_error_keeps_cause(monkeypatch):
    error = TimeoutError("fournisseur indisponible")

    def fail(**kwargs):
        raise error

    monkeypatch.setattr(writer_module, "get_llm", fail)
    with pytest.raises(RuntimeError, match="rédacteur") as caught:
        writer_agent({"ticker": "NVDA", "news": NEWS})
    assert caught.value.__cause__ is error


def test_writer_empty_answers_raise(monkeypatch):
    monkeypatch.setattr(writer_module, "get_llm", lambda **_: spy_model("", "  "))
    with pytest.raises(RuntimeError, match="aucune note"):
        writer_agent(STATE)


def test_writer_strips_markdown_fence_and_keeps_state(monkeypatch):
    from copy import deepcopy

    monkeypatch.setattr(
        writer_module,
        "get_llm",
        lambda **_: spy_model(f"```markdown\n{GOOD_NOTE}\n```"),
    )
    before = deepcopy(STATE)
    assert writer_agent(STATE)["report"] == GOOD_NOTE
    assert STATE == before


def test_numbers_are_normalized():
    assert writer_module._numbers("04 novembre, 191,750 et 5.13 % ; 2026-11-04") == {
        "4",
        "191.75",
        "5.13",
        "2026",
        "11",
    }
