"""Synthetische, reproduzierbare Demo-Daten (fiktive Unternehmen).

Dient zum Ausprobieren ohne Internetzugang und für Tests. Der Demo-Index
durchläuft Bullen-, Bären- und Seitwärtsphasen; die sechs fiktiven Aktien
haben bewusst unterschiedliche Profile (Qualität, Value, Hype, Krise,
Dividende, Zykliker), damit alle Signalarten sichtbar werden.
"""

from __future__ import annotations

import zlib
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from ..models import FundamentalSnapshot, MarketSentimentSnapshot, NewsItem, TickerInfo
from .base import DataProvider, normalize_prices

BENCHMARK = "DEMO-INDEX"
START = date(2017, 1, 2)
END = date(2026, 12, 31)

# (Startdatum, erwartete Jahresrendite, Jahresvolatilität)
INDEX_SEGMENTS = [
    (date(2017, 1, 1), 0.16, 0.14),
    (date(2022, 1, 1), -0.32, 0.26),
    (date(2022, 10, 15), 0.22, 0.15),
    (date(2025, 1, 1), 0.00, 0.14),
    (date(2025, 9, 1), -0.38, 0.30),
    (date(2026, 5, 1), 0.30, 0.17),
]

HYPE_CRASH = date(2025, 6, 2)

PROFILES: dict[str, dict] = {
    "QUALI": dict(name="Demo Qualitätswachstum AG", sector="Technologie", beta=1.0, alpha=0.08, idio=0.20,
                  rev0=20e9, growth=0.15, gm=0.60, om=0.28, nm=0.22, roe=0.28, de=0.3, cr=2.2, cash=0.30,
                  payout=0.20, shares=1.0e9, share_drift=-0.01, cfo=1.25, capex=0.05, pe0=26,
                  rating=1.8, si=0.012, insider=0.15, news=0.5),
    "VALUE": dict(name="Demo Substanzwert AG", sector="Industrie", beta=0.8, alpha=0.03, idio=0.18,
                  rev0=50e9, growth=0.03, gm=0.30, om=0.11, nm=0.08, roe=0.12, de=0.6, cr=1.6, cash=0.10,
                  payout=0.45, shares=2.0e9, share_drift=-0.02, cfo=1.45, capex=0.035, pe0=9,
                  rating=2.4, si=0.02, insider=0.25, news=0.15),
    "HYPE": dict(name="Demo Hype Technologies", sector="Technologie", beta=1.6, alpha=0.55, idio=0.50,
                 rev0=2e9, growth=0.30, gm=0.55, om=0.03, nm=0.02, roe=0.04, de=0.8, cr=1.3, cash=0.20,
                 payout=0.0, shares=0.5e9, share_drift=0.04, cfo=0.6, capex=0.12, pe0=120,
                 rating=2.1, si=0.12, insider=-0.5, news=0.35),
    "PLEITE": dict(name="Demo Krisen AG", sector="Industrie", beta=1.3, alpha=-0.28, idio=0.42,
                   rev0=6e9, growth=-0.10, gm=0.17, om=-0.02, nm=-0.06, roe=-0.10, de=3.0, cr=0.85, cash=0.04,
                   payout=0.0, shares=0.3e9, share_drift=0.05, cfo=1.0, capex=0.04, pe0=None,
                   rating=3.7, si=0.14, insider=-0.3, news=-0.6),
    "DIVI": dict(name="Demo Versorger AG", sector="Versorger", beta=0.5, alpha=0.01, idio=0.12,
                 rev0=30e9, growth=0.02, gm=0.40, om=0.18, nm=0.10, roe=0.10, de=1.2, cr=1.1, cash=0.05,
                 payout=0.75, shares=1.5e9, share_drift=0.0, cfo=1.8, capex=0.12, pe0=16,
                 rating=2.8, si=0.02, insider=0.0, news=0.0),
    "ZYKL": dict(name="Demo Zykliker AG", sector="Industrie", beta=1.4, alpha=0.0, idio=0.28,
                 rev0=15e9, growth=0.05, gm=0.25, om=0.10, nm=0.07, roe=0.14, de=0.9, cr=1.4, cash=0.08,
                 payout=0.30, shares=0.8e9, share_drift=0.0, cfo=1.3, capex=0.06, pe0=12,
                 rating=2.6, si=0.04, insider=0.0, news=0.0),
}

