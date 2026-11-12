"""Tests hors-ligne de l'agent de veille d'actualités (réseau et LLM mockés)."""

from datetime import UTC, datetime

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from market_analyst.agents import news_agent as news_agent_module
from market_analyst.agents.news_agent import NewsArticle, NewsDigest, news_agent
from market_analyst.state import NewsItem
from market_analyst.tools import news as news_tools

NOW = datetime(2026, 11, 5, 12, tzinfo=UTC)


def item(title: str, url: str, published_at: str, summary: str = "", source: str = "X"):
    return NewsItem(
        title=title, source=source, url=url, published_at=published_at, summary=summary
    )


@pytest.fixture
def fake_sources(monkeypatch):
    google = [
        item("Nvidia earnings beat", "https://g/1", "2026-11-04T10:00:00Z"),
        item("Old news", "https://g/2", "2026-10-20T10:00:00Z"),  # hors fenêtre
        item("Same story", "https://g/3", "2026-11-03T10:00:00Z"),
    ]
    yahoo = [
        item(
            "same STORY", "https://y/1", "2026-11-03T11:00:00Z", summary="Résumé Yahoo"
        ),
        item(
            "Nvidia earnings beat", "https://g/1", "2026-11-04T10:00:00Z", summary="dup"
        ),
    ]
    monkeypatch.setattr(news_tools, "fetch_google_news", lambda q, d: list(google))
    monkeypatch.setattr(news_tools, "fetch_yahoo_news", lambda t, n: list(yahoo))


def test_collect_news_filters_dedupes_and_sorts(fake_sources):
    news = news_tools.collect_news("Nvidia", "NVDA", lookback_days=7, now=NOW)

    assert [n["title"] for n in news] == ["Nvidia earnings beat", "same STORY"]
    # en cas de doublon, la version avec résumé (Yahoo) l'emporte
    assert all(n["summary"] for n in news)


def test_collect_news_survives_a_failing_source(monkeypatch):
    def boom(*_):
        raise TimeoutError

    monkeypatch.setattr(news_tools, "fetch_google_news", boom)
    monkeypatch.setattr(
        news_tools,
        "fetch_yahoo_news",
        lambda t, n: [item("A", "u", "2026-11-05T08:00:00Z")],
    )

    assert len(news_tools.collect_news("Nvidia", "NVDA", now=NOW)) == 1


def test_collect_news_spreads_cap_over_days(monkeypatch):
    recent = [item(f"r{i}", f"r{i}", f"2026-11-05T{i:02d}:00:00Z") for i in range(10)]
    older = [item("old", "old", "2026-11-01T10:00:00Z")]
    monkeypatch.setattr(news_tools, "fetch_google_news", lambda q, d: recent + older)

    news = news_tools.collect_news("Nvidia", lookback_days=7, max_results=3, now=NOW)

    assert "old" in [n["title"] for n in news]


class FakeAgent:
    def __init__(self, articles: list[NewsArticle], tool_output: str):
        self.articles, self.tool_output = articles, tool_output
        self.calls: list[dict] = []

    def invoke(self, payload):
        self.calls.append(payload)
        return {
            "messages": [
                *payload["messages"],
                AIMessage(""),
                ToolMessage(self.tool_output, tool_call_id="1"),
            ],
            "structured_response": NewsDigest(articles=self.articles),
        }


def test_news_agent_returns_only_news_and_drops_invented_urls(monkeypatch):
    real = NewsArticle(
        title="T",
        source="S",
        url="https://real",
        published_at="2026-11-04T10:00:00Z",
        summary="Résumé.",
    )
    invented = real.model_copy(update={"url": "https://invented"})
    agent = FakeAgent([real, invented], tool_output='[{"url": "https://real"}]')
    monkeypatch.setattr(news_agent_module, "build_news_agent", lambda: agent)

    out = news_agent(
        {
            "request": "point Nvidia",
            "ticker": "NVDA",
            "company": "Nvidia",
            "lookback_days": 7,
        }
    )

    assert set(out) == {"news"}  # pas de collision au fan-in du graphe
    assert out["news"] == [NewsItem(**real.model_dump())]
    prompt = agent.calls[0]["messages"][0].content
    assert "Nvidia" in prompt
    assert "NVDA" in prompt
    assert "7" in prompt


def test_news_agent_requires_exact_source_url_and_preserves_metadata(monkeypatch):
    import json

    original = NewsArticle(
        title="Titre source",
        source="Source",
        url="https://real/story",
        published_at="2026-11-04T10:00:00Z",
        summary="Synthèse fournie",
    )
    invented = original.model_copy(update={"title": "Titre inventé", "source": "Autre"})
    truncated = original.model_copy(update={"url": "https://real"})
    agent = FakeAgent([invented, truncated], json.dumps([original.model_dump()]))
    monkeypatch.setattr(news_agent_module, "build_news_agent", lambda: agent)
    assert news_agent({"ticker": "NVDA", "lookback_days": 7}) == {
        "news": [original.model_dump()]
    }


RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Nvidia beats estimates - Reuters</title><link>https://news.google.com/a</link>
<pubDate>Wed, 04 Nov 2026 18:29:00 GMT</pubDate><source url="https://reuters.com">Reuters</source></item>
<item><title>No date</title><link>https://news.google.com/b</link></item>
</channel></rss>"""


def test_fetch_google_news_parses_rss(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return RSS

    monkeypatch.setattr(
        news_tools.urllib.request, "urlopen", lambda *a, **k: FakeResponse()
    )

    news = news_tools.fetch_google_news("Nvidia", 7)

    assert news == [
        item(
            "Nvidia beats estimates",
            "https://news.google.com/a",
            "2026-11-04T18:29:00Z",
            source="Reuters",
        )
    ]


def test_fetch_yahoo_news_keeps_only_articles_about_the_asset(monkeypatch):
    def payload(title, symbols, **urls):
        return {
            "content": {
                "title": title,
                "summary": "Résumé",
                "pubDate": "2026-11-05T09:50:00Z",
                "provider": {"displayName": "Motley Fool"},
                "finance": {"stockTickers": [{"symbol": s} for s in symbols]},
                **{k: {"url": v} for k, v in urls.items()},
            }
        }

    class FakeTicker:
        def __init__(self, _):
            pass

        def get_news(self, count):
            return [
                payload(
                    "About NVDA",
                    ["NVDA"],
                    canonicalUrl="https://fool/a",
                    clickThroughUrl="https://y/c",
                ),
                payload("Unrelated", ["RIVN"], canonicalUrl="https://y/x"),
                payload(
                    "Rivian deliveries", ["RIVN", "NVDA"], canonicalUrl="https://y/r"
                ),
            ]

    monkeypatch.setattr(news_tools.yf, "Ticker", FakeTicker)

    news = news_tools.fetch_yahoo_news("nvda", "Nvidia")

    # on cite l'URL du média, on lit la copie hébergée par Yahoo
    assert news == [
        news_tools.Article(
            **item(
                "About NVDA",
                "https://fool/a",
                "2026-11-05T09:50:00Z",
                summary="Résumé",
                source="Motley Fool",
            ),
            read_url="https://y/c",
        )
    ]


def test_collect_news_reserves_half_of_cap_for_yahoo(monkeypatch):
    google = [
        item(f"g{d}{h}", f"g{d}{h}", f"2026-11-0{d}T{h:02d}:00:00Z")
        for d in range(1, 6)
        for h in range(5)
    ]
    yahoo = [
        item(f"y{h}", f"y{h}", f"2026-11-05T{h:02d}:30:00Z", summary="s")
        for h in range(20)
    ]
    monkeypatch.setattr(news_tools, "fetch_google_news", lambda q, d: list(google))
    monkeypatch.setattr(news_tools, "fetch_yahoo_news", lambda t, n: list(yahoo))

    news = news_tools.collect_news("Nvidia", "NVDA", max_results=10, now=NOW)

    assert len(news) == 10
    assert sum(bool(n["summary"]) for n in news) == 5
    assert {n["published_at"][:10] for n in news if not n["summary"]} == {
        f"2026-11-0{d}" for d in range(1, 6)
    }


def test_collect_news_gives_unused_yahoo_quota_to_google(monkeypatch):
    google = [item(f"g{h}", f"g{h}", f"2026-11-04T{h:02d}:00:00Z") for h in range(10)]
    yahoo = [item("y", "y", "2026-11-05T08:00:00Z", summary="s")]
    monkeypatch.setattr(news_tools, "fetch_google_news", lambda q, d: list(google))
    monkeypatch.setattr(news_tools, "fetch_yahoo_news", lambda t, n: list(yahoo))

    news = news_tools.collect_news("Nvidia", "NVDA", max_results=6, now=NOW)

    assert len(news) == 6
    assert sum(bool(n["summary"]) for n in news) == 1


LONG_TEXT = "Nvidia reported record revenue. " * 300  # ~9 600 caractères


def test_add_article_content_reads_truncates_and_falls_back(monkeypatch):
    pages = {"https://y/ok": LONG_TEXT, "https://y/video": "Trop court."}

    def fake_fetch(url):
        if url not in pages:
            raise TimeoutError
        return pages[url]

    monkeypatch.setattr(news_tools, "fetch_article_text", fake_fetch)
    base = item("T", "https://media/x", "2026-11-05T08:00:00Z", summary="Résumé")
    articles = [
        news_tools.Article(**base, read_url="https://y/ok"),
        news_tools.Article(**base, read_url="https://y/video"),
        news_tools.Article(**base, read_url="https://y/down"),
        base,  # Google News : rien à lire
    ]

    ok, video, down, google = news_tools.add_article_content(articles)

    assert ok["content"].startswith("Nvidia reported record revenue.")
    assert len(ok["content"]) <= news_tools.CONTENT_MAX_CHARS + len(" […]")
    assert ok["content"].endswith(" […]")
    assert "content" not in video
    assert "content" not in down
    assert google == base


def test_search_news_exposes_content_but_not_read_url(monkeypatch):
    article = news_tools.Article(
        **item("T", "https://media/x", "2026-11-05T08:00:00Z", summary="s"),
        read_url="https://y/x",
    )
    monkeypatch.setattr(news_tools, "collect_news", lambda *a: [article])
    monkeypatch.setattr(news_tools, "fetch_article_text", lambda url: LONG_TEXT)

    (result,) = news_tools.search_news.invoke(
        {"query": "Nvidia", "ticker": "NVDA", "lookback_days": 7}
    )

    assert result["url"] == "https://media/x"
    assert "read_url" not in result
    assert result["content"]
