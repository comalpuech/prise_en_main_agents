import pytest
from langchain.tools import ToolRuntime
from langgraph.store.base import BaseStore

from market_analyst import graph
from market_analyst.memory.store import IN_MEMORY, build_store
from market_analyst.tools import news as news_tools


@pytest.fixture(autouse=True)
def no_real_memory(monkeypatch):
    """`build_graph()` sans Store explicite : mémoire jetable, jamais `data/memory.db`."""
    monkeypatch.setattr(graph, "build_store", lambda: build_store(IN_MEMORY))


@pytest.fixture
def store() -> BaseStore:
    """Store vide par test (SQLite en mémoire) : jamais le vrai `data/memory.db`."""
    return build_store(IN_MEMORY, ttl_days=30)


def tool_runtime(store: BaseStore | None, ticker: str = "NVDA") -> ToolRuntime:
    """Ce que LangGraph injecte dans un outil appelé par l'agent."""
    return ToolRuntime(
        state={},
        context=news_tools.NewsContext(ticker=ticker),
        config={},
        stream_writer=lambda _: None,
        tool_call_id="test",
        store=store,
    )


@pytest.fixture
def search_news(store):
    """Appelle l'outil comme le ferait l'agent : Store et ticker via le `runtime`."""

    def invoke(args: dict, ticker: str = "NVDA") -> list[dict]:
        runtime = tool_runtime(store, ticker)
        return news_tools.search_news.invoke({**args, "runtime": runtime})

    return invoke
