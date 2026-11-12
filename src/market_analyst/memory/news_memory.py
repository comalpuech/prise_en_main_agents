"""Mémoire de l'agent de news, rangée dans le `LangGraph Store`.

Deux namespaces par ticker, clé = URL de l'article :

- `("news", <TICKER>, "articles")` : les articles sources riches (résumé Yahoo, texte
  lu sur la page). Yahoo ne remonte que les dernières heures : en les gardant, un
  agent lancé chaque jour dispose en fin de semaine d'articles riches sur toute la
  période, sans relire les pages déjà lues.
- `("news", <TICKER>, "syntheses")` : la synthèse en français déjà écrite par l'agent.

Les deux restent séparés : un article source ne contient jamais la synthèse du LLM,
qui, relue comme un champ de l'outil, passerait pour une source.
"""

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime
from langgraph.store.base import BaseStore

from market_analyst.memory.store import require_store

# `store.search` renvoie 10 éléments par défaut : on veut toute la période.
MAX_ARTICLES = 500


def _to_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def articles_namespace(ticker: str) -> tuple[str, ...]:
    return ("news", ticker.upper(), "articles")


def syntheses_namespace(ticker: str) -> tuple[str, ...]:
    return ("news", ticker.upper(), "syntheses")


def recent_articles(
    store: BaseStore, ticker: str, since: datetime
) -> list[dict[str, Any]]:
    """Articles de `ticker` publiés depuis `since`, du plus récent au plus ancien.

    Le filtre compare des chaînes : c'est correct parce que toutes les dates sont au
    même format ISO UTC (`2026-11-05T09:50:00Z`), où l'ordre alphabétique est
    l'ordre chronologique.
    """
    items = store.search(
        articles_namespace(ticker),
        filter={"published_at": {"$gte": _to_iso(since)}},
        limit=MAX_ARTICLES,
    )
    return sorted(
        (item.value for item in items), key=lambda a: a["published_at"], reverse=True
    )


def save_articles(
    store: BaseStore, ticker: str, articles: Iterable[Mapping[str, Any]]
) -> None:
    """Ajoute ou complète les articles, sans rien perdre de ce qui était connu.

    `put` remplace toute la valeur : un article revu dont la page a échoué cette
    fois-ci effacerait son texte. On relit donc l'ancienne valeur et on fusionne
    (get → fusion → put).
    """
    namespace = articles_namespace(ticker)
    for article in articles:
        old = store.get(namespace, article["url"])
        merged = dict(article)
        if old:
            for field in ("summary", "content", "read_url"):
                if not merged.get(field) and old.value.get(field):
                    merged[field] = old.value[field]
        store.put(namespace, article["url"], merged)


def get_syntheses(store: BaseStore, ticker: str, urls: Iterable[str]) -> dict[str, str]:
    """Synthèses déjà écrites pour ces URLs, par URL (absentes si inconnues)."""
    namespace = syntheses_namespace(ticker)
    found = {url: store.get(namespace, url) for url in urls}
    return {url: item.value["summary"] for url, item in found.items() if item}


def save_syntheses(
    store: BaseStore, ticker: str, articles: Iterable[Mapping[str, Any]]
) -> None:
    """Retient la synthèse de chaque article ; une nouvelle remplace l'ancienne."""
    namespace = syntheses_namespace(ticker)
    for article in articles:
        if article["summary"]:
            store.put(
                namespace,
                article["url"],
                {
                    "summary": article["summary"],
                    "title": article["title"],
                    "published_at": article["published_at"],
                },
            )


class SynthesisMemoryMiddleware(AgentMiddleware):
    """Après l'agent : complète les synthèses connues, puis retient les nouvelles.

    Pour un article déjà synthétisé, l'outil fournit `known_summary` et l'agent laisse
    `summary` vide : on y remet la synthèse gardée, à l'identique (le LLM, à qui on
    demandait de la recopier, la reformulait parfois). Retenir une synthèse est une
    règle, pas une décision du LLM : c'est le code qui écrit, pas l'agent.

    Un middleware n'est pas une API de mémoire : c'est le point d'accroche que
    `create_agent` prévoit pour agir avant ou après l'agent, le modèle ou les outils.
    """

    def after_agent(self, state: dict[str, Any], runtime: Runtime) -> dict | None:
        digest = state.get("structured_response")
        ticker = getattr(runtime.context, "ticker", "")
        if digest is None or not ticker:
            return None
        store = require_store(runtime.store)

        known = get_syntheses(store, ticker, (a.url for a in digest.articles))
        articles = [
            a.model_copy(update={"summary": known[a.url]})
            if not a.summary and a.url in known
            else a
            for a in digest.articles
        ]
        # Une URL inventée serait aussi retenue, mais jamais relue : seules les URLs
        # renvoyées par l'outil sont cherchées (et le nœud écarte les inventées).
        save_syntheses(store, ticker, (a.model_dump() for a in articles))
        return {"structured_response": digest.model_copy(update={"articles": articles})}
