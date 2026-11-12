"""Serveur MCP exposant les outils de marché (transport stdio).

Indépendant du workflow agentique : il n'utilise ni le graphe ni les agents,
seulement la collecte d'actualités et le prompt du rédacteur de `market_analyst`.

Lancement : `uv run market-mcp` (ou `uv run python -m market_mcp`)
Inspecteur : `uv run mcp dev src/market_mcp/server.py`

Attention : en stdio, stdout sert au protocole. Aucun print() ici, seulement `logging`
(qui écrit sur stderr).
"""

import logging
from importlib.resources import files

import yfinance as yf
from mcp.server.mcpserver import MCPServer

from market_analyst.tools.news import add_article_content, collect_news

logger = logging.getLogger(__name__)

WRITER_PROMPT = files("market_analyst") / "prompts" / "writer.md"

mcp = MCPServer("market-mcp")


@mcp.tool()
def ping(name: str) -> str:
    """Outil de test : renvoie un bonjour."""
    return f"Bonjour {name}"


@mcp.tool()
def get_news(query: str, ticker: str = "", lookback_days: int = 7) -> list[dict]:
    """Actualités récentes sur une entreprise ou une crypto (Google News + Yahoo Finance).

    Args:
        query: nom de l'actif en anglais (ex. "Nvidia", "Bitcoin").
        ticker: symbole Yahoo Finance (ex. "NVDA", "BTC-USD"), vide si inconnu.
        lookback_days: profondeur de la recherche en jours.

    Returns:
        Articles du plus récent au plus ancien : title, source, url, published_at
        (ISO UTC), summary (parfois vide) et, pour certains, content (texte de l'article).
    """
    articles = add_article_content(collect_news(query, ticker or None, lookback_days))
    return [{k: v for k, v in a.items() if k != "read_url"} for a in articles]


@mcp.tool()
def get_price_summary(ticker: str, days: int = 7) -> dict:
    """Résumé du cours d'une action ou d'une crypto sur les derniers jours.

    Args:
        ticker: symbole Yahoo Finance (ex. "NVDA", "BTC-USD").
        days: période en jours calendaires.

    Returns:
        ticker, first_close, last_close, change_pct (variation en %), high, low,
        start et end (dates des séances), ou `error` si aucune donnée.
    """
    history = yf.Ticker(ticker).history(period=f"{days}d")
    if history.empty:
        return {"ticker": ticker, "error": "Aucune donnée de cours pour ce ticker."}

    closes = history["Close"]
    first, last = float(closes.iloc[0]), float(closes.iloc[-1])
    return {
        "ticker": ticker.upper(),
        "first_close": round(first, 2),
        "last_close": round(last, 2),
        "change_pct": round((last - first) / first * 100, 2),
        "high": round(float(history["High"].max()), 2),
        "low": round(float(history["Low"].min()), 2),
        "start": history.index[0].date().isoformat(),
        "end": history.index[-1].date().isoformat(),
    }


@mcp.resource("prompt://writer")
def writer_prompt() -> str:
    """Prompt système de l'agent rédacteur (règles et format de la note)."""
    return WRITER_PROMPT.read_text(encoding="utf-8")


@mcp.prompt()
def weekly_note(company: str, ticker: str) -> str:
    """Demande une note d'analyse hebdomadaire sur un actif, avec les outils du serveur."""
    return (
        f"Fais-moi un point sur {company} ({ticker}) cette semaine. "
        f"Utilise get_news et get_price_summary, puis rédige la note en respectant "
        f"les règles de la ressource prompt://writer."
    )


def main() -> None:
    logging.basicConfig(level=logging.WARNING)  # stderr, jamais stdout
    mcp.run()  # transport stdio par défaut


if __name__ == "__main__":
    main()
