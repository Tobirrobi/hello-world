"""Signalkatalog: Jede Regel bewertet eine Kennzahl mit einem Score von -1 bis +1.

+1 = starkes Argument für eine Long-Position (Kauf),
-1 = starkes Argument für eine Short-Position (Leerverkauf / Verkauf).

Neue Regeln werden mit dem Dekorator ``@rule`` registriert und tauchen
automatisch in Analyse, Report und Kennzahlen-Katalog auf.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable, Optional

import numpy as np

from .config import Config
from .fundamentals import FundamentalMetrics
from .indicators import TechnicalSnapshot
from .models import MarketRegime, MarketSentimentSnapshot, Regime, Signal, TickerInfo
from .sentiment import NewsSentiment


# --------------------------------------------------------------------------- Hilfen
def interp(x: float, points: list[tuple[float, float]]) -> float:
    """Stückweise lineare Abbildung Kennzahl -> Score, an den Rändern gekappt."""
    xs, ys = zip(*points)
    return float(np.clip(np.interp(x, xs, ys), -1.0, 1.0))


def pct(x: Optional[float], digits: int = 1) -> str:
    return "–" if x is None else f"{x * 100:.{digits}f} %"


def num(x: Optional[float], digits: int = 1) -> str:
    return "–" if x is None else f"{x:.{digits}f}"


def money(x: Optional[float]) -> str:
    if x is None:
        return "–"
    for div, unit in ((1e12, "Bio."), (1e9, "Mrd."), (1e6, "Mio.")):
        if abs(x) >= div:
            return f"{x / div:.1f} {unit}"
    return f"{x:,.0f}"


def size_class(market_cap: Optional[float]) -> Optional[str]:
    if market_cap is None:
        return None
    if market_cap >= 200e9:
        return "Mega Cap"
    if market_cap >= 10e9:
        return "Large Cap"
    if market_cap >= 2e9:
        return "Mid Cap"
    if market_cap >= 300e6:
        return "Small Cap"
    return "Micro Cap"


def band(score: float, pos: str, neg: str, neutral: str = "neutral") -> str:
    if score >= 0.25:
        return pos
    if score <= -0.25:
        return neg
    return neutral


FINANCIAL_KEYWORDS = ("bank", "insurance", "reinsurance", "capital markets", "mortgage", "versicher", "banken")
# Kennzahlen, die für Banken/Versicherer nicht aussagekräftig sind (Bilanzstruktur, Cashflow-Definition)
FINANCIAL_SKIP = {"fcf_rendite", "ev_ebitda", "kuv", "verschuldung", "nettoverschuldung", "liquiditaet",
                  "zinsdeckung", "altman_z", "marge", "marge_trend"}


def is_financial(info: TickerInfo) -> bool:
    text = f"{info.industry} {'' if info.industry else info.sector}".lower()
    return any(k in text for k in FINANCIAL_KEYWORDS) or (not info.industry and "financ" in text)


# --------------------------------------------------------------------------- Kontext
@dataclass
class SignalContext:
    as_of: date
    info: TickerInfo
    tech: TechnicalSnapshot
    fund: FundamentalMetrics
    news: Optional[NewsSentiment]
    expectations: Optional[MarketSentimentSnapshot]
    regime: MarketRegime
    config: Config

    @property
    def uptrend(self) -> Optional[bool]:
        if self.tech.sma200 is None:
            return None
        return self.tech.close > self.tech.sma200


RuleResult = Optional[tuple[float, Optional[float], str, str]]  # score, value, value_fmt, rationale


@dataclass
class RuleSpec:
    key: str
    name: str
    category: str
    weight: float
    long_case: str
    short_case: str
    fn: Callable[[SignalContext], RuleResult]


RULES: list[RuleSpec] = []


def rule(key: str, name: str, category: str, weight: float, long_case: str, short_case: str):
    def deco(fn):
        RULES.append(RuleSpec(key, name, category, weight, long_case, short_case, fn))
        return fn

    return deco


# =========================================================================== BEWERTUNG
@rule("kgv", "KGV (Kurs-Gewinn-Verhältnis)", "bewertung", 1.5,
      "niedriges KGV (< 15) bei stabilen Gewinnen", "sehr hohes KGV (> 35) oder Verluste")
def _kgv(c: SignalContext) -> RuleResult:
    f = c.fund
    if f.eps_negative:
        return -0.6, None, "negativ", "Unternehmen schreibt Verluste – kein sinnvolles KGV"
    if f.pe is None:
        return None
    s = interp(f.pe, [(5, 0.6), (10, 0.8), (15, 0.5), (20, 0.1), (25, -0.1), (35, -0.4), (60, -0.8)])
    txt = band(s, "günstig bewertet", "teuer bewertet", "fair bewertet")
    if f.pe < 6:
        txt += " (Achtung: sehr niedriges KGV kann auf eine Value-Falle hindeuten)"
    return s, f.pe, num(f.pe), f"KGV {f.pe:.1f} – {txt}"


@rule("forward_kgv", "Forward-KGV vs. KGV", "bewertung", 0.8,
      "Forward-KGV deutlich unter KGV (Gewinne sollen steigen)", "Forward-KGV über KGV (Gewinnrückgang erwartet)")
def _fwd_kgv(c: SignalContext) -> RuleResult:
    f = c.fund
    if f.forward_pe is None:
        return None
    if f.pe is None:
        if f.eps_negative:
            return 0.3, f.forward_pe, num(f.forward_pe), "Rückkehr in die Gewinnzone erwartet"
        return None
    ratio = f.forward_pe / f.pe
    s = interp(ratio, [(0.6, 0.8), (0.85, 0.4), (1.0, 0.0), (1.15, -0.5), (1.4, -0.8)])
    return s, f.forward_pe, num(f.forward_pe), (
        f"Forward-KGV {f.forward_pe:.1f} vs. KGV {f.pe:.1f} – "
        + band(s, "Analysten erwarten Gewinnwachstum", "Analysten erwarten Gewinnrückgang", "stabile Gewinnerwartung")
    )


@rule("peg", "PEG-Ratio (KGV / Gewinnwachstum)", "bewertung", 1.0,
      "PEG < 1: Wachstum günstig zu haben", "PEG > 2,5: Wachstum teuer bezahlt")
def _peg(c: SignalContext) -> RuleResult:
    p = c.fund.peg
    if p is None:
        return None
    s = interp(p, [(0.5, 0.8), (1.0, 0.4), (1.5, 0.0), (2.5, -0.5), (4.0, -0.8)])
    return s, p, num(p, 2), f"PEG {p:.2f} – " + band(s, "Wachstum günstig bewertet", "Wachstum teuer bezahlt")


@rule("kbv", "KBV (Kurs-Buchwert-Verhältnis)", "bewertung", 0.6,
      "KBV < 1 bei positiver Eigenkapitalrendite", "sehr hohes KBV ohne hohe Rendite")
def _kbv(c: SignalContext) -> RuleResult:
    f = c.fund
    if f.pb is None:
        return None
    s = interp(f.pb, [(0.7, 0.6), (1.0, 0.4), (2.0, 0.1), (4.0, -0.2), (8.0, -0.5)])
    note = ""
    if f.roe is not None and f.roe > 0.20 and s < 0:
        s, note = max(s, -0.1), " (gerechtfertigt durch hohe Eigenkapitalrendite)"
    if f.roe is not None and f.roe < 0 and s > 0:
        s, note = 0.0, " (aber negative Eigenkapitalrendite – mögliche Value-Falle)"
    return s, f.pb, num(f.pb, 2), f"KBV {f.pb:.2f}{note}"


@rule("kuv", "KUV (Kurs-Umsatz-Verhältnis)", "bewertung", 0.6,
      "KUV < 1", "KUV > 8 (hohe Erwartungen eingepreist)")
def _kuv(c: SignalContext) -> RuleResult:
    p = c.fund.ps
    if p is None:
        return None
    s = interp(p, [(0.5, 0.6), (1.0, 0.4), (3.0, 0.0), (8.0, -0.5), (15.0, -0.8)])
    return s, p, num(p, 2), f"KUV {p:.2f} – " + band(s, "Umsatz günstig bewertet", "sehr hohe Umsatzbewertung")


@rule("ev_ebitda", "EV/EBITDA", "bewertung", 1.0,
      "EV/EBITDA < 8 (inkl. Schulden günstig)", "EV/EBITDA > 18")
def _ev_ebitda(c: SignalContext) -> RuleResult:
    v = c.fund.ev_ebitda
    if v is None:
        return None
    s = interp(v, [(5, 0.7), (8, 0.4), (12, 0.0), (18, -0.4), (30, -0.8)])
    return s, v, num(v), f"EV/EBITDA {v:.1f} – " + band(s, "günstig inkl. Verschuldung", "teuer inkl. Verschuldung")


@rule("fcf_rendite", "Free-Cashflow-Rendite", "bewertung", 1.2,
      "FCF-Rendite > 5 %: Unternehmen erwirtschaftet viel Geld", "negativer Free Cashflow: verbrennt Geld")
def _fcf(c: SignalContext) -> RuleResult:
    y = c.fund.fcf_yield
    if y is None:
        return None
    s = interp(y, [(-0.05, -0.8), (0.0, -0.4), (0.02, 0.0), (0.05, 0.4), (0.08, 0.7), (0.12, 0.8)])
    txt = "verbrennt Geld" if y < 0 else band(s, "hoher Cash-Zufluss", "geringer Cash-Zufluss")
    return s, y, pct(y), f"FCF-Rendite {pct(y)} – {txt}"


@rule("dividende", "Dividendenrendite & Ausschüttungsquote", "bewertung", 0.5,
      "solide Dividende (2–7 %) mit Ausschüttungsquote < 80 %", "Ausschüttung > Gewinn oder Rendite > 10 % (Kürzungsgefahr)")
def _div(c: SignalContext) -> RuleResult:
    f = c.fund
    y = f.dividend_yield
    if not y:
        return None
    if f.payout_ratio is not None and f.payout_ratio > 1.0:
        return -0.4, y, pct(y), f"Dividende {pct(y)}, aber Ausschüttungsquote {pct(f.payout_ratio, 0)} – nicht verdient, Kürzungsgefahr"
    s = interp(y, [(0.0, 0.0), (0.02, 0.2), (0.04, 0.4), (0.07, 0.3), (0.10, -0.3)])
    return s, y, pct(y), f"Dividendenrendite {pct(y)}" + (
        f", Ausschüttungsquote {pct(f.payout_ratio, 0)}" if f.payout_ratio is not None else "")


# =========================================================================== QUALITÄT
@rule("roe", "Eigenkapitalrendite (ROE)", "qualitaet", 1.0,
      "ROE > 15 %: profitables Geschäftsmodell", "negative oder sehr niedrige ROE")
def _roe(c: SignalContext) -> RuleResult:
    r = c.fund.roe
    if r is None:
        return None
    s = interp(r, [(-0.10, -0.8), (0.0, -0.4), (0.08, 0.0), (0.15, 0.4), (0.25, 0.7)])
    return s, r, pct(r), f"ROE {pct(r)} – " + band(s, "hohe Profitabilität", "schwache Profitabilität")


@rule("marge", "Operative Marge", "qualitaet", 0.6,
      "operative Marge > 15 %", "operative Verluste")
def _margin(c: SignalContext) -> RuleResult:
    m = c.fund.operating_margin
    if m is None:
        return None
    s = interp(m, [(-0.10, -0.7), (0.0, -0.3), (0.08, 0.0), (0.15, 0.3), (0.25, 0.6)])
    return s, m, pct(m), f"Operative Marge {pct(m)}"


@rule("marge_trend", "Margenentwicklung (ggü. Vorjahr)", "qualitaet", 0.6,
      "steigende Margen (Preissetzungsmacht)", "fallende Margen (Wettbewerbs-/Kostendruck)")
def _margin_trend(c: SignalContext) -> RuleResult:
    d = c.fund.operating_margin_change
    if d is None:
        return None
    s = interp(d, [(-0.05, -0.6), (-0.01, -0.1), (0.01, 0.1), (0.05, 0.6)])
    return s, d, f"{d * 100:+.1f} Pp", f"Operative Marge {d * 100:+.1f} Prozentpunkte ggü. Vorjahr"


@rule("verschuldung", "Verschuldungsgrad (Debt/Equity)", "qualitaet", 0.7,
      "geringe Verschuldung (< 0,5)", "hohe Verschuldung (> 2) oder negatives Eigenkapital")
def _de(c: SignalContext) -> RuleResult:
    d = c.fund.debt_to_equity
    if d is None:
        return None
    if d >= 99:
        return -0.8, None, "neg. EK", "Negatives Eigenkapital – bilanziell überschuldet"
    s = interp(d, [(0.3, 0.4), (0.8, 0.1), (1.5, -0.2), (3.0, -0.7)])
    return s, d, num(d, 2), f"Debt/Equity {d:.2f}"


@rule("nettoverschuldung", "Nettoverschuldung / EBITDA", "qualitaet", 0.8,
      "Netto-Cash oder < 1x EBITDA", "> 4x EBITDA: Refinanzierungsrisiko")
def _nd(c: SignalContext) -> RuleResult:
    v = c.fund.net_debt_to_ebitda
    if v is None:
        return None
    if v >= 99:
        return -0.8, None, "EBITDA ≤ 0", "Schulden bei negativem EBITDA – hohes Finanzierungsrisiko"
    s = interp(v, [(-1.0, 0.5), (1.0, 0.3), (2.5, 0.0), (4.0, -0.5), (6.0, -0.8)])
    return s, v, f"{v:.1f}x", f"Nettoverschuldung {v:.1f}x EBITDA" + (" (Netto-Cash)" if v < 0 else "")


@rule("liquiditaet", "Current Ratio (Liquidität 2. Grades)", "qualitaet", 0.4,
      "Current Ratio > 1,5", "Current Ratio < 1 (kurzfristige Zahlungsengpässe möglich)")
def _cr(c: SignalContext) -> RuleResult:
    v = c.fund.current_ratio
    if v is None:
        return None
    s = interp(v, [(0.7, -0.6), (1.0, -0.2), (1.5, 0.2), (2.5, 0.3)])
    return s, v, num(v, 2), f"Current Ratio {v:.2f}"


@rule("zinsdeckung", "Zinsdeckungsgrad (EBIT / Zinsen)", "qualitaet", 0.5,
      "Zinsen > 6-fach durch EBIT gedeckt", "Zinsen kaum gedeckt (< 2x)")
def _ic(c: SignalContext) -> RuleResult:
    v = c.fund.interest_coverage
    if v is None:
        return None
    s = interp(v, [(1.0, -0.8), (3.0, -0.2), (6.0, 0.2), (15.0, 0.4)])
    return s, v, f"{v:.1f}x", f"Zinsdeckung {v:.1f}x"


@rule("piotroski", "Piotroski F-Score (0–9)", "qualitaet", 1.2,
      "F-Score ≥ 7: sich verbessernde Fundamentaldaten", "F-Score ≤ 3: sich verschlechternde Fundamentaldaten")
def _pio(c: SignalContext) -> RuleResult:
    v = c.fund.piotroski
    if v is None:
        return None
    s = interp(v, [(1, -0.8), (3, -0.4), (5, 0.0), (7, 0.5), (9, 0.8)])
    return s, float(v), f"{v}/9", f"Piotroski F-Score {v}/9 – " + band(s, "Fundamentaldaten verbessern sich", "Fundamentaldaten verschlechtern sich")


@rule("altman_z", "Altman Z-Score (Insolvenzrisiko)", "qualitaet", 1.0,
      "Z > 3: finanziell solide", "Z < 1,8: erhöhtes Insolvenzrisiko")
def _altman(c: SignalContext) -> RuleResult:
    z = c.fund.altman_z
    if z is None:
        return None
    s = interp(z, [(1.0, -0.9), (1.81, -0.5), (2.99, 0.2), (5.0, 0.4)])
    zone = "Gefahrenzone" if z < 1.81 else ("Grauzone" if z < 2.99 else "sichere Zone")
    return s, z, num(z, 2), f"Altman Z {z:.2f} – {zone}"


# =========================================================================== WACHSTUM
@rule("umsatzwachstum", "Umsatzwachstum (ggü. Vorjahr)", "wachstum", 1.0,
      "Umsatzwachstum > 10 %", "schrumpfender Umsatz")
def _rev_g(c: SignalContext) -> RuleResult:
    g = c.fund.revenue_growth
    if g is None:
        return None
    s = interp(g, [(-0.15, -0.8), (-0.02, -0.4), (0.03, 0.0), (0.10, 0.4), (0.25, 0.8)])
    return s, g, pct(g), f"Umsatz {g * 100:+.1f} % ggü. Vorjahr"


@rule("gewinnwachstum", "Gewinnwachstum je Aktie (EPS)", "wachstum", 1.0,
      "EPS-Wachstum > 10 %", "fallende Gewinne je Aktie")
def _eps_g(c: SignalContext) -> RuleResult:
    g = c.fund.eps_growth
    if g is None:
        return None
    s = interp(g, [(-0.4, -0.8), (-0.1, -0.4), (0.0, -0.1), (0.10, 0.3), (0.30, 0.7)])
    return s, g, pct(g), f"Gewinn je Aktie {g * 100:+.1f} % ggü. Vorjahr"


# =========================================================================== TREND
@rule("sma200", "Kurs vs. 200-Tage-Linie", "trend", 1.3,
      "Kurs über steigender 200-Tage-Linie (langfristiger Aufwärtstrend)", "Kurs unter 200-Tage-Linie (Abwärtstrend)")
def _sma200(c: SignalContext) -> RuleResult:
    t = c.tech
    if t.sma200 is None:
        return None
    d = t.close / t.sma200 - 1
    s = interp(d, [(-0.20, -0.9), (-0.05, -0.5), (0.0, -0.1), (0.0001, 0.1), (0.05, 0.5), (0.20, 0.7), (0.45, 0.3)])
    txt = "über" if d > 0 else "unter"
    extra = " – stark überdehnt, Rückschlaggefahr" if d > 0.35 else ""
    return s, d, pct(d), f"Kurs {pct(abs(d))} {txt} der 200-Tage-Linie{extra}"


@rule("golden_cross", "Golden Cross / Death Cross (SMA50 vs. SMA200)", "trend", 1.0,
      "SMA50 kreuzt SMA200 nach oben (Golden Cross)", "SMA50 kreuzt SMA200 nach unten (Death Cross)")
def _cross(c: SignalContext) -> RuleResult:
    t = c.tech
    if t.cross_state is None or t.cross_state == 0:
        return None
    fresh = t.days_since_cross is not None and t.days_since_cross <= 20
    if t.cross_state > 0:
        s = 0.8 if fresh else 0.4
        txt = f"Golden Cross vor {t.days_since_cross} Tagen" if fresh else "SMA50 liegt über SMA200"
    else:
        s = -0.8 if fresh else -0.4
        txt = f"Death Cross vor {t.days_since_cross} Tagen" if fresh else "SMA50 liegt unter SMA200"
    return s, float(t.cross_state), "↑" if t.cross_state > 0 else "↓", txt


@rule("sma200_steigung", "Steigung der 200-Tage-Linie", "trend", 0.6,
      "steigende 200-Tage-Linie", "fallende 200-Tage-Linie")
def _slope(c: SignalContext) -> RuleResult:
    v = c.tech.sma200_slope
    if v is None:
        return None
    s = interp(v, [(-0.03, -0.7), (-0.005, -0.2), (0.005, 0.2), (0.03, 0.7)])
    return s, v, pct(v, 2), f"200-Tage-Linie {v * 100:+.2f} % in 20 Tagen"


@rule("macd", "MACD-Histogramm", "trend", 0.7,
      "MACD dreht über Signallinie", "MACD fällt unter Signallinie")
def _macd(c: SignalContext) -> RuleResult:
    h, hp = c.tech.macd_hist, c.tech.macd_hist_prev
    if h is None or hp is None:
        return None
    if h > 0 >= hp:
        return 0.7, h, num(h, 3), "MACD hat die Signallinie frisch nach oben gekreuzt (Kaufsignal)"
    if h < 0 <= hp:
        return -0.7, h, num(h, 3), "MACD hat die Signallinie frisch nach unten gekreuzt (Verkaufssignal)"
    if h > 0:
        return (0.5 if h > hp else 0.15), h, num(h, 3), "MACD positiv" + (" und steigend" if h > hp else ", Dynamik lässt nach")
    return (-0.5 if h < hp else -0.15), h, num(h, 3), "MACD negativ" + (" und fallend" if h < hp else ", Abwärtsdynamik lässt nach")


# =========================================================================== MOMENTUM
@rule("momentum_12_1", "12-Monats-Momentum (ohne letzten Monat)", "momentum", 1.3,
      "starke 12-Monats-Performance (Gewinner bleiben oft Gewinner)", "schwache 12-Monats-Performance")
def _mom(c: SignalContext) -> RuleResult:
    m = c.tech.mom_12_1
    if m is None:
        return None
    s = interp(m, [(-0.4, -0.9), (-0.15, -0.5), (0.0, -0.1), (0.15, 0.4), (0.4, 0.8), (1.0, 0.6)])
    return s, m, pct(m), f"Momentum 12-1: {m * 100:+.1f} %"


@rule("rendite_3m", "3-Monats-Rendite", "momentum", 0.7,
      "positive mittelfristige Dynamik", "negative mittelfristige Dynamik")
def _r3m(c: SignalContext) -> RuleResult:
    r = c.tech.ret_3m
    if r is None:
        return None
    s = interp(r, [(-0.25, -0.7), (-0.08, -0.3), (0.08, 0.3), (0.25, 0.7)])
    return s, r, pct(r), f"3-Monats-Rendite {r * 100:+.1f} %"


@rule("relative_staerke", "Relative Stärke vs. Index (6 Monate)", "momentum", 1.0,
      "Aktie schlägt den Markt", "Aktie läuft schlechter als der Markt")
def _rs(c: SignalContext) -> RuleResult:
    r = c.tech.rel_strength_6m
    if r is None:
        return None
    s = interp(r, [(-0.25, -0.8), (-0.08, -0.3), (0.08, 0.3), (0.25, 0.8)])
    return s, r, f"{r * 100:+.1f} Pp", f"6M-Performance {r * 100:+.1f} Prozentpunkte vs. Index"


@rule("hoch_52w", "Abstand zum 52-Wochen-Hoch", "momentum", 0.6,
      "nahe am 52-Wochen-Hoch (Ausbruchsstärke)", "weit unter dem 52-Wochen-Hoch")
def _high(c: SignalContext) -> RuleResult:
    d = c.tech.dist_52w_high
    if d is None:
        return None
    s = interp(d, [(-0.5, -0.6), (-0.3, -0.3), (-0.15, 0.0), (-0.05, 0.3), (0.0, 0.5)])
    return s, d, pct(d), f"{pct(abs(d))} unter dem 52-Wochen-Hoch"


@rule("volumen", "Volumen / On-Balance-Volume", "momentum", 0.6,
      "steigende Kurse mit hohem Volumen (Akkumulation)", "fallende Kurse mit hohem Volumen (Distribution)")
def _volume(c: SignalContext) -> RuleResult:
    t = c.tech
    if t.obv_slope is None:
        return None
    s = interp(t.obv_slope, [(-0.5, -0.5), (-0.1, -0.1), (0.1, 0.1), (0.5, 0.5)])
    txt = "Kaufdruck (OBV steigt)" if s > 0.1 else ("Verkaufsdruck (OBV fällt)" if s < -0.1 else "ausgeglichenes Volumen")
    if t.volume_ratio and t.volume_ratio > 2 and t.ret_1m is not None:
        if t.ret_1m < -0.10:
            s, txt = min(s, -0.5), f"Abverkauf mit {t.volume_ratio:.1f}-fachem Volumen"
        elif t.ret_1m > 0.10:
            s, txt = max(s, 0.5), f"Ausbruch mit {t.volume_ratio:.1f}-fachem Volumen"
    return s, t.obv_slope, num(t.obv_slope, 2), txt


# =========================================================================== OSZILLATOREN
@rule("rsi", "RSI (14 Tage)", "oszillator", 1.0,
      "RSI < 30 im Aufwärtstrend (Rücksetzer kaufen)", "RSI > 70 im Abwärtstrend (Erholung shorten)")
def _rsi(c: SignalContext) -> RuleResult:
    r = c.tech.rsi14
    if r is None:
        return None
    up = c.uptrend
    if r < 30:
        if up:
            return 0.7, r, num(r, 0), f"RSI {r:.0f}: überverkauft im Aufwärtstrend – Kaufgelegenheit (Buy the Dip)"
        return 0.2, r, num(r, 0), f"RSI {r:.0f}: überverkauft, aber im Abwärtstrend – Vorsicht, fallendes Messer"
    if r > 70:
        if up is False:
            return -0.7, r, num(r, 0), f"RSI {r:.0f}: überkauft im Abwärtstrend – Erholung bietet Short-Einstieg"
        return -0.25, r, num(r, 0), f"RSI {r:.0f}: überkauft – kurzfristiger Rücksetzer möglich, Trend intakt"
    if up and r < 40:
        return 0.3, r, num(r, 0), f"RSI {r:.0f}: Rücksetzer im Aufwärtstrend"
    if up is False and r > 60:
        return -0.3, r, num(r, 0), f"RSI {r:.0f}: Erholung im Abwärtstrend"
    return -(r - 50) / 100, r, num(r, 0), f"RSI {r:.0f}: neutral"


@rule("bollinger", "Bollinger-Bänder (%B)", "oszillator", 0.5,
      "Kurs am/unter dem unteren Band", "Kurs am/über dem oberen Band")
def _bb(c: SignalContext) -> RuleResult:
    b = c.tech.bb_pct_b
    if b is None:
        return None
    if b < 0:
        return 0.4, b, num(b, 2), "Kurs unter dem unteren Bollinger-Band – statistisch überverkauft"
    if b > 1:
        return -0.4, b, num(b, 2), "Kurs über dem oberen Bollinger-Band – statistisch überkauft"
    return -(b - 0.5) * 0.4, b, num(b, 2), f"%B {b:.2f} innerhalb der Bänder"


@rule("abstand_sma50", "Abstand zur 50-Tage-Linie", "oszillator", 0.5,
      "deutlich unter SMA50 (Rückkehr zum Mittelwert)", "deutlich über SMA50 (überdehnt)")
def _sma50(c: SignalContext) -> RuleResult:
    t = c.tech
    if t.sma50 is None:
        return None
    d = t.close / t.sma50 - 1
    s = interp(d, [(-0.25, 0.6), (-0.10, 0.2), (0.0, 0.0), (0.10, -0.2), (0.25, -0.6)])
    return s, d, pct(d), f"Kurs {d * 100:+.1f} % zur 50-Tage-Linie"


# =========================================================================== RISIKO
@rule("volatilitaet", "Volatilität (60 Tage, annualisiert)", "risiko", 0.8,
      "niedrige Schwankung (Low-Volatility-Effekt)", "extreme Schwankung (Lotterie-Aktie)")
def _vol(c: SignalContext) -> RuleResult:
    v = c.tech.vol_60d
    if v is None:
        return None
    s = interp(v, [(0.15, 0.3), (0.25, 0.1), (0.40, -0.2), (0.60, -0.5), (0.90, -0.7)])
    return s, v, pct(v, 0), f"Volatilität {pct(v, 0)} p.a."


@rule("drawdown", "Maximaler Drawdown (1 Jahr)", "risiko", 0.5,
      "geringe Rückschläge im letzten Jahr", "tiefer Einbruch im letzten Jahr")
def _dd(c: SignalContext) -> RuleResult:
    d = c.tech.max_dd_1y
    if d is None:
        return None
    s = interp(d, [(-0.6, -0.6), (-0.35, -0.3), (-0.15, 0.0), (-0.05, 0.2)])
    return s, d, pct(d), f"Max. Drawdown 1J {pct(d)}"


# =========================================================================== SENTIMENT
@rule("nachrichten", "Nachrichten-Sentiment", "sentiment", 1.2,
      "überwiegend positive aktuelle Nachrichten", "negative Schlagzeilen (Gewinnwarnung, Klage, Herabstufung …)")
def _news(c: SignalContext) -> RuleResult:
    n = c.news
    if n is None or n.score is None:
        return None
    amp = 1.0
    if n.attention and n.attention > 1:
        amp = min(1.5, 1 + 0.25 * (n.attention - 1))
    s = float(np.clip(n.score * 1.5 * amp, -1, 1))
    txt = f"{n.count} Meldungen in {c.config.news_lookback_days} Tagen, Stimmung " + band(s, "positiv", "negativ")
    if n.attention and n.attention > 2:
        txt += f", stark erhöhte Aufmerksamkeit ({n.attention:.1f}x)"
    if n.top_negative and s < 0:
        txt += f" – z. B. „{n.top_negative[0][0][:90]}“"
    elif n.top_positive and s > 0:
        txt += f" – z. B. „{n.top_positive[0][0][:90]}“"
    return s, n.score, num(n.score, 2), txt


@rule("analysten", "Analysten-Konsens", "sentiment", 0.6,
      "überwiegend Kaufempfehlungen", "überwiegend Verkaufsempfehlungen")
def _analysts(c: SignalContext) -> RuleResult:
    e = c.expectations
    if e is None or e.analyst_rating is None or (e.analyst_count is not None and e.analyst_count < 3):
        return None
    s = float(np.clip((3 - e.analyst_rating) / 2 * 0.6, -0.6, 0.6))
    label = {1: "Strong Buy", 2: "Buy", 3: "Hold", 4: "Sell", 5: "Strong Sell"}[int(round(min(5, max(1, e.analyst_rating))))]
    return s, e.analyst_rating, num(e.analyst_rating, 1), f"Konsens {e.analyst_rating:.1f} ({label})" + (
        f", {e.analyst_count} Analysten" if e.analyst_count else "")


@rule("kursziel", "Kurspotenzial bis Analysten-Kursziel", "sentiment", 0.7,
      "Kursziel > 20 % über aktuellem Kurs", "Kursziel unter aktuellem Kurs")
def _target(c: SignalContext) -> RuleResult:
    e = c.expectations
    if e is None or not e.target_price:
        return None
    up = e.target_price / c.tech.close - 1
    s = interp(up, [(-0.15, -0.7), (0.0, -0.3), (0.10, 0.1), (0.25, 0.5), (0.5, 0.7)])
    return s, up, pct(up), f"Kursziel {e.target_price:.2f} ({up * 100:+.1f} %)"


@rule("short_interest", "Short Interest (Leerverkaufsquote)", "sentiment", 0.6,
      "geringe Leerverkaufsquote", "hohe Leerverkaufsquote (Profis wetten auf Fall) – aber Squeeze-Gefahr")
def _si(c: SignalContext) -> RuleResult:
    e = c.expectations
    if e is None or e.short_interest_pct is None:
        return None
    v = e.short_interest_pct
    s = interp(v, [(0.02, 0.1), (0.05, 0.0), (0.10, -0.3), (0.20, -0.5), (0.35, -0.6)])
    txt = f"{pct(v)} des Free Float leerverkauft"
    if e.days_to_cover:
        txt += f", {e.days_to_cover:.1f} Tage zum Eindecken"
    if v >= c.config.squeeze_short_interest:
        txt += " – Short-Squeeze-Risiko!"
    return s, v, pct(v), txt


@rule("insider", "Insider-Transaktionen", "sentiment", 0.6,
      "Insider kaufen eigene Aktien", "Insider verkaufen massiv")
def _insider(c: SignalContext) -> RuleResult:
    e = c.expectations
    if e is None or e.insider_net_buying is None:
        return None
    v = float(np.clip(e.insider_net_buying, -1, 1))
    s = 0.6 * v
    return s, v, num(v, 2), "Insider " + ("kaufen netto" if v > 0.05 else ("verkaufen netto" if v < -0.05 else "neutral"))


# =========================================================================== MARKT
@rule("marktphase", "Rückenwind durch Gesamtmarkt", "markt", 1.0,
      "Index im Aufwärtstrend (die Flut hebt alle Boote)", "Index im Abwärtstrend (Gegenwind für alle Longs)")
def _market(c: SignalContext) -> RuleResult:
    r = c.regime
    s = float(np.clip(0.6 * r.trend_score, -0.6, 0.6))
    return s, r.trend_score, num(r.trend_score, 2), r.regime.label


@rule("beta", "Beta (Marktsensitivität)", "markt", 0.8,
      "hohes Beta im Bullenmarkt / niedriges Beta im Bärenmarkt", "hohes Beta im Bärenmarkt")
def _beta(c: SignalContext) -> RuleResult:
    b = c.tech.beta
    if b is None:
        return None
    reg = c.regime.regime
    if reg == Regime.BULL:
        s = interp(b, [(0.5, -0.2), (1.0, 0.0), (1.5, 0.3)])
        txt = "verstärkt Aufwärtsbewegung" if b > 1.1 else ("defensiv – hinkt im Bullenmarkt oft hinterher" if b < 0.8 else "marktneutral")
    elif reg == Regime.BEAR:
        s = interp(b, [(0.5, 0.4), (1.0, 0.0), (1.5, -0.5)])
        txt = "fällt überproportional mit dem Markt" if b > 1.1 else ("defensiv – fällt weniger" if b < 0.8 else "marktneutral")
    else:
        s = interp(b, [(0.5, 0.1), (1.5, -0.1)])
        txt = "seitwärts kaum relevant"
    return s, b, num(b, 2), f"Beta {b:.2f} – {txt}"


@rule("groesse", "Marktkapitalisierung (Size)", "markt", 0.6,
      "Small Caps im frühen Bullenmarkt, Mega Caps im Bärenmarkt", "Micro/Small Caps im Bärenmarkt (Flucht in Qualität)")
def _size(c: SignalContext) -> RuleResult:
    mc = c.fund.market_cap
    cls = size_class(mc)
    if cls is None:
        return None
    table = {
        Regime.BULL: {"Mega Cap": 0.0, "Large Cap": 0.0, "Mid Cap": 0.1, "Small Cap": 0.2, "Micro Cap": 0.1},
        Regime.BEAR: {"Mega Cap": 0.2, "Large Cap": 0.1, "Mid Cap": -0.1, "Small Cap": -0.3, "Micro Cap": -0.4},
        Regime.SIDEWAYS: {"Mega Cap": 0.05, "Large Cap": 0.05, "Mid Cap": 0.0, "Small Cap": -0.1, "Micro Cap": -0.2},
    }
    s = table[c.regime.regime][cls]
    return s, mc, money(mc), f"{cls} ({money(mc)})"


# --------------------------------------------------------------------------- Auswertung
def evaluate_rules(ctx: SignalContext) -> list[Signal]:
    out: list[Signal] = []
    financial = is_financial(ctx.info)
    for spec in RULES:
        if spec.key in ctx.config.disabled_signals or (financial and spec.key in FINANCIAL_SKIP):
            continue
        res = spec.fn(ctx)
        if res is None:
            continue
        score, value, value_fmt, rationale = res
        weight = float(ctx.config.signal_weights.get(spec.key, spec.weight))
        if spec.key == "nachrichten" and ctx.news is not None and ctx.news.count < 2:
            weight *= 0.5  # einzelne Meldung = schwaches Signal
        out.append(
            Signal(
                key=spec.key,
                name=spec.name,
                category=spec.category,
                score=float(np.clip(score, -1, 1)),
                weight=weight,
                value=value,
                value_fmt=value_fmt,
                rationale=rationale,
            )
        )
    return out


CROSS_SECTIONAL = [
    ("rel_bewertung", "Relative Bewertung im Universum (Gewinnrendite-Rang)", "bewertung", 0.8,
     "günstigste Aktien des Universums", "teuerste Aktien des Universums"),
    ("rel_momentum", "Relatives Momentum im Universum (Rang)", "momentum", 0.8,
     "stärkste Aktien des Universums", "schwächste Aktien des Universums"),
]
