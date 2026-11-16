"""Erkennung der Marktphase (steigend / fallend / seitwärts, plus Volatilitätsstress)."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .indicators import max_drawdown, period_return, realized_vol, sma
from .models import MarketRegime, Regime


def _clip(x: float) -> float:
    return float(max(-1.0, min(1.0, x)))


def detect_regime(bench_close: Optional[pd.Series], name: str = "Benchmark") -> MarketRegime:
    if bench_close is None or len(bench_close.dropna()) < 210:
        return MarketRegime(
            regime=Regime.SIDEWAYS,
            high_volatility=False,
            trend_score=0.0,
            description=f"Zu wenig Daten für {name} – Marktphase neutral angenommen.",
        )
    close = bench_close.dropna().astype(float)
    last = float(close.iloc[-1])
    s50 = sma(close, 50)
    s200 = sma(close, 200)
    sma50, sma200 = float(s50.iloc[-1]), float(s200.iloc[-1])
    slope200 = float(s200.iloc[-1] / s200.iloc[-21] - 1)
    ret_6m = period_return(close, 126) or 0.0
    dd = float(close.iloc[-1] / close.tail(252).max() - 1)

    components = {
        "Kurs vs. SMA200": _clip((last / sma200 - 1) / 0.05),
        "SMA50 vs. SMA200": _clip((sma50 / sma200 - 1) / 0.03),
        "Steigung SMA200 (20T)": _clip(slope200 / 0.015),
        "6-Monats-Rendite": _clip(ret_6m / 0.10),
    }
    trend = float(np.mean(list(components.values())))

    if trend > 0.25:
        regime = Regime.BULL
    elif trend < -0.25:
        regime = Regime.BEAR
    else:
        regime = Regime.SIDEWAYS
    # Technische Definition Bärenmarkt: >20 % unter Hoch und unter SMA200
    if dd <= -0.20 and last < sma200:
        regime = Regime.BEAR

    vol20 = realized_vol(close, 20)
    vol_hist = np.log(close).diff().rolling(20).std().dropna() * np.sqrt(252)
    vol_median = float(vol_hist.tail(756).median()) if not vol_hist.empty else None
    high_vol = bool(
        vol20 is not None
        and ((vol_median and vol20 > 1.5 * vol_median) or vol20 > 0.30)
    )

    desc = (
        f"{regime.label}: {name} {'über' if last > sma200 else 'unter'} der 200-Tage-Linie "
        f"({(last / sma200 - 1):+.1%}), 6M-Rendite {ret_6m:+.1%}, Abstand zum 52W-Hoch {dd:.1%}."
    )
    if high_vol:
        desc += f" Erhöhte Volatilität ({vol20:.0%} annualisiert) – Positionsgrößen reduzieren."
    return MarketRegime(
        regime=regime,
        high_volatility=high_vol,
        trend_score=trend,
        volatility=vol20,
        drawdown=dd,
        description=desc,
        details={**components, "Max. Drawdown (1 Jahr)": max_drawdown(close.tail(252)),
                 "Volatilität aktuell (20T)": vol20, "Volatilität Median (3 Jahre)": vol_median},
    )
