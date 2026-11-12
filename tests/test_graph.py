"""Graphe hors ligne : interprétation, fan-out/fan-in et contrats d'état."""

from copy import deepcopy
from threading import Barrier

import pytest

from market_analyst import graph
from market_analyst.agents import market_data_agent as market_module
from market_analyst.agents import news_agent as news_module
from market_analyst.agents import writer_agent as writer_module


@pytest.mark.parametrize(
    "text,ticker,days",
    [
        ("Fais-moi un point sur Nvidia cette semaine", "NVDA", 7),
        ("Fais-moi un point sur NVIDIA cette semaine", "NVDA", 7),
        ("NVDA", "NVDA", 7),
        ("Fais-moi un point sur AAPL sur 14 jours", "AAPL", 14),
        ("Analyse $msft sur 5 jours", "MSFT", 5),
        ("ticker BTC-USD sur 30 jours", "BTC-USD", 30),
        ("point sur BRK.B cette semaine", "BRK.B", 7),
        ("Fais-moi un point sur NVDA.", "NVDA", 7),
        ("Ticker nvda.", "NVDA", 7),
    ],
)
def test_parse_request(text, ticker, days):
    state = {"request": text}
    before = deepcopy(state)
    out = graph.parse_request(state)
    assert out["ticker"] == ticker
    assert out["lookback_days"] == days
    assert set(out) == {"ticker", "company", "lookback_days"}
    assert state == before


@pytest.mark.parametrize(
    "state",
    [
        {"request": "Fais-moi un point sur Apple cette semaine"},
        {"request": "NVDA et MSFT"},
        {"request": "Nvidia", "ticker": "MSFT"},
        {"request": "Nvidia sur 0 jours"},
        {"request": "Nvidia sur -7 jours"},
        {"request": "Nvidia sur 1.5 jours"},
        {"request": "Nvidia ce mois"},
        {"request": "Nvidia sur 3 jours cette semaine"},
        {"ticker": "NVDA", "lookback_days": True},
        {"ticker": "NVDA", "lookback_days": 4000},
        {"ticker": "NVDA", "lookback_days": "7"},
        {"ticker": "NVDA/INVALID"},
        {"request": "NVDA cette semaine", "lookback_days": 14},
    ],
)
def test_parse_rejects_ambiguity(state):
    with pytest.raises(graph.RequestError):
        graph.parse_request(state)


def test_explicit_ticker_without_name():
    assert graph.parse_request({"ticker": "aapl", "lookback_days": 10}) == {
        "ticker": "AAPL",
        "company": "AAPL",
        "lookback_days": 10,
    }


def test_graph_end_to_end_parallel_join(monkeypatch):
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


def test_real_nodes_with_offline_agents(monkeypatch):
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
    monkeypatch.setattr(
        writer_module, "build_writer", lambda: pytest.fail("Aucune news")
    )
    out = graph.build_graph().invoke({"request": "Point sur Nvidia cette semaine"})
    assert out["metrics"] == {"last_close": 123.0}
    assert out["news"] == []
    assert "123.0000" in out["report"] and "999999" not in out["report"]
    assert "Indicateurs indisponibles" in out["report"]


def test_pipeline_with_langchain_tool_calls_offline(monkeypatch):
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
                {"query": "Nvidia", "lookback_days": 7},  # ticker : via le contexte
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
        writer_module, "get_llm", lambda **kw: spy_model('{"news_indices": [0]}')
    )
    monkeypatch.setattr(news, "collect_news", lambda *a, **k: [article])
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
    assert "129.0000" in out["report"]
    assert article["title"] in out["report"]