POS_NEWS = [
    "{n} übertrifft Erwartungen im Quartal",
    "{n} hebt Prognose an",
    "Analyst: {n} hochgestuft, Kursziel angehoben",
    "{n} meldet Rekordumsatz",
    "{n} wins major contract",
    "{n} raises guidance on strong demand",
    "{n} announces share buyback",
    "{n} erhält Großauftrag",
]
NEG_NEWS = [
    "{n} verfehlt Erwartungen",
    "Gewinnwarnung bei {n}",
    "{n} herabgestuft – Kursziel gesenkt",
    "Klage gegen {n} eingereicht",
    "{n} cuts guidance amid weak demand",
    "Investigation launched into {n} accounting",
    "{n} kündigt Stellenabbau an",
    "{n} misses estimates, shares tumble",
]
NEUTRAL_NEWS = [
    "{n} lädt zur Hauptversammlung",
    "{n} stellt neuen Finanzvorstand vor",
    "{n} to present at industry conference",
    "{n}: Termin für Quartalszahlen bestätigt",
]


def _seed(key: str) -> int:
    return zlib.crc32(key.encode()) & 0xFFFFFFFF


def _segment(d: date) -> tuple[float, float]:
    mu, vol = INDEX_SEGMENTS[0][1:]
    for start, m, v in INDEX_SEGMENTS:
        if d >= start:
            mu, vol = m, v
    return mu, vol


