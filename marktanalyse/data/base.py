"""Schnittstelle für Datenquellen."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta

import pandas as pd

from ..models import FundamentalSnapshot, MarketSentimentSnapshot, NewsItem, TickerInfo

PRICE_COLUMNS = ["open", "high", "low", "close", "volume"]


def normalize_prices(df: pd.DataFrame) -> pd.DataFrame:
    """Einheitliches Format: tz-naiver DatetimeIndex, Spalten open/high/low/close/volume."""
    if df is None or df.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS)
    df = df.rename(columns={c: str(c).lower().replace(" ", "_") for c in df.columns})
    if "adj_close" in df.columns and "close" not in df.columns:
        df["close"] = df["adj_close"]
    idx = pd.to_datetime(df.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    df.index = idx.normalize()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    for col in PRICE_COLUMNS:
        if col not in df.columns:
            df[col] = df["close"] if col != "volume" else 0.0
    return df[PRICE_COLUMNS].astype(float).dropna(subset=["close"])


class DataProvider(ABC):
    name = "base"

    @abstractmethod
    def prices(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        """Tageskurse (inkl. ``end``)."""

    def info(self, ticker: str) -> TickerInfo:
        return TickerInfo(ticker=ticker)

    def fundamentals(self, ticker: str) -> list[FundamentalSnapshot]:
        return []

    def market_sentiment(self, ticker: str) -> list[MarketSentimentSnapshot]:
        return []

    def news(self, ticker: str, start: datetime, end: datetime) -> list[NewsItem]:
        return []


class CachedProvider(DataProvider):
    """Lädt jede Zeitreihe nur einmal (wichtig für Backtests und Zeitplan-Läufe)."""

    def __init__(self, inner: DataProvider, start: date, end: date):
        self.inner = inner
        self.name = f"{inner.name} (Cache)"
        self.start, self.end = start, end
        self._prices: dict[str, pd.DataFrame] = {}
        self._info: dict[str, TickerInfo] = {}
        self._fund: dict[str, list] = {}
        self._sent: dict[str, list] = {}
        self._news: dict[str, list] = {}

    def prices(self, ticker, start, end):
        if ticker not in self._prices:
            self._prices[ticker] = normalize_prices(self.inner.prices(ticker, self.start, self.end))
        df = self._prices[ticker]
        return df.loc[pd.Timestamp(start):pd.Timestamp(end)]

    def info(self, ticker):
        if ticker not in self._info:
            self._info[ticker] = self.inner.info(ticker)
        return self._info[ticker]

    def fundamentals(self, ticker):
        if ticker not in self._fund:
            self._fund[ticker] = self.inner.fundamentals(ticker)
        return self._fund[ticker]

    def market_sentiment(self, ticker):
        if ticker not in self._sent:
            self._sent[ticker] = self.inner.market_sentiment(ticker)
        return self._sent[ticker]

    def earnings_history(self, ticker, limit: int = 12):
        if not hasattr(self.inner, "earnings_history"):
            return None
        key = (ticker, limit)
        if not hasattr(self, "_earn"):
            self._earn = {}
        if key not in self._earn:
            self._earn[key] = self.inner.earnings_history(ticker, limit)
        return self._earn[key]

    def news(self, ticker, start, end):
        if ticker not in self._news:
            self._news[ticker] = self.inner.news(
                ticker,
                datetime.combine(self.start, datetime.min.time()) - timedelta(days=30),
                datetime.combine(self.end, datetime.max.time()),
            )
        return [n for n in self._news[ticker] if start <= n.published <= end]
