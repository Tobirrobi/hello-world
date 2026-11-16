"""CSV-Datenablage: eigene Daten einspielen und Live-Daten regelmäßig archivieren.

Verzeichnisaufbau::

    daten/
      tickers.csv                 ticker,name,sector,currency
      prices/<TICKER>.csv         date,open,high,low,close,volume
      fundamentals/<TICKER>.csv   available_date,period_end,<Felder von FundamentalSnapshot>
      sentiment/<TICKER>.csv      available_date,<Felder von MarketSentimentSnapshot>
      news/<TICKER>.csv           published,headline,summary,source,url

Weil Yahoo Analystendaten, Short Interest und Nachrichten nur als aktuellen
Stand liefert, baut ``archive()`` bei regelmäßiger Ausführung nach und nach
eine eigene Point-in-Time-Historie auf.
"""

from __future__ import annotations

import re
from dataclasses import asdict, fields
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from ..models import FundamentalSnapshot, MarketSentimentSnapshot, NewsItem, TickerInfo
from .base import DataProvider, normalize_prices


def _fname(ticker: str) -> str:
    return re.sub(r"[^A-Za-z0-9.\-]", "_", ticker) + ".csv"


def _to_date(v):
    if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
        return None
    return pd.Timestamp(v).date()


def _clean(v):
    if isinstance(v, float) and pd.isna(v):
        return None
    return v


class CsvProvider(DataProvider):
    name = "CSV-Datenablage"

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _read(self, sub: str, ticker: str) -> pd.DataFrame:
        p = self.root / sub / _fname(ticker)
        return pd.read_csv(p) if p.exists() else pd.DataFrame()

    def prices(self, ticker, start, end):
        df = self._read("prices", ticker)
        if df.empty:
            raise FileNotFoundError(f"Keine Kursdatei für {ticker} unter {self.root / 'prices'}")
        df = df.set_index(pd.to_datetime(df.pop("date")))
        return normalize_prices(df).loc[pd.Timestamp(start):pd.Timestamp(end)]

    def info(self, ticker):
        p = self.root / "tickers.csv"
        if p.exists():
            df = pd.read_csv(p).fillna("")
            row = df[df["ticker"] == ticker]
            if not row.empty:
                r = row.iloc[0]
                return TickerInfo(ticker, str(r.get("name", "")), str(r.get("sector", "")), str(r.get("currency", "")))
        return TickerInfo(ticker)

    def fundamentals(self, ticker):
        df = self._read("fundamentals", ticker)
        names = {f.name for f in fields(FundamentalSnapshot)}
        out = []
        for rec in df.to_dict("records"):
            kw = {k: _clean(v) for k, v in rec.items() if k in names}
            kw["available_date"] = _to_date(kw["available_date"])
            kw["period_end"] = _to_date(kw.get("period_end"))
            out.append(FundamentalSnapshot(**kw))
        return sorted(out, key=lambda s: s.available_date)

    def market_sentiment(self, ticker):
        df = self._read("sentiment", ticker)
        names = {f.name for f in fields(MarketSentimentSnapshot)}
        out = []
        for rec in df.to_dict("records"):
            kw = {k: _clean(v) for k, v in rec.items() if k in names}
            kw["available_date"] = _to_date(kw["available_date"])
            kw["next_earnings_date"] = _to_date(kw.get("next_earnings_date"))
            if kw.get("analyst_count") is not None:
                kw["analyst_count"] = int(kw["analyst_count"])
            out.append(MarketSentimentSnapshot(**kw))
        return sorted(out, key=lambda s: s.available_date)

    def news(self, ticker, start, end):
        df = self._read("news", ticker)
        out = []
        for rec in df.fillna("").to_dict("records"):
            pub = pd.Timestamp(rec["published"]).to_pydatetime()
            if start <= pub <= end:
                out.append(NewsItem(pub, rec["headline"], rec.get("summary", ""), rec.get("source", ""), rec.get("url", "")))
        return out


def _merge_write(path: Path, new: pd.DataFrame, key: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old = pd.read_csv(path)
        before = len(old)
        merged = pd.concat([old, new.astype(object)], ignore_index=True)
        merged[key] = merged[key].astype(str)
        merged = merged.drop_duplicates(subset=[key] if key != "published" else ["published", "headline"], keep="last")
    else:
        before = 0
        merged = new
    merged = merged.sort_values(key)
    merged.to_csv(path, index=False)
    return len(merged) - before


def archive(provider: DataProvider, tickers: list[str], root: str | Path, history_days: int = 800) -> dict[str, int]:
    """Speichert Kurse, Fundamentaldaten, Erwartungen und Nachrichten in die CSV-Ablage (inkrementell)."""
    root = Path(root)
    end = date.today()
    start = end - timedelta(days=history_days)
    stats: dict[str, int] = {}
    infos = []
    for t in tickers:
        info = provider.info(t)
        infos.append(asdict(info))
        px = provider.prices(t, start, end)
        if not px.empty:
            df = px.reset_index().rename(columns={"index": "date", "Date": "date"})
            df["date"] = pd.to_datetime(df.iloc[:, 0]).dt.strftime("%Y-%m-%d")
            df = df[["date", "open", "high", "low", "close", "volume"]]
            stats[f"{t}:prices"] = _merge_write(root / "prices" / _fname(t), df, "date")
        f = provider.fundamentals(t)
        if f:
            stats[f"{t}:fundamentals"] = _merge_write(root / "fundamentals" / _fname(t),
                                                      pd.DataFrame([asdict(x) for x in f]), "available_date")
        s = provider.market_sentiment(t)
        if s:
            stats[f"{t}:sentiment"] = _merge_write(root / "sentiment" / _fname(t),
                                                   pd.DataFrame([asdict(x) for x in s]), "available_date")
        n = provider.news(t, datetime.combine(start, datetime.min.time()), datetime.now())
        if n:
            stats[f"{t}:news"] = _merge_write(root / "news" / _fname(t), pd.DataFrame([asdict(x) for x in n]), "published")
    tk = root / "tickers.csv"
    _merge_write(tk, pd.DataFrame(infos), "ticker")
    return stats
