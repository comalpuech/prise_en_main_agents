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

    assert calls == [{"timeout": 30, "max_retries": 1}]


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
        llm.get_llm(timeout=30, max_retries=1)
    finally:
        config.get_settings.cache_clear()

    assert received == {
        "model": config.Settings.model_fields["llm_model"].default,
        "temperature": 0.0,
        "timeout": 30,
        "max_retries": 1,
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


# --- Nœud du graphe (contrat attendu, à implémenter) -------------------------

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


def test_writer_agent_node_fills_only_report(monkeypatch):
    model = spy_model('{"news_indices": [0]}')
    monkeypatch.setattr(writer_module, "get_llm", lambda **_: model)

    out = writer_agent(
        {
            "request": "Fais-moi un point sur Nvidia cette semaine",
            "ticker": "NVDA",
            "company": "Nvidia",
            "lookback_days": 7,
            "news": NEWS,
            "metrics": METRICS,
        }
    )

    assert set(out) == {"report"}
    assert "Nvidia beats estimates" in out["report"]
    assert "191.7500" in out["report"]
    assert "41.0000" in out["report"]
    # le LLM a bien reçu les faits et les chiffres de l'état
    sent = model.seen[0][-1].content
    assert "NVDA" in sent
    assert "Nvidia beats estimates" in sent
    assert "191.75" in sent


@pytest.mark.parametrize(
    "reply",
    [
        NOTE,
        '{"news_indices": [-1]}',
        '{"news_indices": [99]}',
        '{"news_indices": [true]}',
        '{"news_indices": [0, 0]}',
    ],
)
def test_writer_never_publishes_free_llm_text(monkeypatch, reply):
    model = spy_model(reply)
    monkeypatch.setattr(writer_module, "get_llm", lambda **_: model)
    report = writer_agent({"ticker": "NVDA", "news": NEWS, "metrics": METRICS})[
        "report"
    ]
    assert "191.7500" in report
    assert NOTE not in report
    assert "Tri LLM invalide" in report


def test_writer_missing_data_needs_no_llm(monkeypatch):
    def forbidden(**kwargs):
        raise AssertionError("Aucune sélection à demander")

    monkeypatch.setattr(writer_module, "get_llm", forbidden)
    report = writer_agent({"ticker": "NVDA", "news": [], "metrics": {}})["report"]
    assert "Aucune actualité" in report
    assert "Indicateurs indisponibles" in report
    assert "SMA 20" in report


def test_writer_error_keeps_cause(monkeypatch):
    error = TimeoutError("fournisseur indisponible")

    def fail(**kwargs):
        raise error

    monkeypatch.setattr(writer_module, "get_llm", fail)
    with pytest.raises(RuntimeError, match="rédacteur") as caught:
        writer_agent({"ticker": "NVDA", "news": NEWS})
    assert caught.value.__cause__ is error


def test_writer_bounds_report_and_does_not_mutate_state(monkeypatch):
    from copy import deepcopy

    model = spy_model('{"news_indices": [0, 1, 2]}')
    monkeypatch.setattr(writer_module, "get_llm", lambda **_: model)
    state = {
        "ticker": "NVDA",
        "news": [dict(NEWS[0], summary="Fait fourni. " * 100)] * 4,
        "metrics": METRICS,
    }
    before = deepcopy(state)
    report = writer_agent(state)["report"]
    assert state == before
    assert len(report.split()) <= 350


def test_writer_omits_nonfinite_metrics(monkeypatch):
    monkeypatch.setattr(
        writer_module, "get_llm", lambda **_: spy_model('{"news_indices": [0]}')
    )
    report = writer_agent(
        {
            "ticker": "NVDA",
            "news": NEWS,
            "metrics": {"last_close": float("nan"), "sma_short": float("inf")},
        }
    )["report"]
    assert "Indicateurs indisponibles" in report
    assert ": nan" not in report and ": inf" not in report


def test_writer_accepts_json_fence(monkeypatch):
    monkeypatch.setattr(
        writer_module,
        "get_llm",
        lambda **_: spy_model('```json\n{"news_indices": [0]}\n```'),
    )
    report = writer_agent({"ticker": "NVDA", "news": NEWS})["report"]
    assert "Nvidia beats estimates" in report
    assert "Tri LLM invalide" not in report
