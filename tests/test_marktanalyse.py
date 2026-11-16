from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from marktanalyse import Analyzer, Config, Recommendation, Regime
from marktanalyse.backtest import backtest_markdown, run_backtest
from marktanalyse.data import CsvProvider, DataProvider, SyntheticProvider, archive
from marktanalyse.data.synthetic import BENCHMARK, demo_dates
from marktanalyse.fundamentals import altman_z_score, compute_fundamentals, piotroski_f_score
from marktanalyse.indicators import compute_technicals, period_return, rsi, sma
from marktanalyse.models import FundamentalSnapshot, MarketRegime, NewsItem
from marktanalyse.regime import detect_regime
from marktanalyse.report import diff_with_previous, to_dict, to_json, to_markdown, to_text
from marktanalyse.scheduler import next_run, parse_interval
from marktanalyse.scoring import classify
from marktanalyse.sentiment import ClaudeSentimentScorer, LexiconSentimentScorer, aggregate_news
from marktanalyse.signals import RULES, interp


@pytest.fixture(scope="module")
def provider():
    return SyntheticProvider()


@pytest.fixture(scope="module")
def analyzer(provider):
    return Analyzer(provider, benchmark=BENCHMARK)


def _series(values, start="2020-01-01"):
    idx = pd.bdate_range(start, periods=len(values))
    return pd.Series(values, index=idx, dtype=float)


# ------------------------------------------------------------------ Indikatoren
def test_basic_indicators():
    up = _series(np.linspace(100, 200, 300))
    assert rsi(up).iloc[-1] == pytest.approx(100.0)
    assert sma(up, 10).iloc[-1] == pytest.approx(np.mean(up.iloc[-10:]))
    assert period_return(up, 10) == pytest.approx(up.iloc[-1] / up.iloc[-11] - 1)
    down = _series(np.linspace(200, 100, 300))
    assert rsi(down).iloc[-1] < 1


def test_technical_snapshot_uptrend():
    close = _series(100 * np.exp(np.linspace(0, 0.6, 400)))
    df = pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99, "close": close, "volume": 1e6})
    t = compute_technicals(df, close * 0.5)
    assert t.close > t.sma50 > t.sma200
    assert t.cross_state == 1
    assert t.mom_12_1 > 0 and t.dist_52w_high == pytest.approx(0.0)
    assert t.beta == pytest.approx(1.0, abs=1e-6)


# ------------------------------------------------------------------ Fundamentaldaten
def _snap(**kw):
    base = dict(available_date=date(2024, 5, 1), period_end=date(2024, 3, 31), shares_outstanding=100.0,
                eps_ttm=2.0, revenue_ttm=1000.0, gross_profit_ttm=400.0, operating_income_ttm=150.0,
                net_income_ttm=200.0, ebitda_ttm=250.0, interest_expense_ttm=10.0, operating_cash_flow_ttm=260.0,
                capex_ttm=60.0, free_cash_flow_ttm=200.0, dividends_per_share_ttm=0.5, total_assets=2000.0,
                total_liabilities=1000.0, total_equity=1000.0, total_debt=500.0, cash=100.0, current_assets=600.0,
                current_liabilities=300.0, retained_earnings=700.0)
    base.update(kw)
    return FundamentalSnapshot(**base)


def test_fundamental_ratios():
    cur = _snap()
    prev = _snap(available_date=date(2023, 5, 1), period_end=date(2023, 3, 31), eps_ttm=1.6, revenue_ttm=900.0,
                 net_income_ttm=160.0, operating_income_ttm=120.0)
    m = compute_fundamentals(30.0, cur, prev)
    assert m.market_cap == 3000.0
    assert m.pe == pytest.approx(15.0)
    assert m.pb == pytest.approx(3.0)
    assert m.ps == pytest.approx(3.0)
    assert m.ev_ebitda == pytest.approx((3000 + 500 - 100) / 250)
    assert m.fcf_yield == pytest.approx(200 / 3000)
    assert m.dividend_yield == pytest.approx(0.5 / 30)
    assert m.eps_growth == pytest.approx(0.25)
    assert m.peg == pytest.approx(15 / 25)
    assert m.roe == pytest.approx(0.2)
    assert m.net_debt_to_ebitda == pytest.approx(400 / 250)
    assert m.revenue_growth == pytest.approx(1000 / 900 - 1)


