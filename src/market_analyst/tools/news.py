"""Outils de collecte d'actualités (sans clé d'API).

Deux sources complémentaires :
- Google News RSS : couvre toute la période demandée, mais ne fournit que le titre ;
- Yahoo Finance (yfinance) : fournit un résumé, mais ne remonte que les dernières heures.

Le filtrage par date, la déduplication et le plafonnement sont faits en Python,
pas par le LLM : l'agent ne voit que des articles déjà dans la fenêtre.
"""

import logging
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

import yfinance as yf
from langchain_core.tools import tool

from market_analyst.state import NewsItem

logger = logging.getLogger(__name__)

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
USER_AGENT = "Mozilla/5.0 (compatible; market-analyst/0.1)"
HTTP_TIMEOUT_S = 10
MAX_RESULTS = 30


def _to_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def fetch_google_news(query: str, lookback_days: int) -> list[NewsItem]:
    """Articles Google News RSS (anglais) correspondant à `query` sur `lookback_days`."""
    params = urllib.parse.urlencode(
        {
            "q": f"{query} when:{lookback_days}d",
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
        }
    )
    request = urllib.request.Request(
        f"{GOOGLE_NEWS_RSS}?{params}", headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
        root = ET.fromstring(response.read())

    items: list[NewsItem] = []
    for node in root.iterfind("./channel/item"):
        source = node.findtext("source", default="").strip()
        title = node.findtext("title", default="").strip()
        # Google suffixe les titres par " - <source>"
        title = title.removesuffix(f" - {source}") if source else title
        pub_date = node.findtext("pubDate")
        if not (title and pub_date):
            continue
        items.append(
            NewsItem(
                title=title,
                source=source,
                url=node.findtext("link", default="").strip(),
                published_at=_to_iso(parsedate_to_datetime(pub_date)),
                summary="",
            )
        )
    return items


def fetch_yahoo_news(ticker: str, name: str) -> list[NewsItem]:
    """Articles Yahoo Finance qui portent vraiment sur l'actif.

    Yahoo associe un ticker à presque tout article du secteur (NVDA à tout ce qui
    parle d'IA) : on exige en plus que le nom (`name`) ou le symbole (« NVDA »,
    « BTC » pour « BTC-USD ») apparaisse dans le titre ou le résumé.
    """
    symbol = ticker.split("-")[0]
    mention = re.compile(rf"\b({re.escape(name)}|{re.escape(symbol)})\b", re.IGNORECASE)
    items: list[NewsItem] = []
    for raw in yf.Ticker(ticker).get_news(count=50):
        content = raw.get("content") or {}
        tickers = {
            t.get("symbol", "").upper()
            for t in (content.get("finance") or {}).get("stockTickers") or []
        }
        if ticker.upper() not in tickers:
            continue
        if not mention.search(
            f"{content.get('title', '')} {content.get('summary', '')}"
        ):
            continue
        url = (content.get("canonicalUrl") or content.get("clickThroughUrl") or {}).get(
            "url"
        )
        pub_date = content.get("pubDate")
        if not (content.get("title") and url and pub_date):
            continue
        items.append(
            NewsItem(
                title=content["title"].strip(),
                source=(content.get("provider") or {}).get("displayName", ""),
                url=url,
                published_at=_to_iso(datetime.fromisoformat(pub_date)),
                summary=(content.get("summary") or "").strip(),
            )
        )
    return items


def collect_news(
    query: str,
    ticker: str | None = None,
    lookback_days: int = 7,
    max_results: int = MAX_RESULTS,
    now: datetime | None = None,
) -> list[NewsItem]:
    """Agrège les sources, filtre sur la fenêtre, déduplique et trie (plus récent d'abord).

    Jusqu'à la moitié du plafond est réservée à Yahoo : ses articles ont un résumé
    mais datent tous des dernières heures, et seraient sinon évincés par la
    répartition jour par jour des articles Google News. La place inutilisée par
    une source revient à l'autre. Une source en échec est journalisée et ignorée.
    """
    cutoff = (now or datetime.now(UTC)) - timedelta(days=lookback_days)
    seen: set[str] = set()
    # Yahoo d'abord : prioritaire en cas de doublon, puisqu'il a un résumé
    yahoo = _fresh_unique(
        _safe_fetch(fetch_yahoo_news, ticker, query) if ticker else [], cutoff, seen
    )
    google = _fresh_unique(
        _safe_fetch(fetch_google_news, query, lookback_days), cutoff, seen
    )

    google_part = _spread_over_days(
        google, max_results - min(len(yahoo), max_results // 2)
    )
    yahoo_part = _spread_over_days(yahoo, max_results - len(google_part))
    return sorted(
        yahoo_part + google_part, key=lambda i: i["published_at"], reverse=True
    )


def _safe_fetch(fetch: Callable[..., list[NewsItem]], *args) -> list[NewsItem]:
    try:
        return fetch(*args)
    except Exception:  # réseau, format inattendu… on dégrade sans planter
        logger.warning(
            "Source d'actualités indisponible : %s", fetch.__name__, exc_info=True
        )
        return []


def _fresh_unique(
    items: list[NewsItem], cutoff: datetime, seen: set[str]
) -> list[NewsItem]:
    """Garde les articles postérieurs à `cutoff` et pas encore vus (URL ou titre)."""
    kept: list[NewsItem] = []
    for item in items:
        key = item["title"].casefold()
        if datetime.fromisoformat(item["published_at"]) < cutoff:
            continue
        if item["url"] in seen or key in seen:
            continue
        seen.update({item["url"], key})
        kept.append(item)
    return kept


def _spread_over_days(items: list[NewsItem], max_results: int) -> list[NewsItem]:
    """Plafonne à `max_results` en piochant à tour de rôle dans chaque jour.

    Évite qu'une journée chargée n'évince le reste de la période.
    """
    by_day: dict[str, list[NewsItem]] = {}
    for item in sorted(items, key=lambda i: i["published_at"], reverse=True):
        by_day.setdefault(item["published_at"][:10], []).append(item)

    picked: list[NewsItem] = []
    queues = list(by_day.values())
    while len(picked) < max_results and any(queues):
        for queue in queues:
            if queue and len(picked) < max_results:
                picked.append(queue.pop(0))
    return picked


@tool
def search_news(query: str, ticker: str = "", lookback_days: int = 7) -> list[dict]:
    """Recherche les actualités récentes sur une entreprise ou une crypto.

    Args:
        query: nom de l'entreprise ou de l'actif en anglais (ex. "Nvidia", "Bitcoin").
        ticker: symbole Yahoo Finance (ex. "NVDA", "BTC-USD"), vide si inconnu.
        lookback_days: profondeur de la recherche en jours.

    Returns:
        Liste d'articles (title, source, url, published_at ISO UTC, summary éventuellement vide),
        du plus récent au plus ancien.
    """
    return [dict(item) for item in collect_news(query, ticker or None, lookback_days)]
