"""Tests de la mémoire de l'agent de news, rangée dans le Store LangGraph."""

from datetime import UTC, datetime

import pytest
from langgraph.runtime import Runtime

from market_analyst.agents.news_agent import NewsArticle, NewsDigest
from market_analyst.memory.news_memory import (
    SynthesisMemoryMiddleware,
    get_syntheses,
    recent_articles,
    save_articles,
    save_syntheses,
)
from market_analyst.tools import news as news_tools
from tests.conftest import tool_runtime

NOW = datetime(2026, 11, 5, 12, tzinfo=UTC)
SINCE = datetime(2026, 10, 29, 12, tzinfo=UTC)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def article(url: str, published_at: str = "2026-11-04T10:00:00Z", **extra):
    return news_tools.Article(
        title=f"Titre {url}",
        source="Reuters",
        url=url,
        published_at=published_at,
        summary=extra.pop("summary", "Résumé"),
        **extra,
    )


# --- Articles sources ---------------------------------------------------------


def test_articles_roundtrip(store):
    saved = article("https://a", content="Texte", read_url="https://y/a")
    save_articles(store, "nvda", [saved])

    assert recent_articles(store, "NVDA", SINCE) == [saved]


def test_save_articles_keeps_known_content(store):
    save_articles(store, "NVDA", [article("https://a", content="Texte lu")])
    save_articles(store, "NVDA", [article("https://a", summary="")])

    (cached,) = recent_articles(store, "NVDA", SINCE)
    assert cached["content"] == "Texte lu"
    assert cached["summary"] == "Résumé"


def test_recent_articles_filters_by_date_and_ticker(store):
    save_articles(
        store,
        "NVDA",
        [
            article("https://new", "2026-11-04T10:00:00Z"),
            article("https://old", "2026-10-20T10:00:00Z"),
        ],
    )
    save_articles(store, "AMD", [article("https://amd")])

    assert [a["url"] for a in recent_articles(store, "NVDA", SINCE)] == ["https://new"]


def test_recent_articles_is_not_capped_at_store_default(store):
    """`store.search` renvoie 10 éléments par défaut."""
    save_articles(store, "NVDA", [article(f"https://{i}") for i in range(15)])

    assert len(recent_articles(store, "NVDA", SINCE)) == 15


def test_collect_news_prefers_known_version_on_duplicate(monkeypatch):
    fresh = article("https://a", summary="Résumé frais")
    monkeypatch.setattr(news_tools, "fetch_yahoo_news", lambda t, n: [fresh])
    monkeypatch.setattr(news_tools, "fetch_google_news", lambda q, d: [])
    known = article("https://a", content="Texte lu hier")

    (news,) = news_tools.collect_news("Nvidia", "NVDA", now=NOW, known=[known])

    assert news["content"] == "Texte lu hier"


def test_search_news_accumulates_and_does_not_reread(monkeypatch, search_news):
    """Jour 1 : un article Yahoo est lu. Jour 2 : Yahoo ne le renvoie plus, mais
    l'outil le ressort de la mémoire, avec son texte, sans relire la page."""
    day1 = article("https://a", now_iso(), read_url="https://y/a")
    reads: list[str] = []

    def fake_read(url):
        reads.append(url)
        return "Nvidia reported record revenue. " * 30

    monkeypatch.setattr(news_tools, "fetch_google_news", lambda q, d: [])
    monkeypatch.setattr(news_tools, "fetch_article_text", fake_read)
    monkeypatch.setattr(news_tools, "fetch_yahoo_news", lambda t, n: [day1])
    search_news({"query": "Nvidia"})

    monkeypatch.setattr(news_tools, "fetch_yahoo_news", lambda t, n: [])
    (result,) = search_news({"query": "Nvidia"})

    assert result["url"] == "https://a"
    assert result["content"].startswith("Nvidia reported")
    assert reads == ["https://y/a"]  # lu une seule fois


def test_search_news_does_not_keep_title_only_articles(monkeypatch, store, search_news):
    google = article("https://g", now_iso(), summary="")
    monkeypatch.setattr(news_tools, "fetch_google_news", lambda q, d: [google])
    monkeypatch.setattr(news_tools, "fetch_yahoo_news", lambda t, n: [])

    search_news({"query": "Nvidia"})

    assert recent_articles(store, "NVDA", SINCE) == []


def test_search_news_fails_loudly_without_store():
    with pytest.raises(Exception, match="Store"):
        news_tools.search_news.invoke(
            {"query": "Nvidia", "runtime": tool_runtime(None)}
        )


# --- Synthèses ---------------------------------------------------------------


def test_syntheses_by_ticker(store):
    save_syntheses(
        store, "nvda", [article("https://a"), article("https://b", summary="")]
    )

    assert get_syntheses(store, "NVDA", ["https://a", "https://b"]) == {
        "https://a": "Résumé"
    }
    assert get_syntheses(store, "AMD", ["https://a"]) == {}


def test_search_news_returns_known_summary_instead_of_content(
    monkeypatch, store, search_news
):
    known = article("https://a", summary="", content="Texte long")
    monkeypatch.setattr(news_tools, "collect_news", lambda *a, **k: [known])
    save_syntheses(store, "NVDA", [article("https://a", summary="Déjà synthétisé.")])

    (result,) = search_news({"query": "Nvidia"})

    assert result["known_summary"] == "Déjà synthétisé."
    assert "content" not in result


def test_middleware_fills_known_and_saves_new_syntheses(store):
    save_syntheses(store, "NVDA", [article("https://known", summary="Gardée.")])
    digest = NewsDigest(
        articles=[
            NewsArticle(**article("https://known", summary="")),
            NewsArticle(**article("https://new", summary="Nouvelle.")),
        ]
    )
    runtime = Runtime(context=news_tools.NewsContext(ticker="NVDA"), store=store)

    update = SynthesisMemoryMiddleware().after_agent(
        {"structured_response": digest, "messages": []}, runtime
    )

    summaries = [a.summary for a in update["structured_response"].articles]
    assert summaries == ["Gardée.", "Nouvelle."]
    assert get_syntheses(store, "NVDA", ["https://new"]) == {"https://new": "Nouvelle."}