def test_piotroski_and_altman():
    good_prev = _snap(net_income_ttm=100.0, total_debt=700.0, current_assets=500.0, gross_profit_ttm=350.0,
                      revenue_ttm=900.0, shares_outstanding=105.0)
    assert piotroski_f_score(_snap(), good_prev) == 9
    bad = _snap(net_income_ttm=-50.0, operating_cash_flow_ttm=-20.0)
    assert piotroski_f_score(bad, _snap()) <= 3
    z = altman_z_score(_snap(), 3000.0)
    expected = 1.2 * 300 / 2000 + 1.4 * 700 / 2000 + 3.3 * 150 / 2000 + 0.6 * 3000 / 1000 + 1000 / 2000
    assert z == pytest.approx(expected)


def test_loss_making_company_has_no_pe():
    m = compute_fundamentals(10.0, _snap(eps_ttm=-1.0, net_income_ttm=-100.0))
    assert m.pe is None and m.eps_negative


# ------------------------------------------------------------------ Sentiment
def test_lexicon_sentiment():
    s = LexiconSentimentScorer()
    assert s.score_text("Firma hebt Prognose an und meldet Rekordumsatz") > 0.5
    assert s.score_text("Gewinnwarnung: Firma senkt Prognose") < -0.5
    assert s.score_text("Company raises guidance after it beats estimates") > 0.5
    assert s.score_text("No bankruptcy expected, says CEO") > 0  # Negation
    assert s.score_text("Hauptversammlung findet statt") == 0


def test_news_aggregation_decay():
    now = datetime(2024, 1, 15, 18)
    items = [NewsItem(now - timedelta(days=10), "Gewinnwarnung bei Firma"),
             NewsItem(now - timedelta(hours=5), "Firma hebt Prognose an")]
    agg = aggregate_news(items, now, LexiconSentimentScorer(), lookback_days=14, half_life_days=3)
    assert agg.count == 2 and agg.score > 0  # die frische Meldung dominiert


def test_claude_scorer_parses_and_falls_back():
    scorer = object.__new__(ClaudeSentimentScorer)
    scorer.model, scorer.fallback = "x", LexiconSentimentScorer()
    payload = json.dumps({"scores": [{"index": 0, "score": 0.8}, {"index": 1, "score": -3}]})
    resp = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=payload)])
    scorer.client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: resp)))
    items = [NewsItem(datetime.now(), "a"), NewsItem(datetime.now(), "b")]
    assert scorer.score(items) == [0.8, -1.0]

    def boom(**kw):
        raise RuntimeError("offline")

    scorer.client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=boom)))
    assert scorer.score([NewsItem(datetime.now(), "Gewinnwarnung")])[0] < 0


# ------------------------------------------------------------------ Marktphase & Klassifikation
def test_regime_detection():
    up = _series(100 * np.exp(np.linspace(0, 0.5, 400)))
    down = _series(100 * np.exp(np.linspace(0, -0.5, 400)))
    assert detect_regime(up).regime == Regime.BULL
    assert detect_regime(down).regime == Regime.BEAR
    assert detect_regime(None).regime == Regime.SIDEWAYS


def test_thresholds_depend_on_regime():
    cfg = Config()
    bull = MarketRegime(Regime.BULL, False, 0.8)
    bear = MarketRegime(Regime.BEAR, False, -0.8)
    assert classify(0.2, bull, cfg) == Recommendation.LONG
    assert classify(0.2, bear, cfg) == Recommendation.HOLD
    assert classify(-0.2, bull, cfg) == Recommendation.HOLD
    assert classify(-0.2, bear, cfg) == Recommendation.SHORT
    assert classify(-0.6, bear, cfg) == Recommendation.STRONG_SHORT


def test_interp_clamps():
    pts = [(0, -1), (1, 1)]
    assert interp(-5, pts) == -1 and interp(5, pts) == 1 and interp(0.5, pts) == 0


def test_rule_keys_unique():
    keys = [r.key for r in RULES]
    assert len(keys) == len(set(keys)) and len(keys) >= 30


# ------------------------------------------------------------------ Engine
class TruncatedProvider(DataProvider):
    """Schneidet alle Daten am Stichtag ab – Referenz für den Look-ahead-Test."""

    def __init__(self, inner, cutoff):
        self.inner, self.cutoff = inner, cutoff

    def prices(self, t, s, e):
        return self.inner.prices(t, s, min(e, self.cutoff))

    def info(self, t):
        return self.inner.info(t)

    def fundamentals(self, t):
        return [f for f in self.inner.fundamentals(t) if f.available_date <= self.cutoff]

    def market_sentiment(self, t):
        return [x for x in self.inner.market_sentiment(t) if x.available_date <= self.cutoff]

    def news(self, t, s, e):
        return [n for n in self.inner.news(t, s, e) if n.published.date() <= self.cutoff]


