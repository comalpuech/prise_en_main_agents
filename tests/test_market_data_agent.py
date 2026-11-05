"""Tests sans réseau : Yahoo Finance et modèle de chat remplacés localement."""

from copy import deepcopy
from datetime import date
from math import sqrt
from types import SimpleNamespace

import pandas as pd
import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage

from market_analyst.agents import market_data_agent as agent_module
from market_analyst.tools import market

END = date(2026, 11, 5)


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    monkeypatch.setattr(
        agent_module,
        "get_settings",
        lambda: SimpleNamespace(
            llm_model="google_genai:gemini-2.5-flash",
            default_lookback_days=7,
        ),
    )
    monkeypatch.setenv("GOOGLE_API_KEY", "offline-test-placeholder")
    agent_module.build_market_data_agent.cache_clear()
    yield


@pytest.fixture
def prices(monkeypatch):
    frame = pd.DataFrame(
        {"Close": [100.0 + i for i in range(30)]},
        index=pd.bdate_range(end="2026-11-04", periods=30, tz="America/New_York"),
    )
    calls = []

    class Ticker:
        def __init__(self, symbol):
            calls.append(symbol)

        def history(self, **kwargs):
            calls.append(kwargs)
            return frame

    monkeypatch.setattr(market.yf, "Ticker", Ticker)
    return frame, calls


def test_metrics_and_download_options(prices):
    frame, calls = prices
    out = market.collect_market_metrics("nvda", 7, as_of=END)
    assert out["last_close"] == 129
    assert out["sma_short"] == 127
    assert out["sma_long"] == 119.5
    assert out["weekly_return_pct"] == pytest.approx((129 / 125 - 1) * 100)
    expected = frame.Close.loc["2026-10-29":].pct_change().std(ddof=1) * sqrt(252) * 100
    assert out["volatility_annualized"] == pytest.approx(expected)
    assert calls[0] == "NVDA"
    assert calls[1]["auto_adjust"] is True
    assert calls[1]["end"] == END.isoformat()
    assert calls[1]["raise_errors"] is True


def test_requested_period_is_not_always_a_week(prices):
    frame, _ = prices
    out = market.collect_market_metrics("NVDA", 14, as_of=END)
    baseline = frame.loc[:"2026-10-22", "Close"].iloc[-1]
    assert out["weekly_return_pct"] == pytest.approx((129 / baseline - 1) * 100)


def test_short_history_omits_unavailable_metrics(prices, monkeypatch):
    frame, _ = prices
    monkeypatch.setattr(market.yf.Ticker, "history", lambda self, **kw: frame.iloc[-3:])
    out = market.collect_market_metrics("NVDA", as_of=END)
    assert out["last_close"] == 129
    assert "sma_short" not in out
    assert "sma_long" not in out
    assert out["weekly_return_pct"] == pytest.approx((129 / 127 - 1) * 100)


@pytest.mark.parametrize("kind", ["empty", "missing_close", "invalid", "stale"])
def test_unusable_data_returns_empty(prices, kind, monkeypatch):
    frame, _ = prices
    if kind == "empty":
        frame = frame.iloc[:0]
    elif kind == "missing_close":
        frame = frame.drop(columns="Close")
    elif kind == "invalid":
        frame["Close"] = float("nan")
    else:
        frame.index = frame.index - pd.Timedelta(days=100)
    monkeypatch.setattr(market.yf.Ticker, "history", lambda self, **kw: frame)
    assert market.collect_market_metrics("INVALID", as_of=END) == {}


def test_network_failure(monkeypatch, caplog):
    def fail(_):
        raise TimeoutError("Yahoo indisponible")

    monkeypatch.setattr(market.yf, "Ticker", fail)
    assert market.collect_market_metrics("NVDA", as_of=END) == {}
    assert "Historique indisponible" in caplog.text


def test_single_close_only(prices, monkeypatch):
    frame, _ = prices
    monkeypatch.setattr(market.yf.Ticker, "history", lambda self, **kw: frame.iloc[-1:])
    assert market.collect_market_metrics("NVDA", as_of=END) == {"last_close": 129}


def test_crypto_annualization(prices):
    stock = market.collect_market_metrics("NVDA", as_of=END)
    crypto = market.collect_market_metrics("BTC-USD", as_of=END)
    assert crypto["volatility_annualized"] == stock["volatility_annualized"]


def test_weekend_boundary_uses_first_session_inside_period(prices):
    frame, _ = prices
    out = market.collect_market_metrics("NVDA", 4, as_of=END)
    # Début dimanche 1 novembre : première clôture du lundi 2 novembre.
    baseline = frame.loc["2026-11-02":, "Close"].iloc[0]
    assert out["weekly_return_pct"] == pytest.approx((129 / baseline - 1) * 100)


