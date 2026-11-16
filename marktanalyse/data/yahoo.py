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
from dataclasses import fields
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
    """Summe der letzten 4 Quartale; fehlt genau eines, wird aus den übrigen drei hochgerechnet."""
    vals = [v for v in (_get(df, key, c) for c in cols) if v is not None]
    if len(cols) < 4 or len(vals) < 3:
        return None
    return float(sum(vals) * 4 / len(vals))


def _qgrowth(df: Optional[pd.DataFrame], key: str, col, prev_col, need_positive: bool = False) -> Optional[float]:
    """Wachstum eines Quartals ggü. dem Vorjahresquartal."""
    cur, prev = _get(df, key, col), _get(df, key, prev_col)
    if cur is None or prev is None or prev == 0 or (need_positive and prev < 0):
        return None
    return (cur - prev) / abs(prev)


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

    def _info_dict(self, ticker: str) -> dict:
        try:
            return self._t(ticker).info or {}
        except Exception as exc:
            log.warning("Info für %s nicht abrufbar: %s", ticker, exc)
            return {}

    def info(self, ticker):
        i = self._info_dict(ticker)
        return TickerInfo(
            ticker=ticker,
            name=i.get("longName") or i.get("shortName") or ticker,
            sector=i.get("sector") or "",
            currency=i.get("currency") or "",
            industry=i.get("industry") or "",
        )

    def fundamentals(self, ticker):
        t = self._t(ticker)
        try:
            qi, qb, qc = t.quarterly_income_stmt, t.quarterly_balance_sheet, t.quarterly_cashflow
            ai, ab, ac = t.income_stmt, t.balance_sheet, t.cashflow
        except Exception as exc:
            log.warning("Fundamentaldaten für %s nicht abrufbar: %s", ticker, exc)
            return []
        try:
            ti, tc = t.ttm_income_stmt, t.ttm_cashflow
        except Exception:
            ti = tc = None
        try:
            divs = t.dividends
            divs.index = pd.to_datetime(divs.index).tz_localize(None) if divs.index.tz is not None else divs.index
        except Exception:
            divs = None

        snaps: list[FundamentalSnapshot] = []
        # Jahresabschlüsse (längere Historie)
        if ab is not None and not ab.empty:
            for col in sorted(ab.columns):
                snaps.append(self._snapshot(col, col, ai, ab, ac, None, self.annual_lag_days, divs))
        # Quartale: TTM aus den letzten 4 Quartalen (eine Lücke wird hochgerechnet)
        if qi is not None and not qi.empty and qb is not None and not qb.empty:
            qcols = sorted(qi.columns)
            bcols = sorted(qb.columns)
            for i in range(3, len(qcols)):
                col = qcols[i]
                bal = [b for b in bcols if b <= col and (col - b).days <= 100]
                if not bal:
                    continue
                snap = self._snapshot(col, bal[-1], qi, qb, qc, qcols[i - 3:i + 1], self.report_lag_days, divs,
                                      ttm=(ti, tc))
                yoy = [c for c in qcols[:i] if 330 <= (col - c).days <= 400]
                if yoy and snap is not None:
                    snap.revenue_growth_yoy = _qgrowth(qi, "revenue", col, yoy[-1])
                    snap.eps_growth_yoy = _qgrowth(qi, "eps", col, yoy[-1], need_positive=True)
                snaps.append(snap)
        snaps = [s for s in snaps if s is not None and (s.revenue_ttm is not None or s.net_income_ttm is not None)]
        snaps = self._to_price_currency(ticker, snaps)
        # bei gleichem Verfügbarkeitsdatum den Quartals-Snapshot bevorzugen
        dedup = {}
        for s in sorted(snaps, key=lambda s: s.available_date):
            dedup[s.available_date] = s
        return list(dedup.values())

    def _snapshot(self, col, bal_col, inc, bal, cf, ttm_cols, lag, divs, ttm=(None, None)) -> Optional[FundamentalSnapshot]:
        period_end = pd.Timestamp(col).date()
        cf_keys = ("cfo", "capex", "fcf", "dividends")

        def flow(key):
            src = cf if key in cf_keys else inc
            if ttm_cols is None:
                return _get(src, key, col)
            v = _ttm(src, key, ttm_cols)
            if v is None:  # direkt von Yahoo gelieferte TTM-Werte (nur jüngstes Quartal)
                tsrc = ttm[1] if key in cf_keys else ttm[0]
                if tsrc is not None and not tsrc.empty and col in tsrc.columns:
                    v = _get(tsrc, key, col)
            return v

        shares = _get(bal, "shares", bal_col)
        ni = flow("net_income")
        eps = flow("eps")
        if eps is None and ni is not None and shares:
            eps = ni / shares
        capex = flow("capex")
        dps = None
        if divs is not None:
            pe_ts = pd.Timestamp(period_end)
            dps = float(divs[(divs.index > pe_ts - pd.Timedelta(days=365)) & (divs.index <= pe_ts)].sum())
        elif flow("dividends") is not None and shares:
            dps = abs(flow("dividends")) / shares
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
            dividends_per_share_ttm=dps,
            total_assets=_get(bal, "total_assets", bal_col),
            total_liabilities=_get(bal, "total_liabilities", bal_col),
            total_equity=_get(bal, "equity", bal_col),
            total_debt=_get(bal, "total_debt", bal_col),
            cash=_get(bal, "cash", bal_col),
            current_assets=_get(bal, "current_assets", bal_col),
            current_liabilities=_get(bal, "current_liabilities", bal_col),
            retained_earnings=_get(bal, "retained_earnings", bal_col),
        )

    def _to_price_currency(self, ticker: str, snaps: list[FundamentalSnapshot]) -> list[FundamentalSnapshot]:
        """Rechnet Bilanzwerte in die Kurswährung um (z. B. ADRs mit Abschluss in TWD, Kurs in USD)."""
        i = self._info_dict(ticker)
        fin, px = i.get("financialCurrency"), i.get("currency")
        if not snaps or not fin or not px or fin == px:
            return snaps
        try:
            start = min(s.period_end for s in snaps) - timedelta(days=10)
            fx = self.prices(f"{fin}{px}=X", start, date.today())["close"]
        except Exception as exc:
            log.warning("%s: Wechselkurs %s/%s nicht verfügbar (%s) – Fundamentaldaten verworfen", ticker, fin, px, exc)
            return []
        if fx.empty:
            return []
        money = [f.name for f in fields(FundamentalSnapshot)
                 if f.name not in ("available_date", "period_end", "shares_outstanding", "revenue_growth_yoy", "eps_growth_yoy")]
        for s in snaps:
            # Dividenden kommen bereits in Kurswährung aus der Ausschüttungshistorie
            rate = float(fx.loc[: pd.Timestamp(s.period_end)].iloc[-1]) if not fx.loc[: pd.Timestamp(s.period_end)].empty else float(fx.iloc[0])
            for name in money:
                v = getattr(s, name)
                if v is not None and name != "dividends_per_share_ttm":
                    setattr(s, name, v * rate)
        return snaps

    def market_sentiment(self, ticker):
        t = self._t(ticker)
        i = self._info_dict(ticker)
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

    def earnings_history(self, ticker: str, limit: int = 12) -> pd.DataFrame:
        """Quartalszahlen: Meldezeitpunkt (Index), Schätzung, gemeldeter Gewinn je Aktie, Überraschung in %."""
        ed = self._t(ticker).get_earnings_dates(limit=limit)
        if ed is None or ed.empty:
            return pd.DataFrame(columns=["estimate", "reported", "surprise"])
        ed = ed.rename(columns={"EPS Estimate": "estimate", "Reported EPS": "reported", "Surprise(%)": "surprise"})
        return ed[["estimate", "reported", "surprise"]].dropna(subset=["reported"]).sort_index()

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
