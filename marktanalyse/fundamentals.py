"""Fundamentale Kennzahlen: Bewertung, Qualität, Bilanz, Wachstum, Scores."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from .models import FundamentalSnapshot, MarketSentimentSnapshot


def _div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _growth(cur: Optional[float], prev: Optional[float]) -> Optional[float]:
    if cur is None or prev is None or prev == 0:
        return None
    return (cur - prev) / abs(prev)


@dataclass
class FundamentalMetrics:
    market_cap: Optional[float] = None
    enterprise_value: Optional[float] = None
    pe: Optional[float] = None  # KGV (TTM)
    forward_pe: Optional[float] = None
    peg: Optional[float] = None
    pb: Optional[float] = None  # KBV
    ps: Optional[float] = None  # KUV
    ev_ebitda: Optional[float] = None
    fcf_yield: Optional[float] = None
    earnings_yield: Optional[float] = None
    dividend_yield: Optional[float] = None
    payout_ratio: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    debt_to_equity: Optional[float] = None
    net_debt_to_ebitda: Optional[float] = None
    current_ratio: Optional[float] = None
    interest_coverage: Optional[float] = None
    revenue_growth: Optional[float] = None
    eps_growth: Optional[float] = None
    operating_margin_change: Optional[float] = None
    piotroski: Optional[int] = None
    altman_z: Optional[float] = None
    eps_ttm: Optional[float] = None
    eps_negative: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def piotroski_f_score(cur: FundamentalSnapshot, prev: FundamentalSnapshot) -> Optional[int]:
    """Piotroski F-Score (0..9). Benötigt aktuelle und Vorjahreszahlen."""
    roa = _div(cur.net_income_ttm, cur.total_assets)
    roa_prev = _div(prev.net_income_ttm, prev.total_assets)
    cfo = cur.operating_cash_flow_ttm
    lev = _div(cur.total_debt, cur.total_assets)
    lev_prev = _div(prev.total_debt, prev.total_assets)
    cr = _div(cur.current_assets, cur.current_liabilities)
    cr_prev = _div(prev.current_assets, prev.current_liabilities)
    gm = _div(cur.gross_profit_ttm, cur.revenue_ttm)
    gm_prev = _div(prev.gross_profit_ttm, prev.revenue_ttm)
    at = _div(cur.revenue_ttm, cur.total_assets)
    at_prev = _div(prev.revenue_ttm, prev.total_assets)

    tests = [
        (roa, lambda: roa > 0),
        (cfo, lambda: cfo > 0),
        (roa is not None and roa_prev is not None or None, lambda: roa > roa_prev),
        (cfo is not None and cur.net_income_ttm is not None or None, lambda: cfo > cur.net_income_ttm),
        (lev is not None and lev_prev is not None or None, lambda: lev <= lev_prev),
        (cr is not None and cr_prev is not None or None, lambda: cr > cr_prev),
        (cur.shares_outstanding is not None and prev.shares_outstanding is not None or None,
         lambda: cur.shares_outstanding <= prev.shares_outstanding * 1.005),
        (gm is not None and gm_prev is not None or None, lambda: gm > gm_prev),
        (at is not None and at_prev is not None or None, lambda: at > at_prev),
    ]
    available = [t for t in tests if t[0] is not None]
    if len(available) < 7:
        return None
    passed = sum(1 for _, check in available if check())
    # fehlende Kriterien anteilig hochrechnen
    return int(round(passed * 9 / len(available)))


def altman_z_score(snap: FundamentalSnapshot, market_cap: Optional[float]) -> Optional[float]:
    """Altman Z-Score (Originalformel). < 1.81 Insolvenzgefahr, > 2.99 sicher."""
    ta = snap.total_assets
    if not ta or market_cap is None or not snap.total_liabilities:
        return None
    parts = [
        (snap.current_assets, snap.current_liabilities),
        (snap.retained_earnings,),
        (snap.operating_income_ttm,),
        (snap.revenue_ttm,),
    ]
    if any(v is None for group in parts for v in group):
        return None
    wc = snap.current_assets - snap.current_liabilities
    return (
        1.2 * wc / ta
        + 1.4 * snap.retained_earnings / ta
        + 3.3 * snap.operating_income_ttm / ta
        + 0.6 * market_cap / snap.total_liabilities
        + 1.0 * snap.revenue_ttm / ta
    )


def compute_fundamentals(
    price: float,
    cur: Optional[FundamentalSnapshot],
    prev: Optional[FundamentalSnapshot] = None,
    expectations: Optional[MarketSentimentSnapshot] = None,
) -> FundamentalMetrics:
    m = FundamentalMetrics()
    if cur is None:
        return m

    shares = cur.shares_outstanding
    eps = cur.eps_ttm
    if eps is None:
        eps = _div(cur.net_income_ttm, shares)
    m.eps_ttm = eps
    m.market_cap = price * shares if shares else None
    mc = m.market_cap

    if mc is not None and cur.total_debt is not None and cur.cash is not None:
        m.enterprise_value = mc + cur.total_debt - cur.cash

    if eps is not None:
        m.eps_negative = eps <= 0
        m.pe = price / eps if eps > 0 else None
        m.earnings_yield = eps / price if price else None
    if expectations is not None and expectations.eps_forward and expectations.eps_forward > 0:
        m.forward_pe = price / expectations.eps_forward

    m.pb = _div(mc, cur.total_equity) if cur.total_equity and cur.total_equity > 0 else None
    m.ps = _div(mc, cur.revenue_ttm)
    if m.enterprise_value is not None and cur.ebitda_ttm and cur.ebitda_ttm > 0:
        m.ev_ebitda = m.enterprise_value / cur.ebitda_ttm

    fcf = cur.free_cash_flow_ttm
    if fcf is None and cur.operating_cash_flow_ttm is not None and cur.capex_ttm is not None:
        fcf = cur.operating_cash_flow_ttm - abs(cur.capex_ttm)
    m.fcf_yield = _div(fcf, mc)

    if cur.dividends_per_share_ttm is not None and price:
        m.dividend_yield = cur.dividends_per_share_ttm / price
        if eps and eps > 0:
            m.payout_ratio = cur.dividends_per_share_ttm / eps

    if cur.total_equity and cur.total_equity > 0:
        m.roe = _div(cur.net_income_ttm, cur.total_equity)
        m.debt_to_equity = _div(cur.total_debt, cur.total_equity)
    elif cur.total_equity is not None and cur.total_equity <= 0:
        m.debt_to_equity = 99.0  # negatives Eigenkapital
    m.roa = _div(cur.net_income_ttm, cur.total_assets)
    m.gross_margin = _div(cur.gross_profit_ttm, cur.revenue_ttm)
    m.operating_margin = _div(cur.operating_income_ttm, cur.revenue_ttm)
    m.net_margin = _div(cur.net_income_ttm, cur.revenue_ttm)
    if cur.total_debt is not None and cur.cash is not None and cur.ebitda_ttm:
        nd = cur.total_debt - cur.cash
        m.net_debt_to_ebitda = nd / cur.ebitda_ttm if cur.ebitda_ttm > 0 else 99.0
    m.current_ratio = _div(cur.current_assets, cur.current_liabilities)
    if cur.interest_expense_ttm:
        m.interest_coverage = _div(cur.operating_income_ttm, abs(cur.interest_expense_ttm))

    if prev is not None:
        m.revenue_growth = _growth(cur.revenue_ttm, prev.revenue_ttm)
        prev_eps = prev.eps_ttm if prev.eps_ttm is not None else _div(prev.net_income_ttm, prev.shares_outstanding)
        m.eps_growth = _growth(eps, prev_eps)
        prev_om = _div(prev.operating_income_ttm, prev.revenue_ttm)
        if m.operating_margin is not None and prev_om is not None:
            m.operating_margin_change = m.operating_margin - prev_om
        m.piotroski = piotroski_f_score(cur, prev)

    if m.pe is not None and m.eps_growth is not None and m.eps_growth > 0:
        m.peg = m.pe / (m.eps_growth * 100)
    m.altman_z = altman_z_score(cur, mc)
    return m
