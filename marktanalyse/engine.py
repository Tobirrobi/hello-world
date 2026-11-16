"""Analyse-Engine: führt für einen Stichtag alle Schritte aus und liefert Empfehlungen."""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from typing import Optional, Sequence

import pandas as pd

from .config import Config
from .data.base import DataProvider, normalize_prices
from .fundamentals import compute_fundamentals
from .indicators import compute_technicals
from .models import AnalysisReport, FundamentalSnapshot, MarketSentimentSnapshot, TickerAnalysis
from .regime import detect_regime
from .scoring import (
    aggregate,
    apply_vetoes,
    build_trade_plan,
    classify,
    cross_sectional_signals,
    portfolio_view,
)
from .sentiment import LexiconSentimentScorer, SentimentScorer, aggregate_news
from .signals import CROSS_SECTIONAL, SignalContext, evaluate_rules

log = logging.getLogger(__name__)


def _latest_before(items, as_of: date, max_age_days: Optional[int] = None):
    cands = [x for x in items if x.available_date <= as_of]
    if not cands:
        return None
    best = max(cands, key=lambda x: x.available_date)
    if max_age_days is not None and (as_of - best.available_date).days > max_age_days:
        return None
    return best


def _year_ago(items: list[FundamentalSnapshot], cur: FundamentalSnapshot) -> Optional[FundamentalSnapshot]:
    """Vergleichsperiode ~12 Monate vor dem aktuellen Snapshot."""
    ref = cur.period_end or cur.available_date
    best, best_gap = None, None
    for x in items:
        p = x.period_end or x.available_date
        gap = abs((ref - p).days - 365)
        if x is not cur and x.available_date <= cur.available_date and gap <= 60:
            if best_gap is None or gap < best_gap:
                best, best_gap = x, gap
    return best


class Analyzer:
    def __init__(
        self,
        provider: DataProvider,
        benchmark: str = "^GSPC",
        config: Optional[Config] = None,
        sentiment_scorer: Optional[SentimentScorer] = None,
    ):
        self.provider = provider
        self.benchmark = benchmark
        self.config = config or Config()
        self.scorer = sentiment_scorer or LexiconSentimentScorer()

    # ------------------------------------------------------------------ Hilfen
    def _prices(self, ticker: str, as_of: date) -> pd.DataFrame:
        start = as_of - timedelta(days=self.config.price_history_days)
        df = normalize_prices(self.provider.prices(ticker, start, as_of))
        return df.loc[: pd.Timestamp(as_of)]  # Sicherheitsnetz gegen Zukunftsdaten

    def analyze_ticker(self, ticker: str, as_of: date, regime, bench_close) -> TickerAnalysis:
        cfg = self.config
        df = self._prices(ticker, as_of)
        if len(df) < 30:
            raise ValueError(f"zu wenige Kursdaten ({len(df)} Tage)")
        last_bar = df.index[-1].date()
        if (as_of - last_bar).days > 7:
            raise ValueError(f"letzter Kurs vom {last_bar} – Daten veraltet")
        tech = compute_technicals(df, bench_close)
        info = self.provider.info(ticker)

        funds = sorted(self.provider.fundamentals(ticker), key=lambda s: s.available_date)
        cur = _latest_before(funds, as_of, cfg.max_fundamental_age_days)
        prev = _year_ago(funds, cur) if cur else None
        expectations: Optional[MarketSentimentSnapshot] = _latest_before(
            self.provider.market_sentiment(ticker), as_of, cfg.max_sentiment_age_days
        )
        fund = compute_fundamentals(tech.close, cur, prev, expectations)

        as_of_dt = datetime.combine(as_of, time(23, 59, 59))
        news_items = self.provider.news(ticker, as_of_dt - timedelta(days=cfg.news_lookback_days), as_of_dt)
        news = aggregate_news(news_items, as_of_dt, self.scorer, cfg.news_lookback_days, cfg.news_half_life_days)

        ctx = SignalContext(as_of, info, tech, fund, news, expectations, regime, cfg)
        signals = evaluate_rules(ctx)
        metrics = {
            "technisch": tech.to_dict(),
            "fundamental": fund.to_dict(),
            "erwartungen": asdict(expectations) if expectations else None,
            "nachrichten": {
                "score": news.score, "anzahl": news.count, "letzte_3_tage": news.recent_count,
                "aufmerksamkeit": news.attention, "verfahren": news.scorer,
                "positiv": news.top_positive, "negativ": news.top_negative,
            },
            "datenstand": {
                "kurs": str(last_bar),
                "fundamentaldaten": str(cur.available_date) if cur else None,
                "periode": str(cur.period_end) if cur and cur.period_end else None,
                "erwartungen": str(expectations.available_date) if expectations else None,
            },
        }
        return TickerAnalysis(ticker=ticker, info=info, as_of=as_of, price=tech.close, signals=signals, metrics=metrics)

    # ------------------------------------------------------------------ Hauptfunktion
    def analyze(self, tickers: Sequence[str], as_of: Optional[date] = None) -> AnalysisReport:
        as_of = as_of or date.today()
        cfg = self.config
        warnings: list[str] = []

        bench_close = None
        try:
            bdf = self._prices(self.benchmark, as_of)
            bench_close = bdf["close"] if not bdf.empty else None
        except Exception as exc:
            warnings.append(f"Benchmark {self.benchmark} nicht verfügbar ({exc}) – Marktphase neutral angenommen.")
        regime = detect_regime(bench_close, self.benchmark)

        analyses: list[TickerAnalysis] = []
        for t in tickers:
            try:
                analyses.append(self.analyze_ticker(t, as_of, regime, bench_close))
            except Exception as exc:
                log.debug("Analyse %s fehlgeschlagen", t, exc_info=True)
                warnings.append(f"{t}: übersprungen – {exc}")

        cross_sectional_signals(analyses, CROSS_SECTIONAL)
        for a in analyses:
            a.category_scores, a.total_score, a.confidence, a.coverage = aggregate(a.signals, regime, cfg)
            a.raw_recommendation = a.recommendation = classify(a.total_score, regime, cfg)
            apply_vetoes(a, regime, cfg)
            a.trade_plan = build_trade_plan(a, regime, cfg)

        analyses.sort(key=lambda a: a.total_score, reverse=True)
        return AnalysisReport(
            as_of=as_of,
            generated_at=datetime.now(),
            benchmark=self.benchmark,
            regime=regime,
            analyses=analyses,
            portfolio=portfolio_view(analyses, regime),
            warnings=warnings,
        )
