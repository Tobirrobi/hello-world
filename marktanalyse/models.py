"""Datenmodelle für Kurse, Fundamentaldaten, Nachrichten und Analyseergebnisse.

Alle Rohdaten tragen ein Verfügbarkeitsdatum (``available_date`` bzw.
``published``). Die Analyse-Engine nutzt nur Daten, die zum Analysezeitpunkt
bereits öffentlich waren. So ist eine Analyse "für einen Zeitpunkt" ohne
Blick in die Zukunft (Look-ahead-Bias) möglich.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional


@dataclass
class TickerInfo:
    ticker: str
    name: str = ""
    sector: str = ""
    currency: str = ""


@dataclass
class FundamentalSnapshot:
    """Fundamentaldaten eines Berichtszeitraums (Strömungsgrößen als TTM = letzte 12 Monate)."""

    available_date: date  # Tag, ab dem die Zahlen öffentlich bekannt waren
    period_end: Optional[date] = None
    shares_outstanding: Optional[float] = None
    eps_ttm: Optional[float] = None
    revenue_ttm: Optional[float] = None
    gross_profit_ttm: Optional[float] = None
    operating_income_ttm: Optional[float] = None  # ~ EBIT
    net_income_ttm: Optional[float] = None
    ebitda_ttm: Optional[float] = None
    interest_expense_ttm: Optional[float] = None
    operating_cash_flow_ttm: Optional[float] = None
    capex_ttm: Optional[float] = None  # als positive Ausgabe
    free_cash_flow_ttm: Optional[float] = None
    dividends_per_share_ttm: Optional[float] = None
    total_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    total_equity: Optional[float] = None
    total_debt: Optional[float] = None
    cash: Optional[float] = None
    current_assets: Optional[float] = None
    current_liabilities: Optional[float] = None
    retained_earnings: Optional[float] = None


@dataclass
class MarketSentimentSnapshot:
    """Erwartungen & Positionierung: Analysten, Short Interest, Insider, Termine."""

    available_date: date
    analyst_rating: Optional[float] = None  # 1 = Strong Buy ... 5 = Strong Sell
    analyst_count: Optional[int] = None
    target_price: Optional[float] = None
    eps_forward: Optional[float] = None  # erwarteter Gewinn je Aktie (12 Monate voraus)
    short_interest_pct: Optional[float] = None  # Anteil am Free Float, 0..1
    days_to_cover: Optional[float] = None
    insider_net_buying: Optional[float] = None  # -1 (nur Verkäufe) .. +1 (nur Käufe)
    next_earnings_date: Optional[date] = None


@dataclass
class NewsItem:
    published: datetime
    headline: str
    summary: str = ""
    source: str = ""
    url: str = ""


class Regime(str, Enum):
    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"

    @property
    def label(self) -> str:
        return {
            Regime.BULL: "Steigender Markt (Bullenmarkt)",
            Regime.BEAR: "Fallender Markt (Bärenmarkt)",
            Regime.SIDEWAYS: "Seitwärtsmarkt",
        }[self]


class Recommendation(str, Enum):
    STRONG_LONG = "strong_long"
    LONG = "long"
    HOLD = "hold"
    SHORT = "short"
    STRONG_SHORT = "strong_short"

    @property
    def label(self) -> str:
        return {
            Recommendation.STRONG_LONG: "STARKER KAUF (Long)",
            Recommendation.LONG: "KAUF (Long)",
            Recommendation.HOLD: "HALTEN / NEUTRAL",
            Recommendation.SHORT: "VERKAUF / SHORT",
            Recommendation.STRONG_SHORT: "STARKER SHORT",
        }[self]

    @property
    def direction(self) -> int:
        return {
            Recommendation.STRONG_LONG: 1,
            Recommendation.LONG: 1,
            Recommendation.HOLD: 0,
            Recommendation.SHORT: -1,
            Recommendation.STRONG_SHORT: -1,
        }[self]

    def downgrade(self) -> "Recommendation":
        """Eine Stufe Richtung Neutral."""
        return {
            Recommendation.STRONG_LONG: Recommendation.LONG,
            Recommendation.LONG: Recommendation.HOLD,
            Recommendation.HOLD: Recommendation.HOLD,
            Recommendation.SHORT: Recommendation.HOLD,
            Recommendation.STRONG_SHORT: Recommendation.SHORT,
        }[self]


@dataclass
class Signal:
    """Ein einzelnes Signal. ``score`` > 0 spricht für Long, < 0 für Short."""

    key: str
    name: str
    category: str
    score: float  # -1 .. +1
    weight: float = 1.0
    value: Optional[float] = None
    value_fmt: str = ""
    rationale: str = ""


@dataclass
class MarketRegime:
    regime: Regime
    high_volatility: bool
    trend_score: float  # -1 .. +1
    volatility: Optional[float] = None  # annualisiert
    drawdown: Optional[float] = None  # vom 52-Wochen-Hoch
    description: str = ""
    details: dict = field(default_factory=dict)


@dataclass
class TradePlan:
    direction: int  # +1 Long, -1 Short
    entry: float
    stop_loss: float
    take_profit: float
    risk_per_share: float
    shares: int
    position_value: float
    position_pct: float  # Anteil am Kapital
    reward_risk: float
    notes: list[str] = field(default_factory=list)


@dataclass
class TickerAnalysis:
    ticker: str
    info: TickerInfo
    as_of: date
    price: float
    signals: list[Signal]
    metrics: dict  # alle berechneten Kennzahlen (für Report/JSON)
    category_scores: dict = field(default_factory=dict)
    total_score: float = 0.0
    confidence: float = 0.0
    coverage: float = 0.0
    recommendation: Recommendation = Recommendation.HOLD
    raw_recommendation: Recommendation = Recommendation.HOLD
    notes: list[str] = field(default_factory=list)
    trade_plan: Optional[TradePlan] = None

    def pro_signals(self, n: int = 5) -> list[Signal]:
        s = [x for x in self.signals if x.score > 0.05]
        return sorted(s, key=lambda x: x.score * x.weight, reverse=True)[:n]

    def contra_signals(self, n: int = 5) -> list[Signal]:
        s = [x for x in self.signals if x.score < -0.05]
        return sorted(s, key=lambda x: x.score * x.weight)[:n]


@dataclass
class PortfolioView:
    net_exposure: str
    gross_exposure: str
    long_strategy: list[str]
    short_strategy: list[str]
    hedging: list[str]
    top_longs: list[str] = field(default_factory=list)
    top_shorts: list[str] = field(default_factory=list)
    pair_trades: list[tuple[str, str, str]] = field(default_factory=list)  # (long, short, Begründung)


@dataclass
class AnalysisReport:
    as_of: date
    generated_at: datetime
    benchmark: str
    regime: MarketRegime
    analyses: list[TickerAnalysis]
    portfolio: PortfolioView
    warnings: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)  # Änderungen ggü. letztem Lauf