def test_no_lookahead(provider):
    d = date(2025, 3, 14)
    full = Analyzer(provider, BENCHMARK).analyze(SyntheticProvider.tickers(), d)
    cut = Analyzer(TruncatedProvider(provider, d), BENCHMARK).analyze(SyntheticProvider.tickers(), d)
    a = {x.ticker: x.total_score for x in full.analyses}
    b = {x.ticker: x.total_score for x in cut.analyses}
    assert a == pytest.approx(b)


def test_demo_dates_regimes_and_recommendations(analyzer):
    dates = demo_dates()
    bull = analyzer.analyze(SyntheticProvider.tickers(), dates["Bullenmarkt"])
    bear = analyzer.analyze(SyntheticProvider.tickers(), dates["Bärenmarkt"])
    assert bull.regime.regime == Regime.BULL
    assert bear.regime.regime == Regime.BEAR
    recs = {a.ticker: a for a in bear.analyses}
    assert recs["PLEITE"].recommendation.direction < 0
    assert recs["HYPE"].recommendation.direction < 0
    assert recs["VALUE"].total_score > recs["PLEITE"].total_score
    assert all(a.coverage > 0.9 for a in bear.analyses)
    shorts = [a for a in bear.analyses if a.recommendation.direction < 0]
    for a in shorts:
        assert a.trade_plan and a.trade_plan.stop_loss > a.price > a.trade_plan.take_profit
        assert a.trade_plan.position_value <= Config().capital * Config().max_position_pct + a.price


def test_squeeze_veto_applies(analyzer):
    rep = analyzer.analyze(SyntheticProvider.tickers(), demo_dates()["Bärenmarkt"])
    hype = next(a for a in rep.analyses if a.ticker == "HYPE")
    assert any("Squeeze" in n for n in hype.notes)
    assert hype.recommendation != hype.raw_recommendation


def test_unknown_ticker_is_reported_not_raised(analyzer):
    rep = analyzer.analyze(["QUALI", "GIBTSNICHT"], date(2024, 6, 28))
    assert [a.ticker for a in rep.analyses] == ["QUALI"]
    assert any("GIBTSNICHT" in w for w in rep.warnings)


# ------------------------------------------------------------------ Reports
def test_reports_and_diff(analyzer):
    d1, d2 = demo_dates()["Seitwärtsmarkt"], demo_dates()["Bärenmarkt"]
    r1 = analyzer.analyze(SyntheticProvider.tickers(), d1)
    r2 = analyzer.analyze(SyntheticProvider.tickers(), d2)
    md = to_markdown(r2)
    assert "## 1. Marktphase" in md and "Einzelanalysen" in md and "PLEITE" in md
    assert json.loads(to_json(r2))["regime"]["regime"] == "bear"
    assert "Empfehlung" in to_text(r2)
    changes = diff_with_previous(r2, to_dict(r1))
    assert any("Marktphase gewechselt" in c for c in changes)


# ------------------------------------------------------------------ CSV-Ablage
def test_csv_roundtrip(tmp_path, provider):
    tickers = ["QUALI", "PLEITE"]
    archive(provider, tickers + [BENCHMARK], tmp_path, history_days=800)
    d = date(2026, 3, 31)
    a = Analyzer(provider, BENCHMARK).analyze(tickers, d)
    b = Analyzer(CsvProvider(tmp_path), BENCHMARK).analyze(tickers, d)
    assert {x.ticker: x.total_score for x in a.analyses} == pytest.approx({x.ticker: x.total_score for x in b.analyses}, abs=1e-6)
    # erneutes Archivieren dupliziert nichts
    stats = archive(provider, tickers, tmp_path, history_days=800)
    assert all(v == 0 for k, v in stats.items() if k.endswith(":prices") or k.endswith(":fundamentals"))


# ------------------------------------------------------------------ Backtest & Zeitplan
def test_backtest_runs(provider):
    res = run_backtest(provider, ["QUALI", "VALUE", "HYPE", "PLEITE"], date(2025, 1, 2), date(2025, 12, 31),
                       BENCHMARK, interval_days=42, horizon_days=21)
    assert len(res.periods) >= 5
    assert set(res.records["empfehlung"]) <= {r.value for r in Recommendation}
    assert "Strategien" in backtest_markdown(res)


