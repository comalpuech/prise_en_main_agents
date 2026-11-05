"""Cours Yahoo Finance et indicateurs calculés exclusivement en Python."""

import logging
from datetime import UTC, date, datetime, timedelta
from math import isfinite, sqrt

import pandas as pd
import yfinance as yf
from langchain_core.tools import tool

from market_analyst.state import MarketMetrics

logger = logging.getLogger(__name__)


def collect_market_metrics(
    ticker: str, lookback_days: int = 7, *, as_of: date | None = None
) -> MarketMetrics:
    """Indicateurs sur clôtures ajustées, hors séance en cours.

    Le rendement va de la dernière clôture à ou avant le début de la fenêtre
    calendaire à la dernière clôture disponible. Les SMA utilisent 5/20 séances,
    même pour une fenêtre courte. La volatilité utilise les rendements de la
    fenêtre, l'écart-type échantillonnal et 252 séances/an (365 pour XXX-USD).
    Un indicateur non calculable est absent, jamais remplacé par zéro ou NaN.
    """
    if not ticker.strip() or lookback_days <= 0:
        raise ValueError("Un ticker et une période strictement positive sont requis")
    ticker = ticker.strip().upper()
    end = as_of or datetime.now(UTC).date()
    cutoff = pd.Timestamp(end - timedelta(days=lookback_days))
    # Marge pour les week-ends/jours fériés et la SMA 20, sans réduire la période.
    start = end - timedelta(days=max(60, lookback_days + 30))
    try:
        history = yf.Ticker(ticker).history(
            start=start.isoformat(),
            end=end.isoformat(),
            interval="1d",
            auto_adjust=True,
            actions=False,
            timeout=10,
            raise_errors=True,
        )
    except Exception:
        logger.warning("Historique indisponible pour %s", ticker, exc_info=True)
        return {}
    if history.empty or "Close" not in history:
        logger.warning("Aucune clôture pour %s", ticker)
        return {}

    close = pd.to_numeric(history["Close"], errors="coerce").copy()
    # Conserve la date de séance locale, sans décaler les marchés vers UTC.
    close.index = pd.DatetimeIndex(close.index).tz_localize(None).normalize()
    close = close.sort_index()
    close = close[~close.index.duplicated(keep="last")]
    close = close.where(close.map(lambda x: isfinite(x) and x > 0))
    close = close.loc[close.index < pd.Timestamp(end)]
    valid = close.dropna()
    if valid.empty or not (valid.index >= cutoff).any():
        logger.warning("Aucune clôture dans la période pour %s", ticker)
        return {}

    metrics = MarketMetrics(last_close=float(valid.iloc[-1]))
    baseline = valid.loc[valid.index <= cutoff]
    if not baseline.empty and baseline.index[-1] < valid.index[-1]:
        metrics["weekly_return_pct"] = float(
            (valid.iloc[-1] / baseline.iloc[-1] - 1) * 100
        )
    for window, key in ((5, "sma_short"), (20, "sma_long")):
        value = close.rolling(window).mean().iloc[-1]
        if pd.notna(value):
            metrics[key] = float(value)
    returns = close.pct_change(fill_method=None).loc[close.index > cutoff].dropna()
    if len(returns) >= 2:
        sessions = 365 if ticker.endswith("-USD") else 252
        metrics["volatility_annualized"] = float(returns.std(ddof=1) * sqrt(sessions))
    return {key: value for key, value in metrics.items() if isfinite(value)}


@tool(response_format="content_and_artifact", return_direct=True)
def get_market_metrics(ticker: str, lookback_days: int = 7) -> tuple[dict, dict]:
    """Récupère les clôtures Yahoo Finance et calcule les indicateurs déterministes.

    Args:
        ticker: symbole Yahoo Finance exact, par exemple NVDA ou BTC-USD.
        lookback_days: période en jours calendaires, strictement positive.
    """
    metrics = collect_market_metrics(ticker, lookback_days)
    return metrics, {
        "ticker": ticker.strip().upper(),
        "lookback_days": lookback_days,
        "metrics": metrics,
    }
