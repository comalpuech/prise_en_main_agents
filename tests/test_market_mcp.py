"""Tests hors-ligne du serveur MCP (réseau mocké, client MCP en mémoire)."""

import asyncio
import sys
from pathlib import Path

import pandas as pd
from mcp import Client, StdioServerParameters

from market_analyst.tools.news import Article
from market_mcp import server as mcp_server


def run(coro):
    return asyncio.run(coro)


class FakeTicker:
    def __init__(self, _ticker):
        pass

    def history(self, period):
        return pd.DataFrame(
            {
                "Close": [100.0, 105.0, 110.0],
                "High": [101, 106, 112],
                "Low": [99, 103, 108],
            },
            index=pd.to_datetime(["2026-11-03", "2026-11-04", "2026-11-05"]),
        )


class EmptyTicker(FakeTicker):
    def history(self, period):
        return pd.DataFrame()


def test_server_declares_tools_resource_and_prompt():
    async def check():
        async with Client(mcp_server.mcp) as client:
            tools = {t.name for t in (await client.list_tools()).tools}
            resources = {str(r.uri) for r in (await client.list_resources()).resources}
            prompts = {p.name for p in (await client.list_prompts()).prompts}
        return tools, resources, prompts

    tools, resources, prompts = run(check())

    assert tools == {"ping", "get_news", "get_price_summary"}
    assert resources == {"prompt://writer"}
    assert prompts == {"weekly_note"}


def test_ping_over_mcp():
    async def check():
        async with Client(mcp_server.mcp) as client:
            return await client.call_tool("ping", {"name": "Côme"})

    assert run(check()).content[0].text == "Bonjour Côme"


def test_get_price_summary(monkeypatch):
    monkeypatch.setattr(mcp_server.yf, "Ticker", FakeTicker)

    summary = mcp_server.get_price_summary("nvda", days=7)

    assert summary == {
        "ticker": "NVDA",
        "first_close": 100.0,
        "last_close": 110.0,
        "change_pct": 10.0,
        "high": 112.0,
        "low": 99.0,
        "start": "2026-11-03",
        "end": "2026-11-05",
    }


def test_get_price_summary_unknown_ticker(monkeypatch):
    monkeypatch.setattr(mcp_server.yf, "Ticker", EmptyTicker)

    assert "error" in mcp_server.get_price_summary("XXXX")


def test_get_news_hides_read_url(monkeypatch):
    article = Article(
        title="T",
        source="S",
        url="https://media/x",
        read_url="https://yahoo/x",
        published_at="2026-11-05T08:00:00Z",
        summary="s",
    )
    monkeypatch.setattr(mcp_server, "collect_news", lambda *a: [article])
    monkeypatch.setattr(mcp_server, "add_article_content", lambda articles: articles)

    (result,) = mcp_server.get_news("Nvidia", "NVDA", 7)

    assert result["url"] == "https://media/x"
    assert "read_url" not in result


def test_writer_prompt_resource():
    assert "## Limites de l'analyse" in mcp_server.writer_prompt()


def test_server_runs_as_independent_stdio_process():
    async def check():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "market_mcp"],
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        async with Client(parameters, read_timeout_seconds=10) as client:
            tools = {tool.name for tool in (await client.list_tools()).tools}
            response = await client.call_tool("ping", {"name": "integration"})
            return tools, response.content[0].text

    tools, reply = run(asyncio.wait_for(check(), timeout=20))
    assert tools == {"ping", "get_news", "get_price_summary"}
    assert reply == "Bonjour integration"


def test_mcp_returns_tool_error_on_network_failure(monkeypatch):
    class FailingTicker:
        def __init__(self, ticker):
            pass

        def history(self, period):
            raise TimeoutError("Source de cours indisponible")

    monkeypatch.setattr(mcp_server.yf, "Ticker", FailingTicker)

    async def check():
        async with Client(mcp_server.mcp) as client:
            return await client.call_tool("get_price_summary", {"ticker": "NVDA"})

    assert run(check()).is_error