def test_scheduler_timing():
    assert parse_interval("6h") == timedelta(hours=6)
    assert parse_interval("1w") == timedelta(days=7)
    with pytest.raises(ValueError):
        parse_interval("morgen")
    fri_evening = datetime(2026, 11, 13, 23, 0)  # Freitag
    nxt = next_run(fri_evening, timedelta(days=1), "22:15", last_run=fri_evening)
    assert nxt.weekday() == 0 and (nxt.hour, nxt.minute) == (22, 15)
    mon = datetime(2026, 11, 16, 9, 0)
    assert next_run(mon, timedelta(hours=6)) == datetime(2026, 11, 16, 15, 0)


def test_overlapping_holding_periods_are_not_double_counted():
    from marktanalyse.backtest import _summarize

    # 12 Stichtage, Haltedauer = 3 × Abstand, jede Periode +3 % → pro Abstand ~+1 %
    per = pd.DataFrame({"datum": range(12), "regime": "bull", "index": 0.03, "long": 0.03, "short": np.nan,
                        "long_short": 0.03, "n_long": 1, "n_short": 0, "ic": np.nan})
    rec = pd.DataFrame({"datum": range(12), "ticker": "X", "regime": "bull", "score": 0.3, "empfehlung": "long",
                        "richtung": 1, "rendite": 0.03, "rendite_vs_index": 0.0})
    s = _summarize(rec, per, interval_days=21, horizon_days=63)
    assert s["index"]["gesamt"] == pytest.approx(1.03 ** 4 - 1, rel=1e-6)


# ------------------------------------------------------------------ Signal-Wächter
class _FakeSignalProvider(DataProvider):
    def __init__(self, frames, earnings):
        self.frames, self.earn = frames, earnings

    def prices(self, t, s, e):
        df = self.frames[t]
        return df.loc[pd.Timestamp(s):pd.Timestamp(e)]

    def earnings_history(self, t, limit=12):
        return self.earn.get(t)


def _frame(closes, idx):
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1e6})


def _announce(idx, pos, surprise=20.0):
    """Meldung nach US-Börsenschluss am Vortag -> Reaktionstag = idx[pos]."""
    ts = pd.Timestamp(idx[pos - 1].date()).tz_localize("America/New_York") + pd.Timedelta(hours=16, minutes=30)
    return pd.DataFrame({"estimate": [1.0], "reported": [1.2], "surprise": [surprise]}, index=[ts])


def _signal_setup(after_entry=110.0, n=500):
    from marktanalyse.signale import SignalRules

    idx = pd.bdate_range("2024-01-01", periods=n)
    react = 300  # Reaktionstag (Index)
    stock = np.full(n, 100.0)
    stock[react:] = 108.0  # +8 % am Meldetag
    stock[react + 1:] = after_entry
    prov = _FakeSignalProvider({"TEST": _frame(stock, idx), "^GSPC": _frame(np.full(n, 1000.0), idx)},
                               {"TEST": _announce(idx, react)})
    wl = pd.DataFrame({"ticker": ["TEST"], "isin": ["XX000"], "name": ["Testfirma"], "region": ["US"], "branche": [""]})
    return prov, wl, idx, react, SignalRules()


def _titles(prov, wl, day, **kw):
    from marktanalyse.signale import scan

    kw.setdefault("verkauf", True)
    return [a.titel for a in scan(prov, wl, day.date(), **kw).alerts]


def test_reaction_day_after_close_and_premarket():
    from marktanalyse.signale import reaction_day

    idx = pd.bdate_range("2026-11-02", periods=10)
    after = pd.Timestamp("2026-11-03 16:05", tz="America/New_York")
    pre = pd.Timestamp("2026-11-03 07:00", tz="America/New_York")
    assert idx[reaction_day(after, idx)] == pd.Timestamp("2026-11-04")
    assert idx[reaction_day(pre, idx)] == pd.Timestamp("2026-11-03")


