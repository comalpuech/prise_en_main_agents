"""Tests sans réseau : Yahoo Finance et modèle de chat remplacés localement."""

from datetime import date
from math import sqrt

import pandas as pd
import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage

from market_analyst.agents import market_data_agent as agent_module
from market_analyst.tools import market

END = date(2026, 11, 5)


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
    expected = frame.Close.pct_change().loc["2026-10-30":].std(ddof=1) * sqrt(252)
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


def test_short_history_omits_unavailable_metrics(prices):
    frame, _ = prices
    frame.drop(frame.index[:-3], inplace=True)
    out = market.collect_market_metrics("NVDA", as_of=END)
    assert out["last_close"] == 129
    assert "sma_short" not in out
    assert "sma_long" not in out
    assert "weekly_return_pct" not in out


@pytest.mark.parametrize("kind", ["empty", "missing_close", "invalid", "stale"])
def test_unusable_data_returns_empty(prices, kind):
    frame, _ = prices
    if kind == "empty":
        frame.drop(frame.index, inplace=True)
    elif kind == "missing_close":
        frame.drop(columns="Close", inplace=True)
    elif kind == "invalid":
        frame["Close"] = float("nan")
    else:
        frame.index = frame.index - pd.Timedelta(days=100)
    assert market.collect_market_metrics("INVALID", as_of=END) == {}


def test_network_failure(monkeypatch, caplog):
    def fail(_):
        raise TimeoutError("Yahoo indisponible")

    monkeypatch.setattr(market.yf, "Ticker", fail)
    assert market.collect_market_metrics("NVDA", as_of=END) == {}
    assert "Historique indisponible" in caplog.text


def test_single_close_only(prices):
    frame, _ = prices
    frame.drop(frame.index[:-1], inplace=True)
    assert market.collect_market_metrics("NVDA", as_of=END) == {"last_close": 129}


def test_crypto_annualization(prices):
    stock = market.collect_market_metrics("NVDA", as_of=END)
    crypto = market.collect_market_metrics("BTC-USD", as_of=END)
    assert crypto["volatility_annualized"] == pytest.approx(
        stock["volatility_annualized"] * sqrt(365 / 252)
    )


def test_weekend_boundary_uses_previous_session(prices):
    frame, _ = prices
    out = market.collect_market_metrics("NVDA", 4, as_of=END)
    # Début dimanche 1 novembre : clôture de référence du vendredi 30 octobre.
    baseline = frame.loc[:"2026-10-30", "Close"].iloc[-1]
    assert out["weekly_return_pct"] == pytest.approx((129 / baseline - 1) * 100)


def test_invalid_prices_do_not_create_filled_returns(prices):
    frame, _ = prices
    frame.loc[frame.index[-2], "Close"] = 0
    out = market.collect_market_metrics("NVDA", as_of=END)
    assert out["last_close"] == 129
    assert "sma_short" not in out
    clean = frame.Close.where(frame.Close > 0)
    returns = clean.pct_change(fill_method=None).loc["2026-10-30":].dropna()
    assert out["volatility_annualized"] == pytest.approx(returns.std() * sqrt(252))


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