def test_invalid_prices_do_not_create_filled_returns(prices):
    frame, _ = prices
    frame.loc[frame.index[-2], "Close"] = 0
    out = market.collect_market_metrics("NVDA", as_of=END)
    assert out["last_close"] == 129
    assert "sma_short" not in out
    clean = frame.Close.where(frame.Close > 0)
    returns = clean.loc["2026-10-29":].pct_change(fill_method=None).dropna()
    assert out["volatility_annualized"] == pytest.approx(
        returns.std() * sqrt(252) * 100
    )


@pytest.mark.parametrize("ticker, days", [("", 7), ("NVDA", 0), ("NVDA", -1)])
def test_invalid_parameters(ticker, days):
    with pytest.raises(ValueError):
        market.collect_market_metrics(ticker, days)
    with pytest.raises(ValueError):
        agent_module.market_data_agent({"ticker": ticker, "lookback_days": days})


def test_actual_langchain_tool_execution(monkeypatch):
    """Exécute create_agent et son ToolNode avec un appel Gemini simulé."""

    class ToolCallingModel(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    model = ToolCallingModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_market_metrics",
                        "args": {
                            "ticker": "NVDA",
                            "lookback_days": 7,
                        },
                        "id": "market-1",
                        "type": "tool_call",
                    }
                ],
            )
        ]
    )
    monkeypatch.setattr(agent_module, "get_llm", lambda: model)
    monkeypatch.setattr(
        market, "collect_market_metrics", lambda *a: {"last_close": 129.0}
    )
    agent_module.build_market_data_agent.cache_clear()
    try:
        assert agent_module.market_data_agent(
            {"ticker": "NVDA", "lookback_days": 7}
        ) == {"metrics": {"last_close": 129.0}}
    finally:
        agent_module.build_market_data_agent.cache_clear()


@pytest.mark.parametrize("wrong_args", [False, True])
def test_llm_numbers_are_never_used(monkeypatch, wrong_args):
    class Agent:
        def invoke(self, payload, config):
            assert "Nvidia" in payload["messages"][0].content
            return {
                "messages": [
                    ToolMessage(
                        content='{"last_close": 99999}',
                        name="get_market_metrics",
                        tool_call_id="1",
                        artifact={
                            "ticker": "MSFT" if wrong_args else "NVDA",
                            "lookback_days": 7,
                            "metrics": {"last_close": 129},
                        },
                    ),
                    AIMessage(content='{"last_close": 99999}'),
                ]
            }

    monkeypatch.setattr(agent_module, "build_market_data_agent", lambda: Agent())
    out = agent_module.market_data_agent(
        {
            "ticker": "NVDA",
            "company": "Nvidia",
            "lookback_days": 7,
            "news": [],
            "request": "point Nvidia",
        }
    )
    assert out == {"metrics": {} if wrong_args else {"last_close": 129}}


def test_missing_tool_call_returns_empty(monkeypatch):
    class Agent:
        def invoke(self, *args, **kwargs):
            return {"messages": [AIMessage(content="last_close = 99999")]}

    monkeypatch.setattr(agent_module, "build_market_data_agent", lambda: Agent())
    assert agent_module.market_data_agent({"ticker": "NVDA"}) == {"metrics": {}}


@pytest.mark.parametrize("reverse", [False, True])
def test_yfinance_multiindex(prices, monkeypatch, reverse):
    frame, _ = prices
    columns = [("Close", "NVDA"), ("Close", "MSFT")]
    if reverse:
        columns = [tuple(reversed(column)) for column in columns]
    multi = pd.concat([frame.Close, frame.Close * 2], axis=1)
    multi.columns = pd.MultiIndex.from_tuples(columns)
    monkeypatch.setattr(market.yf.Ticker, "history", lambda self, **kw: multi)
    assert market.collect_market_metrics("NVDA", as_of=END)["last_close"] == 129


def test_state_is_not_mutated(monkeypatch):
    state = {
        "ticker": "NVDA",
        "news": [{"title": "existant"}],
        "messages": [],
        "metrics": {"last_close": 1},
        "company": "Nvidia",
    }
    before = deepcopy(state)

    class Agent:
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
                            "metrics": {"last_close": 129},
                        },
                    )
                ]
            }

    monkeypatch.setattr(agent_module, "build_market_data_agent", lambda: Agent())
    assert agent_module.market_data_agent(state) == {"metrics": {"last_close": 129}}
    assert state == before


def test_missing_google_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GOOGLE_API_KEY absente"):
        agent_module.build_market_data_agent()


@pytest.mark.parametrize(
    "error", [TimeoutError("réseau"), RuntimeError("404 NOT_FOUND")]
)
def test_llm_failure_preserves_cause(monkeypatch, error):
    class Agent:
        def invoke(self, *a, **kw):
            raise error

    monkeypatch.setattr(agent_module, "build_market_data_agent", lambda: Agent())
    with pytest.raises(RuntimeError, match="GOOGLE_MODEL") as caught:
        agent_module.market_data_agent({"ticker": "NVDA"})
    assert caught.value.__cause__ is error