class SyntheticProvider(DataProvider):
    name = "Demo-Daten (synthetisch)"

    def __init__(self):
        self._days = pd.bdate_range(START, END)
        self._bench_ret = self._make_benchmark_returns()
        self._cache: dict[str, pd.DataFrame] = {}
        self._news_cache: dict[str, list[NewsItem]] = {}

    @staticmethod
    def tickers() -> list[str]:
        return list(PROFILES)

    # ------------------------------------------------------------------ Kurse
    def _make_benchmark_returns(self) -> pd.Series:
        rng = np.random.default_rng(_seed(BENCHMARK))
        rets = []
        for d in self._days:
            mu, vol = _segment(d.date())
            rets.append((mu - 0.5 * vol**2) / 252 + vol / np.sqrt(252) * rng.standard_t(5) * np.sqrt(3 / 5))
        return pd.Series(rets, index=self._days)

    def _alpha(self, ticker: str, d: date) -> float:
        p = PROFILES[ticker]
        if ticker == "HYPE" and d >= HYPE_CRASH:
            return -0.70
        return p["alpha"]

    def _ohlcv(self, key: str, log_ret: pd.Series, start_price: float, base_volume: float) -> pd.DataFrame:
        rng = np.random.default_rng(_seed(key + "-ohlc"))
        close = start_price * np.exp(log_ret.cumsum())
        prev = close.shift(1).fillna(start_price)
        dvol = log_ret.rolling(20, min_periods=1).std().fillna(0.01).clip(lower=0.003)
        open_ = prev * np.exp(rng.normal(0, 0.3, len(close)) * dvol)
        hi = np.maximum(open_, close) * np.exp(np.abs(rng.normal(0, 0.5, len(close))) * dvol)
        lo = np.minimum(open_, close) * np.exp(-np.abs(rng.normal(0, 0.5, len(close))) * dvol)
        vol = base_volume * (1 + 0.4 * np.abs(rng.normal(size=len(close)))) * (1 + 4 * np.abs(log_ret) / dvol.mean())
        return pd.DataFrame({"open": open_, "high": hi, "low": lo, "close": close, "volume": vol}, index=log_ret.index)

    def _series(self, ticker: str) -> pd.DataFrame:
        if ticker in self._cache:
            return self._cache[ticker]
        if ticker == BENCHMARK:
            df = self._ohlcv(ticker, self._bench_ret, 3000.0, 3e9)
        elif ticker in PROFILES:
            p = PROFILES[ticker]
            rng = np.random.default_rng(_seed(ticker))
            idio = rng.standard_t(4, len(self._days)) * np.sqrt(2 / 4) * p["idio"] / np.sqrt(252)
            alpha = np.array([self._alpha(ticker, d.date()) for d in self._days]) / 252
            lr = pd.Series(alpha + p["beta"] * self._bench_ret.to_numpy() + idio - 0.5 * p["idio"] ** 2 / 252,
                           index=self._days)
            eps0 = p["rev0"] * p["nm"] / p["shares"]
            start_price = eps0 * p["pe0"] if p["pe0"] else 25.0
            df = self._ohlcv(ticker, lr, start_price, p["shares"] * 0.004)
        else:
            raise KeyError(f"Unbekannter Demo-Ticker: {ticker}. Verfügbar: {', '.join([BENCHMARK, *PROFILES])}")
        self._cache[ticker] = df
        return df

    def prices(self, ticker, start, end):
        df = self._series(ticker)
        return normalize_prices(df.loc[pd.Timestamp(start):pd.Timestamp(end)])

    def info(self, ticker):
        if ticker == BENCHMARK:
            return TickerInfo(ticker, "Demo-Leitindex", "Index", "EUR")
        p = PROFILES[ticker]
        return TickerInfo(ticker, p["name"], p["sector"], "EUR")

    # ------------------------------------------------------------------ Fundamentaldaten
    def _growth(self, ticker: str, d: date) -> float:
        p = PROFILES[ticker]
        if ticker == "HYPE":
            return 0.35 if d < HYPE_CRASH else -0.05
        if ticker == "ZYKL":
            mu, _ = _segment(d)
            return 0.04 + 0.4 * mu
        return p["growth"]

    def _net_margin(self, ticker: str, d: date, years: float) -> float:
        p = PROFILES[ticker]
        if ticker == "HYPE":
            return 0.03 if d < HYPE_CRASH else -0.06
        if ticker == "PLEITE":
            return p["nm"] - 0.012 * years
        if ticker == "QUALI":
            return p["nm"] + 0.004 * years
        return p["nm"]

    def fundamentals(self, ticker):
        if ticker not in PROFILES:
            return []
        p = PROFILES[ticker]
        rng = np.random.default_rng(_seed(ticker + "-fund"))
        quarters = pd.date_range(START - timedelta(days=400), END, freq="QE")
        out: list[FundamentalSnapshot] = []
        rev = p["rev0"]
        shares = p["shares"]
        nm0 = p["nm"]
        equity = abs(p["rev0"] * nm0) / abs(p["roe"]) if nm0 else p["rev0"] * 0.3
        retained = equity * 0.6
        debt0 = p["de"] * equity
        for q in quarters:
            d = q.date()
            years = (d - START).days / 365.25
            g = self._growth(ticker, d) + rng.normal(0, 0.01)
            rev *= (1 + g) ** 0.25
            shares *= (1 + p["share_drift"]) ** 0.25
            nm = self._net_margin(ticker, d, max(0.0, years)) + rng.normal(0, 0.003)
            om = nm + (p["om"] - p["nm"])
            ni = rev * nm
            equity += ni / 4 * (1 - p["payout"] if ni > 0 else 1)
            retained += ni / 4 * (1 - p["payout"] if ni > 0 else 1)
            debt = debt0 * (rev / p["rev0"]) ** 0.5 if ticker != "PLEITE" else debt0 * (1 + 0.05 * max(0, years))
            cur_liab = 0.20 * rev
            cr = p["cr"] - (0.03 * max(0, years) if ticker == "PLEITE" else 0)
            cur_assets = cr * cur_liab
            cash = min(p["cash"] * rev, cur_assets * 0.8)
            total_liab = debt + 0.25 * rev
            total_assets = max(equity, 0) + total_liab if equity > 0 else total_liab + equity
            cfo = ni * p["cfo"] if ni > 0 else ni + 0.02 * rev
            capex = p["capex"] * rev
            eps = ni / shares
            out.append(FundamentalSnapshot(
                available_date=d + timedelta(days=40),
                period_end=d,
                shares_outstanding=shares,
                eps_ttm=eps,
                revenue_ttm=rev,
                gross_profit_ttm=rev * (p["gm"] + rng.normal(0, 0.003)),
                operating_income_ttm=rev * om,
                net_income_ttm=ni,
                ebitda_ttm=rev * (om + 0.05),
                interest_expense_ttm=debt * 0.045,
                operating_cash_flow_ttm=cfo,
                capex_ttm=capex,
                free_cash_flow_ttm=cfo - capex,
                dividends_per_share_ttm=max(0.0, eps * p["payout"]) if eps > 0 else 0.0,
                total_assets=total_assets,
                total_liabilities=total_liab,
                total_equity=equity,
                total_debt=debt,
                cash=cash,
                current_assets=cur_assets,
                current_liabilities=cur_liab,
                retained_earnings=retained,
            ))
        return out

    # ------------------------------------------------------------------ Erwartungen
    def market_sentiment(self, ticker):
        if ticker not in PROFILES:
            return []
        p = PROFILES[ticker]
        rng = np.random.default_rng(_seed(ticker + "-sent"))
        px = self._series(ticker)["close"]
        funds = self.fundamentals(ticker)
        out = []
        for m in pd.date_range(START, END, freq="MS"):
            d = m.date()
            hist = px.loc[: pd.Timestamp(d)]
            if hist.empty:
                continue
            price = float(hist.iloc[-1])
            ret_3m = float(hist.iloc[-1] / hist.iloc[max(0, len(hist) - 63)] - 1)
            rating = p["rating"] - 0.8 * np.tanh(ret_3m * 2) * 0.5 + rng.normal(0, 0.1)
            si = p["si"] * (1 + rng.normal(0, 0.1))
            insider = p["insider"]
            if ticker == "HYPE" and d >= HYPE_CRASH:
                rating, si, insider = rating + 1.0, 0.22 + rng.normal(0, 0.01), -0.7
            rating = float(np.clip(rating, 1, 5))
            upside = (3 - rating) * 0.10 + rng.normal(0, 0.03)
            avail = [f for f in funds if f.available_date <= d]
            eps_fwd = None
            if avail:
                eps = avail[-1].eps_ttm
                eps_fwd = eps * (1 + self._growth(ticker, d) * (1.3 if ticker == "HYPE" and d < HYPE_CRASH else 1.0)) if eps else None
            next_q = pd.Timestamp(d) + pd.offsets.QuarterEnd(0)
            next_report = (next_q + timedelta(days=40)).date()
            if next_report < d:
                next_report = (next_q + pd.offsets.QuarterEnd(1) + timedelta(days=40)).date()
            out.append(MarketSentimentSnapshot(
                available_date=d,
                analyst_rating=rating,
                analyst_count=int(8 + rng.integers(0, 15)),
                target_price=price * (1 + upside),
                eps_forward=eps_fwd,
                short_interest_pct=max(0.0, si),
                days_to_cover=max(0.5, si * 30),
                insider_net_buying=float(np.clip(insider + rng.normal(0, 0.15), -1, 1)),
                next_earnings_date=next_report,
            ))
        return out

    # ------------------------------------------------------------------ Nachrichten
    def _all_news(self, ticker: str) -> list[NewsItem]:
        if ticker in self._news_cache:
            return self._news_cache[ticker]
        if ticker not in PROFILES:
            return []
        p = PROFILES[ticker]
        rng = np.random.default_rng(_seed(ticker + "-news"))
        px = self._series(ticker)["close"]
        ret20 = px.pct_change(20).fillna(0)
        items = []
        for ts in px.index:
            if rng.random() > 0.3:  # ~1,5 Meldungen pro Woche
                continue
            bias = p["news"]
            if ticker == "HYPE":
                bias = 0.4 if ts.date() < HYPE_CRASH else -0.7
            z = 2.0 * bias + 6.0 * float(ret20.loc[ts])
            p_pos = 1 / (1 + np.exp(-z))
            u = rng.random()
            if u < 0.2:
                tmpl = NEUTRAL_NEWS[rng.integers(len(NEUTRAL_NEWS))]
            elif rng.random() < p_pos:
                tmpl = POS_NEWS[rng.integers(len(POS_NEWS))]
            else:
                tmpl = NEG_NEWS[rng.integers(len(NEG_NEWS))]
            if ticker == "PLEITE" and rng.random() < 0.15:
                tmpl = "Sorge vor Insolvenz bei {n}"
            items.append(NewsItem(
                published=datetime.combine(ts.date(), datetime.min.time()) + timedelta(hours=int(rng.integers(7, 20))),
                headline=tmpl.format(n=p["name"]),
                source="Demo-Newsfeed",
            ))
        self._news_cache[ticker] = items
        return items

    def news(self, ticker, start, end):
        return [n for n in self._all_news(ticker) if start <= n.published <= end]


def demo_dates() -> dict[str, date]:
    """Beispielzeitpunkte für die Demo (Marktphasen des Demo-Index)."""
    return {
        "Bullenmarkt": date(2024, 6, 28),
        "Seitwärtsmarkt": date(2025, 7, 31),
        "Bärenmarkt": date(2026, 3, 31),
    }
