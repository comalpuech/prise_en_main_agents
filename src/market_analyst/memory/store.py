"""Construction du `LangGraph Store`, la mémoire partagée entre les exécutions.

Le Store est créé une seule fois, à la racine (`graph.compile(store=...)`), puis
LangGraph l'injecte partout : `runtime.store` dans les nœuds, les outils
(`ToolRuntime`) et les middlewares, y compris dans l'agent lancé depuis un nœud.
"""

import sqlite3
from pathlib import Path

from langgraph.store.base import BaseStore
from langgraph.store.sqlite import SqliteStore

from market_analyst.config import get_settings

IN_MEMORY = ":memory:"


def build_store(path: str | None = None, ttl_days: int | None = None) -> SqliteStore:
    """`SqliteStore` sur `path` (`MEMORY_STORE_PATH` par défaut, ":memory:" possible).

    Toujours SQLite, même en mémoire : `InMemoryStore` ne sait pas filtrer une plage
    de dates écrites en texte (`{"$gte": "2026-11-05T…"}`), il les convertit en float.

    `SqliteStore.from_conn_string` est un context manager qui ferme la connexion en
    sortie de bloc : il ne convient pas à un Store gardé pendant tout le processus.
    On ouvre donc la connexion nous-mêmes, avec les mêmes options :
    `check_same_thread=False` (LangGraph peut exécuter les outils dans un autre
    thread, le Store sérialise les accès avec un verrou) et l'autocommit.
    """
    settings = get_settings()
    path = path or settings.memory_store_path
    ttl_minutes = (ttl_days or settings.memory_ttl_days) * 24 * 60
    if path != IN_MEMORY:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    # TTL compté depuis la dernière écriture (`put`), sans prolongation à la lecture
    store = SqliteStore(
        conn, ttl={"default_ttl": ttl_minutes, "refresh_on_read": False}
    )
    store.setup()  # crée les tables au premier lancement, migre ensuite
    store.sweep_ttl()  # purge les souvenirs expirés (pas de balayage en tâche de fond)
    return store


def require_store(store: BaseStore | None) -> BaseStore:
    """Échoue bruyamment plutôt que de tourner sans mémoire."""
    if store is None:
        raise RuntimeError(
            "Aucun Store LangGraph : compiler le graphe avec "
            "`compile(store=build_store())` (ou passer `store=` dans les tests)."
        )
    return store
