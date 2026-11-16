"""Walk-Forward-Backtest: Analyse in regelmäßigen Abständen, danach Messung der Folgerendite.

Für jeden Stichtag sieht die Engine nur Daten bis zu diesem Tag. Die
Empfehlungen werden anschließend mit der tatsächlichen Kursentwicklung der
folgenden ``horizon_days`` Handelstage verglichen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Optional, Sequence

import numpy as np
import pandas as pd

from .data.base import CachedProvider, DataProvider
from .engine import Analyzer
from .models import Recommendation


@dataclass
class BacktestResult:
    records: pd.DataFrame  # eine Zeile je Stichtag & Ticker
    periods: pd.DataFrame  # eine Zeile je Stichtag (Portfolio-Renditen)
    summary: dict = field(default_factory=dict)


def _schedule(index: pd.DatetimeIndex, start: date, end: date, every: int) -> list[date]:
    days = index[(index >= pd.Timestamp(start)) & (index <= pd.Timestamp(end))]
    return [d.date() for d in days[::every]]


def run_backtest(
    provider: DataProvider,
    tickers: Sequence[str],
    start: date,
    end: date,
    benchmark: str,
    interval_days: int = 21,
    horizon_days: int = 21,
    config=None,
    progress: Optional[Callable[[date], None]] = None,
) -> BacktestResult:
    analyzer_cfg = config
    lookback = (config.price_history_days if config else 450) + 30
    cached = CachedProvider(provider, start - timedelta(days=lookback), end + timedelta(days=horizon_days * 2 + 10))
    analyzer = Analyzer(cached, benchmark=benchmark, config=analyzer_cfg)

    bench = cached.prices(benchmark, cached.start, cached.end)["close"]
    closes = {t: cached.prices(t, cached.start, cached.end)["close"] for t in tickers}

    def fwd(series: pd.Series, d: date) -> Optional[float]:
        s = series.loc[pd.Timestamp(d):]
        if len(s) <= horizon_days:
            return None
        return float(s.iloc[horizon_days] / s.iloc[0] - 1)

    rows, prow = [], []
    for d in _schedule(bench.index, start, end, interval_days):
        if progress:
            progress(d)
        rep = analyzer.analyze(tickers, d)
        bret = fwd(bench, d)
        if bret is None:
            break
        longs, shorts = [], []
        for a in rep.analyses:
            r = fwd(closes[a.ticker], d)
            if r is None:
                continue
            rows.append({
                "datum": d, "ticker": a.ticker, "regime": rep.regime.regime.value, "score": a.total_score,
                "empfehlung": a.recommendation.value, "richtung": a.recommendation.direction,
                "rendite": r, "rendite_vs_index": r - bret,
            })
            if a.recommendation.direction > 0:
                longs.append(r)
            elif a.recommendation.direction < 0:
                shorts.append(r)
        scores = [x["score"] for x in rows if x["datum"] == d]
        rets = [x["rendite"] for x in rows if x["datum"] == d]
        ic = pd.Series(scores).rank().corr(pd.Series(rets).rank()) if len(scores) >= 4 else np.nan  # Spearman ohne scipy
        l = float(np.mean(longs)) if longs else 0.0
        s = float(np.mean(shorts)) if shorts else 0.0
        n_sides = (1 if longs else 0) + (1 if shorts else 0)
        ls = (l - s) / n_sides if n_sides else 0.0  # je Seite 50 % Kapital, wenn beide besetzt
        prow.append({"datum": d, "regime": rep.regime.regime.value, "index": bret, "long": l if longs else np.nan,
                     "short": -s if shorts else np.nan, "long_short": ls, "n_long": len(longs),
                     "n_short": len(shorts), "ic": ic})

    records = pd.DataFrame(rows)
    periods = pd.DataFrame(prow)
    return BacktestResult(records, periods, _summarize(records, periods, interval_days))


def _summarize(rec: pd.DataFrame, per: pd.DataFrame, interval_days: int) -> dict:
    if rec.empty or per.empty:
        return {}
    out: dict = {"stichtage": len(per), "beobachtungen": len(rec)}
    by = {}
    for r in Recommendation:
        sub = rec[rec["empfehlung"] == r.value]
        if sub.empty:
            continue
        d = r.direction or 1
        hits = (sub["rendite"] * d > 0).mean() if r.direction else np.nan
        by[r.label] = {
            "anzahl": int(len(sub)),
            "ø_rendite": float(sub["rendite"].mean()),
            "ø_vs_index": float(sub["rendite_vs_index"].mean()),
            "trefferquote": float(hits) if r.direction else None,
        }
    out["nach_empfehlung"] = by
    per_year = 252 / interval_days

    def stats(series: pd.Series) -> dict:
        s = series.fillna(0.0)
        curve = (1 + s).cumprod()
        total = float(curve.iloc[-1] - 1)
        ann = float(curve.iloc[-1] ** (per_year / len(s)) - 1) if len(s) else 0.0
        vol = float(s.std() * np.sqrt(per_year)) if len(s) > 1 else 0.0
        dd = float((curve / curve.cummax() - 1).min())
        return {"gesamt": total, "p_a": ann, "vola": vol, "sharpe": ann / vol if vol else None, "max_dd": dd}

    out["long_short_strategie"] = stats(per["long_short"])
    out["nur_long"] = stats(per["long"])
    out["index"] = stats(per["index"])
    out["ø_information_coefficient"] = float(per["ic"].mean()) if per["ic"].notna().any() else None
    out["nach_marktphase"] = {
        reg: {"stichtage": int(len(g)), "ø_long_short": float(g["long_short"].mean()), "ø_index": float(g["index"].mean())}
        for reg, g in per.groupby("regime")
    }
    return out


def backtest_markdown(res: BacktestResult, title: str = "Backtest") -> str:
    s = res.summary
    if not s:
        return f"# {title}\n\nKeine auswertbaren Stichtage.\n"
    f = lambda x: "–" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x * 100:+.1f} %"  # noqa: E731
    L = [f"# {title}", "",
         f"{s['stichtage']} Stichtage, {s['beobachtungen']} Einzelbeobachtungen. "
         "Rendite = Kursentwicklung im Haltezeitraum nach dem Stichtag.", "",
         "## Ergebnis nach Empfehlung", "",
         "| Empfehlung | Anzahl | Ø Rendite | Ø vs. Index | Trefferquote |", "|---|---:|---:|---:|---:|"]
    for k, v in s["nach_empfehlung"].items():
        hit = "–" if v["trefferquote"] is None else f"{v['trefferquote']:.0%}"
        L.append(f"| {k} | {v['anzahl']} | {f(v['ø_rendite'])} | {f(v['ø_vs_index'])} | {hit} |")
    L += ["", "## Strategien", "", "| Strategie | Gesamt | p. a. | Volatilität | Sharpe | Max. Drawdown |",
          "|---|---:|---:|---:|---:|---:|"]
    for name, key in (("Long/Short nach Empfehlung", "long_short_strategie"), ("Nur Long-Empfehlungen", "nur_long"),
                      ("Index (Buy & Hold)", "index")):
        v = s[key]
        sh = "–" if v["sharpe"] is None else f"{v['sharpe']:.2f}"
        L.append(f"| {name} | {f(v['gesamt'])} | {f(v['p_a'])} | {v['vola'] * 100:.1f} % | {sh} | {f(v['max_dd'])} |")
    ic = s.get("ø_information_coefficient")
    L += ["", f"Ø Information Coefficient (Rangkorrelation Score ↔ Folgerendite): "
              f"{'–' if ic is None else f'{ic:+.3f}'}", "", "## Nach Marktphase", "",
          "| Marktphase | Stichtage | Ø Long/Short je Periode | Ø Index je Periode |", "|---|---:|---:|---:|"]
    for reg, v in s["nach_marktphase"].items():
        L.append(f"| {reg} | {v['stichtage']} | {f(v['ø_long_short'])} | {f(v['ø_index'])} |")
    L += ["", "> Ein Backtest ist kein Beweis für zukünftige Ergebnisse. Transaktionskosten, Leihgebühren "
              "und Slippage sind nicht berücksichtigt."]
    return "\n".join(L) + "\n"
