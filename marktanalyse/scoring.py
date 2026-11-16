"""Verdichtung der Signale zu Score, Empfehlung, Trade-Plan und Portfolio-Sicht."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Optional

import numpy as np

from .config import CATEGORIES, Config
from .models import (
    MarketRegime,
    PortfolioView,
    Recommendation,
    Regime,
    Signal,
    TickerAnalysis,
    TradePlan,
)


def aggregate(signals: list[Signal], regime: MarketRegime, cfg: Config) -> tuple[dict, float, float, float]:
    """Gibt (Kategorie-Scores, Gesamtscore, Konfidenz, Datenabdeckung) zurück."""
    by_cat: dict[str, list[Signal]] = defaultdict(list)
    for s in signals:
        by_cat[s.category].append(s)

    cat_scores: dict[str, float] = {}
    for cat, sigs in by_cat.items():
        w = sum(s.weight for s in sigs)
        if w > 0:
            cat_scores[cat] = sum(s.score * s.weight for s in sigs) / w

    reg = regime.regime.value
    total_w = sum(cfg.category_weight(reg, c) for c in CATEGORIES)
    used_w = sum(cfg.category_weight(reg, c) for c in cat_scores)
    if used_w == 0:
        return cat_scores, 0.0, 0.0, 0.0
    total = sum(cfg.category_weight(reg, c) * v for c, v in cat_scores.items()) / used_w
    coverage = used_w / total_w if total_w else 0.0

    # Konfidenz: Stärke des Signals, Einigkeit der Kategorien, Datenabdeckung
    if abs(total) < 1e-9:
        agreement = 0.0
    else:
        agree_w = sum(cfg.category_weight(reg, c) for c, v in cat_scores.items() if v * total > 0)
        agreement = agree_w / used_w
    strength = min(1.0, abs(total) / 0.5)
    confidence = 0.5 * strength + 0.3 * agreement + 0.2 * coverage
    return cat_scores, float(total), float(confidence), float(coverage)


def thresholds_for(regime: MarketRegime, cfg: Config) -> dict:
    th = dict(cfg.thresholds[regime.regime.value])
    if regime.high_volatility:
        th = {k: v + cfg.high_vol_threshold_add for k, v in th.items()}
    return th


def classify(score: float, regime: MarketRegime, cfg: Config) -> Recommendation:
    th = thresholds_for(regime, cfg)
    if score >= th["strong_long"]:
        return Recommendation.STRONG_LONG
    if score >= th["long"]:
        return Recommendation.LONG
    if score <= -th["strong_short"]:
        return Recommendation.STRONG_SHORT
    if score <= -th["short"]:
        return Recommendation.SHORT
    return Recommendation.HOLD


def apply_vetoes(a: TickerAnalysis, regime: MarketRegime, cfg: Config) -> None:
    """Praxisregeln, die eine rein rechnerische Empfehlung abschwächen."""
    rec = a.recommendation
    m = a.metrics
    tech, fund, exp = m.get("technisch", {}), m.get("fundamental", {}), m.get("erwartungen") or {}

    if rec.direction < 0:
        si = exp.get("short_interest_pct")
        if si is not None and si >= cfg.squeeze_short_interest:
            mom = tech.get("ret_1m") or 0
            rec = rec.downgrade() if mom <= 0 else Recommendation.HOLD
            a.notes.append(f"Short-Squeeze-Gefahr: {si:.0%} Leerverkaufsquote – Short abgeschwächt.")
        adv = tech.get("avg_dollar_volume")
        if adv is not None and adv < cfg.min_dollar_volume_short:
            rec = Recommendation.HOLD
            a.notes.append("Zu geringe Liquidität für einen Leerverkauf (Leihe teuer/knapp) – kein Short.")
        if regime.regime == Regime.BULL and (tech.get("mom_12_1") or 0) > 0.20 and tech.get("sma200") and a.price > tech["sma200"]:
            rec = rec.downgrade()
            a.notes.append("Nicht gegen den Trend shorten: Aktie im intakten Aufwärtstrend eines Bullenmarkts.")

    if rec.direction > 0:
        if regime.regime == Regime.BEAR and (tech.get("mom_12_1") or 0) < -0.20 and tech.get("sma200") and a.price < tech["sma200"]:
            rec = rec.downgrade()
            a.notes.append("Nicht ins fallende Messer greifen: Abwärtstrend in einem Bärenmarkt – Long abgeschwächt.")
        z = fund.get("altman_z")
        if rec == Recommendation.STRONG_LONG and z is not None and z < cfg.distress_altman_z:
            rec = Recommendation.LONG
            a.notes.append(f"Altman Z {z:.2f} signalisiert Insolvenzrisiko – kein starker Kauf.")

    ne = exp.get("next_earnings_date")
    if ne is not None:
        days = (ne - a.as_of).days
        if 0 <= days <= cfg.earnings_blackout_days:
            a.notes.append(f"Quartalszahlen in {days} Tagen ({ne}) – Ereignisrisiko, Positionsgröße halbiert.")
    if a.coverage < 0.5:
        a.notes.append(f"Nur {a.coverage:.0%} der Kennzahlen-Gewichte verfügbar – Aussagekraft eingeschränkt.")
    a.recommendation = rec


def build_trade_plan(a: TickerAnalysis, regime: MarketRegime, cfg: Config) -> Optional[TradePlan]:
    d = a.recommendation.direction
    if d == 0:
        return None
    tech = a.metrics.get("technisch", {})
    atr = tech.get("atr14")
    if not atr or atr <= 0:
        vol = tech.get("vol_20d") or 0.3
        atr = a.price * vol / math.sqrt(252) * 1.5
    mult = cfg.atr_stop_multiple_high_vol if regime.high_volatility else cfg.atr_stop_multiple
    risk = mult * atr
    stop = a.price - d * risk
    target = a.price + d * cfg.reward_risk * risk
    notes = []

    exposure = cfg.exposure[regime.regime.value]["long" if d > 0 else "short"]
    factor = exposure * (0.5 + 0.5 * a.confidence)
    if regime.high_volatility:
        factor *= cfg.high_vol_size_factor
        notes.append("Hohe Marktvolatilität: Positionsgröße reduziert.")
    if any("Quartalszahlen" in n for n in a.notes):
        factor *= 0.5
    risk_budget = cfg.capital * cfg.risk_per_trade * factor
    shares = int(risk_budget / risk) if risk > 0 else 0
    max_shares = int(cfg.capital * cfg.max_position_pct / a.price) if a.price > 0 else 0
    if shares > max_shares:
        shares = max_shares
        notes.append(f"Positionsgröße auf {cfg.max_position_pct:.0%} des Kapitals begrenzt.")
    value = shares * a.price

    exp = a.metrics.get("erwartungen") or {}
    tp = exp.get("target_price")
    if d > 0 and tp and tp < target:
        notes.append(f"Analysten-Kursziel ({tp:.2f}) liegt unter dem technischen Ziel – ggf. früher Gewinne mitnehmen.")
    if d < 0:
        notes.append("Short: Leihgebühr, Dividendenzahlungen und unbegrenztes Verlustrisiko beachten; Stop strikt einhalten.")
    notes.append("Bei der nächsten Analyse neu bewerten; Stop-Loss nachziehen (Trailing Stop um gleiches ATR-Vielfaches).")

    return TradePlan(
        direction=d,
        entry=a.price,
        stop_loss=stop,
        take_profit=target,
        risk_per_share=risk,
        shares=shares,
        position_value=value,
        position_pct=value / cfg.capital if cfg.capital else 0.0,
        reward_risk=cfg.reward_risk,
        notes=notes,
    )


def portfolio_view(analyses: list[TickerAnalysis], regime: MarketRegime) -> PortfolioView:
    r = regime.regime
    if r == Regime.BULL:
        pv = PortfolioView(
            net_exposure="+60 % bis +100 % netto long",
            gross_exposure="100–130 %",
            long_strategy=[
                "Trend- und Momentum-Führer kaufen (Kurs über steigender 200-Tage-Linie, starke relative Stärke).",
                "Rücksetzer im Aufwärtstrend kaufen (RSI 30–40 nahe der 50-Tage-Linie).",
                "Wachstumswerte mit vertretbarem PEG (< 2) bevorzugen; Small/Mid Caps profitieren oft überproportional.",
            ],
            short_strategy=[
                "Shorts nur selektiv und klein: fundamental schwache Titel mit gebrochenem Trend (Death Cross, negative Nachrichten).",
                "Keine Shorts gegen intakte Aufwärtstrends oder bei hoher Leerverkaufsquote (Squeeze-Gefahr).",
            ],
            hedging=["Kein permanenter Index-Hedge nötig; Stops nachziehen und Gewinne laufen lassen."],
        )
    elif r == Regime.BEAR:
        pv = PortfolioView(
            net_exposure="−30 % bis +30 % (Kapitalerhalt hat Vorrang)",
            gross_exposure="50–100 %",
            long_strategy=[
                "Nur defensive Qualität: niedriges Beta, Netto-Cash, stabile Cashflows, solide Dividende.",
                "Keine 'billigen' Aktien im Abwärtstrend kaufen – auf Bodenbildung (Kurs zurück über SMA50/SMA200) warten.",
            ],
            short_strategy=[
                "Shorts auf Titel mit hoher Bewertung, schwacher Bilanz (hohe Verschuldung, Altman Z < 1,8) und negativem Momentum.",
                "Einstiege in Erholungen suchen (RSI > 60–70 unter fallender 200-Tage-Linie).",
                "Negative Nachrichten (Gewinnwarnungen, Herabstufungen) als Bestätigung nutzen.",
            ],
            hedging=[
                "Index-Short oder Put-Optionen auf den Leitindex zur Absicherung der Long-Seite.",
                "Cash-Quote erhöhen; Positionsgrößen reduzieren.",
            ],
        )
    else:
        pv = PortfolioView(
            net_exposure="+20 % bis +60 % netto long",
            gross_exposure="80–120 %",
            long_strategy=[
                "Bewertung und Qualität stärker gewichten; an Unterstützungen / unteren Bollinger-Bändern kaufen.",
                "Dividendenwerte und Unternehmen mit hoher FCF-Rendite bevorzugen.",
            ],
            short_strategy=[
                "Mean-Reversion-Shorts an Widerständen (RSI > 70, oberes Bollinger-Band) bei teuren, schwachen Titeln.",
                "Pair-Trades (Long stark / Short schwach in derselben Branche) reduzieren das Marktrisiko.",
            ],
            hedging=["Teil-Absicherung über Pair-Trades statt Index-Short."],
        )
    if regime.high_volatility:
        pv.hedging.insert(0, "Volatilitätsstress: Brutto-Exposure senken, weitere Stops, kleinere Positionen.")

    longs = sorted([a for a in analyses if a.recommendation.direction > 0], key=lambda a: -a.total_score)
    shorts = sorted([a for a in analyses if a.recommendation.direction < 0], key=lambda a: a.total_score)
    pv.top_longs = [a.ticker for a in longs[:5]]
    pv.top_shorts = [a.ticker for a in shorts[:5]]

    # Pair-Trades: gleiche Branche, großer Score-Abstand
    by_sector: dict[str, list[TickerAnalysis]] = defaultdict(list)
    for a in analyses:
        if a.info.sector:
            by_sector[a.info.sector].append(a)
    for sector, items in by_sector.items():
        if len(items) < 2:
            continue
        best = max(items, key=lambda a: a.total_score)
        worst = min(items, key=lambda a: a.total_score)
        if best.total_score > 0.05 and worst.total_score < -0.05 and best.total_score - worst.total_score > 0.35:
            pv.pair_trades.append(
                (best.ticker, worst.ticker,
                 f"{sector}: Score {best.total_score:+.2f} vs. {worst.total_score:+.2f} – Marktrisiko neutralisiert")
            )
    return pv


def cross_sectional_signals(analyses: list[TickerAnalysis], specs) -> None:
    """Rang-basierte Signale innerhalb des analysierten Universums (ab 4 Titeln)."""
    if len(analyses) < 4:
        return
    spec = {s[0]: s for s in specs}

    def ranks(values: dict[str, float]) -> dict[str, float]:
        if len(values) < 4:
            return {}
        keys = list(values)
        order = np.argsort(np.argsort([values[k] for k in keys]))
        n = len(keys) - 1
        return {k: float(order[i] / n) for i, k in enumerate(keys)}

    ey = {a.ticker: a.metrics["fundamental"].get("earnings_yield") for a in analyses}
    ey = {k: v for k, v in ey.items() if v is not None}
    mom = {a.ticker: a.metrics["technisch"].get("mom_12_1") for a in analyses}
    mom = {k: v for k, v in mom.items() if v is not None}

    for key, values, txt in (
        ("rel_bewertung", ranks(ey), "Gewinnrendite"),
        ("rel_momentum", ranks(mom), "12-1-Momentum"),
    ):
        _, name, cat, weight, *_ = spec[key]
        for a in analyses:
            if a.ticker not in values:
                continue
            p = values[a.ticker]
            score = 2 * p - 1
            a.signals.append(
                Signal(key=key, name=name, category=cat, score=score * 0.8, weight=weight, value=p,
                       value_fmt=f"{p:.0%}", rationale=f"{txt}-Perzentil {p:.0%} im analysierten Universum")
            )
