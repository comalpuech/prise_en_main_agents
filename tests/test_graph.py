"""Graphe hors ligne : interprétation, fan-out/fan-in et contrats d'état."""

from copy import deepcopy
from threading import Barrier

import pytest

from market_analyst import graph
from market_analyst.agents import market_data_agent as market_module
from market_analyst.agents import news_agent as news_module
from market_analyst.agents import writer_agent as writer_module


class FakeParser:
    """Remplace le LLM à sortie structurée de `parse_request`."""

    def __init__(self, **fields):
        self.result = graph.ParsedRequest(**{"company": "", **fields})
        self.calls: list = []

    def invoke(self, messages):
        self.calls.append(messages)
        return self.result


@pytest.fixture
def fake_parser(monkeypatch):
    def install(**fields):
        parser = FakeParser(**fields)
        monkeypatch.setattr(graph, "build_request_parser", lambda: parser)
        return parser

    install(ticker="NVDA", company="Nvidia", lookback_days=7)
    return install


@pytest.mark.parametrize(
    "text,fields,expected",
    [
        (
            "Fais-moi un point sur Nvidia cette semaine",
            {"ticker": "NVDA", "company": "Nvidia", "lookback_days": 7},
            {"ticker": "NVDA", "company": "Nvidia", "lookback_days": 7},
        ),
        (
            "Point sur Apple ce mois-ci",
            {"ticker": "aapl", "company": "Apple", "lookback_days": 30},
            {"ticker": "AAPL", "company": "Apple", "lookback_days": 30},
        ),
        (
            "Comment va LVMH ?",
            {"ticker": "MC.PA", "company": "LVMH"},
            {"ticker": "MC.PA", "company": "LVMH", "lookback_days": 7},
        ),
        (
            "Et le Bitcoin sur 2 semaines ?",
            {"ticker": "BTC-USD", "company": "Bitcoin", "lookback_days": 14},
            {"ticker": "BTC-USD", "company": "Bitcoin", "lookback_days": 14},
        ),
        (
            "Le S&P 500 cette semaine",
            {"ticker": "^GSPC", "company": "S&P 500", "lookback_days": 7},
            {"ticker": "^GSPC", "company": "S&P 500", "lookback_days": 7},
        ),
    ],
)
def test_parse_request_uses_llm_interpretation(fake_parser, text, fields, expected):
    parser = fake_parser(**fields)
    state = {"request": text}
    before = deepcopy(state)

    assert graph.parse_request(state) == expected
    assert state == before
    (messages,) = parser.calls
    assert messages[0][0] == "system" and "Yahoo Finance" in messages[0][1]
    assert messages[1] == ("human", text)


def test_explicit_cli_values_override_llm(fake_parser):
    fake_parser(ticker="NVDA", company="Nvidia", lookback_days=7)
    out = graph.parse_request(
        {"request": "Nvidia", "ticker": "nvda", "lookback_days": 14}
    )
    assert out == {"ticker": "NVDA", "company": "Nvidia", "lookback_days": 14}


def test_explicit_ticker_without_request_needs_no_llm(monkeypatch):
    monkeypatch.setattr(
        graph, "build_request_parser", lambda: pytest.fail("LLM inutile")
    )
    assert graph.parse_request({"ticker": "aapl", "lookback_days": 10}) == {
        "ticker": "AAPL",
        "company": "AAPL",
        "lookback_days": 10,
    }


def test_llm_refusal_becomes_request_error(fake_parser):
    fake_parser(ticker="", error="Deux actifs demandés : choisissez-en un seul.")
    with pytest.raises(graph.RequestError, match="Deux actifs"):
        graph.parse_request({"request": "Nvidia et AMD"})


@pytest.mark.parametrize(
    "fields",
    [
        {"ticker": ""},
        {"ticker": "NVDA/INVALID"},
        {"ticker": "NVDA", "lookback_days": 0},
        {"ticker": "NVDA", "lookback_days": 4000},
    ],
)
def test_parse_validates_llm_output(fake_parser, fields):
    fake_parser(**fields)
    with pytest.raises(graph.RequestError):
        graph.parse_request({"request": "demande"})


@pytest.mark.parametrize(
    "state",
    [
        {},
        {"ticker": "NVDA", "lookback_days": True},
        {"ticker": "NVDA", "lookback_days": "7"},
        {"ticker": "NVDA/INVALID"},
    ],
)
def test_parse_rejects_invalid_explicit_values(state):
    with pytest.raises(graph.RequestError):
        graph.parse_request(state)


def test_parser_failure_keeps_cause(monkeypatch):
    error = TimeoutError("quota")

    class Broken:
        def invoke(self, messages):
            raise error

    monkeypatch.setattr(graph, "build_request_parser", lambda: Broken())
    with pytest.raises(RuntimeError, match="interprétation") as caught:
        graph.parse_request({"request": "Nvidia"})
    assert caught.value.__cause__ is error


def test_graph_end_to_end_parallel_join(monkeypatch, fake_parser):
    barrier = Barrier(2)
    metrics = {"last_close": 100.0}
    news = [{"title": "fait"}]
    writes = []

    def news_node(state):
        barrier.wait(timeout=5)
        writes.append("news")
        return {"news": news}

    def market_node(state):
        barrier.wait(timeout=5)
        writes.append("metrics")
        return {"metrics": metrics}

    def writer_node(state):
        assert sorted(writes) == ["metrics", "news"]
        assert state["news"] == news and state["metrics"] == metrics
        writes.append("report")
        return {"report": "note"}

    monkeypatch.setattr(graph, "news_agent", news_node)
    monkeypatch.setattr(graph, "market_data_agent", market_node)
    monkeypatch.setattr(graph, "writer_agent", writer_node)
    initial = {"request": "Point sur Nvidia cette semaine"}
    before = deepcopy(initial)
    out = graph.build_graph().invoke(initial, config={"max_concurrency": 2})
    assert initial == before
    assert out["report"] == "note"
    assert out["ticker"] == "NVDA"
    assert writes.count("report") == 1
    assert writes[-1] == "report"


