"""Echte Marktdaten über Yahoo Finance (Paket ``yfinance``).

Point-in-Time-Hinweise:
* Kurse sind vollständig historisch verfügbar.
* Fundamentaldaten werden aus Quartals- und Jahresabschlüssen rekonstruiert
  und erst ``report_lag_days`` nach Periodenende als "bekannt" markiert.
  Yahoo liefert nur ca. 5 Quartale bzw. 4 Geschäftsjahre.
* Analysten, Short Interest, Forward-EPS und Nachrichten gibt es nur als
  aktuellen Stand. Sie fließen deshalb nur in Analysen der letzten Tage ein.
  Wer sie historisch nutzen will, archiviert sie regelmäßig mit
  ``marktanalyse archive`` (siehe CsvStore).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd

from ..models import FundamentalSnapshot, MarketSentimentSnapshot, NewsItem, TickerInfo
from .base import DataProvider, normalize_prices

log = logging.getLogger(__name__)

FIELDS = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "gross_profit": ["Gross Profit"],
    "operating_income": ["Operating Income", "EBIT"],
    "net_income": ["Net Income Common Stockholders", "Net Income", "Net Income From Continuing Operation Net Minority Interest"],
    "ebitda": ["EBITDA", "Normalized EBITDA"],
    "interest_expense": ["Interest Expense", "Interest Expense Non Operating"],
    "eps": ["Diluted EPS", "Basic EPS"],
    "total_assets": ["Total Assets"],
    "total_liabilities": ["Total Liabilities Net Minority Interest", "Total Liabilities"],
    "equity": ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"],
    "total_debt": ["Total Debt"],
    "cash": ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"],
    "current_assets": ["Current Assets"],
    "current_liabilities": ["Current Liabilities"],
    "retained_earnings": ["Retained Earnings"],
    "shares": ["Ordinary Shares Number", "Share Issued"],
    "cfo": ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"],
    "capex": ["Capital Expenditure"],
    "fcf": ["Free Cash Flow"],
    "dividends": ["Cash Dividends Paid", "Common Stock Dividend Paid"],
}


def _get(df: Optional[pd.DataFrame], key: str, col) -> Optional[float]:
    if df is None or df.empty or col not in df.columns:
        return None
    for name in FIELDS[key]:
        if name in df.index:
            v = df.at[name, col]
            if pd.notna(v):
                return float(v)
    return None


def _ttm(df: Optional[pd.DataFrame], key: str, cols: list) -> Optional[float]:
    """Summe der letzten 4 Quartale (alle müssen vorhanden sein)."""
    vals = [_get(df, key, c) for c in cols]
    if len(vals) < 4 or any(v is None for v in vals):
        return None
    return float(sum(vals))


class YahooProvider(DataProvider):
    name = "Yahoo Finance"

    def __init__(self, report_lag_days: int = 45, annual_lag_days: int = 75):
        try:
            import yfinance as yf
        except ImportError as exc:  # pragma: no cover
            raise ImportError("Für echte Kursdaten bitte installieren: pip install 'marktanalyse[yahoo]'") from exc
        self.yf = yf
        self.report_lag_days = report_lag_days
        self.annual_lag_days = annual_lag_days
        self._tickers: dict = {}

    def _t(self, ticker: str):
        if ticker not in self._tickers:
            self._tickers[ticker] = self.yf.Ticker(ticker)
        return self._tickers[ticker]

    def prices(self, ticker, start, end):
        df = self._t(ticker).history(start=start, end=end + timedelta(days=1), auto_adjust=True, actions=False)
        return normalize_prices(df)

    def info(self, ticker):
        try:
            i = self._t(ticker).info or {}
        except Exception as exc:
            log.warning("Info für %s nicht abrufbar: %s", ticker, exc)
            i = {}
        return TickerInfo(
            ticker=ticker,
            name=i.get("longName") or i.get("shortName") or ticker,
            sector=i.get("sector") or "",
            currency=i.get("currency") or "",
        )

    def fundamentals(self, ticker):
        t = self._t(ticker)
        snaps: list[FundamentalSnapshot] = []
        try:
            qi, qb, qc = t.quarterly_income_stmt, t.quarterly_balance_sheet, t.quarterly_cashflow
            ai, ab, ac = t.income_stmt, t.balance_sheet, t.cashflow
        except Exception as exc:
            log.warning("Fundamentaldaten für %s nicht abrufbar: %s", ticker, exc)
            return []

        # Jahresabschlüsse (längere Historie)
        if ab is not None and not ab.empty:
            for col in sorted(ab.columns):
                snaps.append(self._snapshot(col, ai, ab, ac, None, self.annual_lag_days))
        # Quartale mit TTM aus 4 Quartalen (präziser, aber kürzere Historie)
        if qb is not None and not qb.empty and qi is not None and not qi.empty:
            qcols = sorted(qi.columns)
            for i in range(3, len(qcols)):
                window = qcols[i - 3:i + 1]
                col = window[-1]
                if col not in qb.columns:
                    continue
                snaps.append(self._snapshot(col, qi, qb, qc, window, self.report_lag_days))
        snaps = [s for s in snaps if s is not None]
        # bei gleichem Verfügbarkeitsdatum den Quartals-Snapshot bevorzugen
        dedup = {}
        for s in sorted(snaps, key=lambda s: s.available_date):
            dedup[s.available_date] = s
        return list(dedup.values())

    def _snapshot(self, col, inc, bal, cf, ttm_cols, lag) -> Optional[FundamentalSnapshot]:
        period_end = pd.Timestamp(col).date()

        def flow(key):
            if ttm_cols is None:
                return _get(inc if key not in ("cfo", "capex", "fcf", "dividends") else cf, key, col)
            src = inc if key not in ("cfo", "capex", "fcf", "dividends") else cf
            return _ttm(src, key, ttm_cols)

        shares = _get(bal, "shares", col)
        ni = flow("net_income")
        eps = flow("eps")
        if eps is None and ni is not None and shares:
            eps = ni / shares
        divs = flow("dividends")
        capex = flow("capex")
        return FundamentalSnapshot(
            available_date=period_end + timedelta(days=lag),
            period_end=period_end,
            shares_outstanding=shares,
            eps_ttm=eps,
            revenue_ttm=flow("revenue"),
            gross_profit_ttm=flow("gross_profit"),
            operating_income_ttm=flow("operating_income"),
            net_income_ttm=ni,
            ebitda_ttm=flow("ebitda"),
            interest_expense_ttm=flow("interest_expense"),
            operating_cash_flow_ttm=flow("cfo"),
            capex_ttm=abs(capex) if capex is not None else None,
            free_cash_flow_ttm=flow("fcf"),
            dividends_per_share_ttm=(abs(divs) / shares) if divs is not None and shares else None,
            total_assets=_get(bal, "total_assets", col),
            total_liabilities=_get(bal, "total_liabilities", col),
            total_equity=_get(bal, "equity", col),
            total_debt=_get(bal, "total_debt", col),
            cash=_get(bal, "cash", col),
            current_assets=_get(bal, "current_assets", col),
            current_liabilities=_get(bal, "current_liabilities", col),
            retained_earnings=_get(bal, "retained_earnings", col),
        )

    def market_sentiment(self, ticker):
        t = self._t(ticker)
        try:
            i = t.info or {}
        except Exception:
            i = {}
        next_earn = None
        try:
            cal = t.calendar
            if isinstance(cal, dict) and cal.get("Earnings Date"):
                ed = cal["Earnings Date"]
                next_earn = ed[0] if isinstance(ed, list) else ed
                if isinstance(next_earn, datetime):
                    next_earn = next_earn.date()
        except Exception:
            pass
        insider = None
        try:
            ip = t.insider_purchases
            if ip is not None and not ip.empty:
                row = ip[ip.iloc[:, 0].astype(str).str.contains("% Net Shares", na=False)]
                if not row.empty:
                    insider = float(row.iloc[0, 1])  # z. B. 0.05 = netto 5 % gekauft
                    insider = max(-1.0, min(1.0, insider * 10))
        except Exception:
            pass
        return [MarketSentimentSnapshot(
            available_date=date.today(),
            analyst_rating=i.get("recommendationMean"),
            analyst_count=i.get("numberOfAnalystOpinions"),
            target_price=i.get("targetMeanPrice"),
            eps_forward=i.get("forwardEps"),
            short_interest_pct=i.get("shortPercentOfFloat"),
            days_to_cover=i.get("shortRatio"),
            insider_net_buying=insider,
            next_earnings_date=next_earn,
        )]

    def news(self, ticker, start, end):
        try:
            raw = self._t(ticker).get_news(count=50)
        except Exception as exc:
            log.warning("Nachrichten für %s nicht abrufbar: %s", ticker, exc)
            return []
        out = []
        for item in raw or []:
            c = item.get("content", item)
            title = c.get("title") or ""
            summary = c.get("summary") or c.get("description") or ""
            ts = c.get("pubDate") or c.get("displayTime") or item.get("providerPublishTime")
            if isinstance(ts, (int, float)):
                pub = datetime.fromtimestamp(ts)
            elif ts:
                pub = pd.Timestamp(ts).tz_localize(None).to_pydatetime() if pd.Timestamp(ts).tzinfo is None else \
                    pd.Timestamp(ts).tz_convert(None).to_pydatetime()
            else:
                continue
            provider = c.get("provider") or {}
            url = (c.get("canonicalUrl") or {}).get("url") or item.get("link") or ""
            if title and start <= pub <= end:
                out.append(NewsItem(published=pub, headline=title, summary=summary,
                                    source=provider.get("displayName", "") if isinstance(provider, dict) else str(provider),
                                    url=url))
        return out