def test_buy_mail_then_sell_mail_after_holding_period():
    from marktanalyse.signale import scan, subject, to_html

    prov, wl, idx, react, rules = _signal_setup()
    rep = scan(prov, wl, idx[react].date(), betrag=500, verkauf=True)
    assert subject(rep) == "Aktien-Signal – KAUFEN: Testfirma"
    assert "XX000" in to_html(rep) and "500 €" in to_html(rep)
    assert _titles(prov, wl, idx[react + 10]) == []
    # Einstieg am Folgetag, verkauft wird 63 Handelstage nach dem Signal
    assert _titles(prov, wl, idx[react + rules.hold_days]) == ["VERKAUFEN: Testfirma"]
    sell = scan(prov, wl, idx[react + rules.hold_days].date(), verkauf=True).alerts[0]
    assert "3 Monate" in sell.grund and sell.ergebnis == pytest.approx(0.0)


def test_emergency_stop_sends_single_sell_mail():
    prov, wl, idx, react, rules = _signal_setup(after_entry=108.0)
    df = prov.frames["TEST"].copy()
    df.loc[idx[react + 5]:, ["open", "high", "low", "close"]] = 85.0  # −21 % ab Tag 5
    prov.frames["TEST"] = df
    seen = {d: _titles(prov, wl, idx[d]) for d in (react + 4, react + 5, react + 6, react + rules.hold_days)}
    assert seen == {react + 4: [], react + 5: ["VERKAUFEN: Testfirma"], react + 6: [], react + rules.hold_days: []}


def test_new_buy_signal_while_holding_extends_without_mail():
    prov, wl, idx, react, rules = _signal_setup()
    second = react + 40  # zweites Kaufsignal, Aktie wird noch gehalten
    df = prov.frames["TEST"].copy()
    df.iloc[second:, :4] = 120.0  # +9 % am zweiten Meldetag
    prov.frames["TEST"] = df
    prov.earn["TEST"] = pd.concat([_announce(idx, react), _announce(idx, second)])
    assert _titles(prov, wl, idx[second]) == []  # kein zweites "KAUFEN"
    assert _titles(prov, wl, idx[react + rules.hold_days]) == []  # alte Haltedauer verlängert
    assert _titles(prov, wl, idx[second + rules.hold_days]) == ["VERKAUFEN: Testfirma"]


def test_sell_mails_only_for_buys_since_start_date():
    prov, wl, idx, react, rules = _signal_setup()
    start = idx[react + 1].date()  # Mails erst nach dem Kaufsignal eingerichtet
    assert _titles(prov, wl, idx[react + rules.hold_days], since=start) == []
    assert _titles(prov, wl, idx[react + rules.hold_days]) == ["VERKAUFEN: Testfirma"]


def test_weak_reaction_gives_no_signal():
    prov, wl, idx, react, _ = _signal_setup(after_entry=101.0)
    df = prov.frames["TEST"].copy()
    df.iloc[react:, :4] = 101.0  # nur +1 % Reaktion
    prov.frames["TEST"] = df
    assert _titles(prov, wl, idx[react]) == []


def test_buy_only_mode_never_sends_sell_mails():
    from marktanalyse.signale import scan, to_text

    prov, wl, idx, react, rules = _signal_setup(after_entry=80.0)  # Kurs bricht nach dem Kauf ein
    rep = scan(prov, wl, idx[react].date(), betrag=250)
    assert [a.titel for a in rep.alerts] == ["KAUFEN: Testfirma"] and "250 €" in to_text(rep)
    assert "behalten" in to_text(rep) and "verkaufen sollst" not in to_text(rep)
    for d in range(react + 1, react + rules.hold_days + 5):
        assert scan(prov, wl, idx[d].date()).alerts == []


def test_buy_only_mode_max_one_mail_per_stock_per_year():
    prov, wl, idx, react, rules = _signal_setup(n=700)
    second, third = react + 40, react + 300  # 2 Monate bzw. > 12 Monate später
    df = prov.frames["TEST"].copy()
    df.iloc[second:, :4] = 120.0
    df.iloc[third:, :4] = 132.0
    prov.frames["TEST"] = df
    prov.earn["TEST"] = pd.concat([_announce(idx, react), _announce(idx, second), _announce(idx, third)])
    assert _titles(prov, wl, idx[react], verkauf=False) == ["KAUFEN: Testfirma"]
    assert _titles(prov, wl, idx[second], verkauf=False) == []
    assert _titles(prov, wl, idx[third], verkauf=False) == ["KAUFEN: Testfirma"]
    # Signale vor dem Start der Mails zählen nicht für die Grenze
    assert _titles(prov, wl, idx[second], verkauf=False, since=idx[react + 1].date()) == ["KAUFEN: Testfirma"]