def test_graph_propagates_agent_failure(monkeypatch):
    def fail(state):
        raise RuntimeError("modèle indisponible")

    def writer(state):
        raise AssertionError("Pas de publication après un échec")

    monkeypatch.setattr(graph, "news_agent", fail)
    monkeypatch.setattr(graph, "market_data_agent", lambda state: {"metrics": {}})
    monkeypatch.setattr(graph, "writer_agent", writer)
    with pytest.raises(RuntimeError, match="modèle indisponible"):
        graph.build_graph().invoke({"ticker": "NVDA"})


def test_real_nodes_with_offline_agents(monkeypatch, fake_parser):
    """Les trois vrais nœuds, seuls leurs agents LLM sont remplacés."""
    from langchain_core.messages import AIMessage, ToolMessage

    from market_analyst.agents.news_agent import NewsDigest

    class News:
        def invoke(self, *a, **kw):
            return {"structured_response": NewsDigest(articles=[]), "messages": []}

    class Market:
        def invoke(self, *a, **kw):
            return {
                "messages": [
                    ToolMessage(
                        content="",
                        name="get_market_metrics",
                        tool_call_id="1",
                        artifact={
                            "ticker": "NVDA",
                            "lookback_days": 7,
                            "metrics": {"last_close": 123.0},
                        },
                    ),
                    AIMessage(content="Cours inventé : 999999"),
                ]
            }

    monkeypatch.setattr(news_module, "build_news_agent", lambda: News())
    monkeypatch.setattr(market_module, "build_market_data_agent", lambda: Market())
    from tests.test_writer_agent import spy_model

    writer_llm = spy_model("# NVDA\n## Résumé\nClôture à 123.00, aucune actualité.")
    monkeypatch.setattr(writer_module, "get_llm", lambda **kw: writer_llm)
    out = graph.build_graph().invoke({"request": "Point sur Nvidia cette semaine"})
    assert out["metrics"] == {"last_close": 123.0}
    assert out["news"] == []
    assert "123.00" in out["report"] and "999999" not in out["report"]
    # le rédacteur ne voit que la métrique calculée en Python, pas le texte du LLM marché
    sent = writer_llm.seen[0][-1].content
    assert '"Dernière clôture ajustée": "123.00"' in sent and "999999" not in sent


def test_pipeline_with_langchain_tool_calls_offline(monkeypatch, fake_parser):
    import pandas as pd
    from langchain_core.language_models.fake_chat_models import (
        FakeMessagesListChatModel,
    )
    from langchain_core.messages import AIMessage

    from market_analyst.tools import market, news
    from tests.test_writer_agent import spy_model

    article = {
        "title": "Nvidia publie ses résultats",
        "source": "Source test",
        "url": "https://example.test/nvda",
        "published_at": "2026-11-11T12:00:00Z",
        "summary": "Résultats publiés selon la source fournie.",
    }

    class ToolModel(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    def call(name, args, identifier):
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": name,
                    "args": args,
                    "id": identifier,
                    "type": "tool_call",
                }
            ],
        )

    news_model = ToolModel(
        responses=[
            call(
                "search_news",
                {"query": "Nvidia", "ticker": "NVDA", "lookback_days": 7},
                "n",
            ),
            call("NewsDigest", {"articles": [article]}, "digest"),
        ]
    )
    market_model = ToolModel(
        responses=[
            call("get_market_metrics", {"ticker": "NVDA", "lookback_days": 7}, "m"),
        ]
    )
    monkeypatch.setenv("GOOGLE_API_KEY", "offline-test-placeholder")
    monkeypatch.setattr(news_module, "get_llm", lambda **kw: news_model)
    monkeypatch.setattr(market_module, "get_llm", lambda: market_model)
    monkeypatch.setattr(
        writer_module,
        "get_llm",
        lambda **kw: spy_model(
            "# NVDA\n## Points clés\n- Clôture à 129.00 ; Nvidia publie ses résultats."
        ),
    )
    monkeypatch.setattr(news, "collect_news", lambda *a: [article])
    monkeypatch.setattr(news, "add_article_content", lambda articles: articles)
    # Fenêtre fixe pour tester les vrais calculs sans dépendre du jour d'exécution.
    real_collect = market.collect_market_metrics
    from datetime import date

    monkeypatch.setattr(
        market,
        "collect_market_metrics",
        lambda ticker, days: real_collect(ticker, days, as_of=date(2026, 11, 12)),
    )
    frame = pd.DataFrame(
        {"Close": range(100, 130)}, index=pd.bdate_range(end="2026-11-11", periods=30)
    )

    class Ticker:
        def __init__(self, symbol):
            assert symbol == "NVDA"

        def history(self, **kw):
            return frame

    monkeypatch.setattr(market.yf, "Ticker", Ticker)
    news_module.build_news_agent.cache_clear()
    market_module.build_market_data_agent.cache_clear()
    try:
        out = graph.build_graph().invoke(
            {"request": "Fais-moi un point sur Nvidia cette semaine"}
        )
    finally:
        news_module.build_news_agent.cache_clear()
        market_module.build_market_data_agent.cache_clear()
    assert len(out["news"]) == 1
    assert out["metrics"]["last_close"] == 129
    assert out["metrics"]["sma_short"] == 127
    assert out["metrics"]["sma_long"] == 119.5
    assert "129.00" in out["report"]
    assert "Contrôle automatique" not in out["report"]
