"""Timing-Signale für einzelne Aktien: Wann kaufen, wann verkaufen?

Die Regeln arbeiten nur mit Tageskursen und sind deshalb über Jahrzehnte
testbar (inkl. 2008, 2020, 2022). Alle Signale sind *Ereignisse* (ein Zustand
wechselt), damit jede Meldung genau einmal ausgelöst wird.

Signale
-------
Kauf
  * ``trendwende_auf``  Kurs schließt > 2 % über der 200-Tage-Linie, nachdem er
    zuvor > 2 % darunter lag (Hysterese gegen Fehlsignale).
  * ``ruecksetzer``     Im Aufwärtstrend steigt der RSI(14) wieder über 30
    (überverkaufter Rücksetzer dreht nach oben).
Verkauf
  * ``trendbruch``      Kurs schließt > 2 % unter der 200-Tage-Linie, nachdem er
    zuvor > 2 % darüber lag.
  * ``stop``            Trailing-Stop: Schlusskurs fällt um mehr als 3 ATR unter
    den höchsten Schlusskurs seit dem Einstieg.
  * ``erholung_short``  Im Abwärtstrend fällt der RSI(14) wieder unter 70
    (Erholung läuft aus) – nur für Hebelprodukte / Leerverkauf relevant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from .indicators import atr, rsi, sma


@dataclass
class TimingRules:
    trend_band: float = 0.02
    rsi_buy: float = 30.0
    rsi_short: float = 70.0
    atr_stop: float = 3.0
    cost_per_side: float = 0.001  # Spread/Gebühr je Kauf bzw. Verkauf (0,1 %)


EVENT_TEXT = {
    "trendwende_auf": ("Kauf", "Trendwende nach oben: Kurs über die 200-Tage-Linie ausgebrochen"),
    "ruecksetzer": ("Kauf", "Rücksetzer im Aufwärtstrend: RSI dreht aus dem überverkauften Bereich nach oben"),
    "trendbruch": ("Verkauf", "Trendbruch: Kurs unter die 200-Tage-Linie gefallen"),
    "stop": ("Verkauf", "Trailing-Stop ausgelöst: Kurs mehr als 3 ATR unter dem Hoch seit Einstieg"),
    "erholung_short": ("Short", "Erholung im Abwärtstrend läuft aus (RSI fällt unter 70)"),
}


def trend_state(close: pd.Series, sma200: pd.Series, band: float) -> pd.Series:
    """+1 Aufwärtstrend, −1 Abwärtstrend, 0 unbekannt – mit Hysterese-Band um die SMA200."""
    c, s = close.to_numpy(), sma200.to_numpy()
    out = np.zeros(len(c), dtype=int)
    state = 0
    for i in range(len(c)):
        if np.isnan(s[i]):
            state = 0
        elif c[i] > s[i] * (1 + band):
            state = 1
        elif c[i] < s[i] * (1 - band):
            state = -1
        out[i] = state
    return pd.Series(out, index=close.index)


def timing_frame(df: pd.DataFrame, rules: Optional[TimingRules] = None) -> pd.DataFrame:
    """Berechnet Indikatoren, Trendzustand und alle Ereignisse für jede Kerze."""
    r = rules or TimingRules()
    f = pd.DataFrame(index=df.index)
    f["open"], f["close"] = df["open"].astype(float), df["close"].astype(float)
    f["sma200"] = sma(f["close"], 200)
    f["rsi14"] = rsi(f["close"], 14)
    f["atr14"] = atr(df, 14)
    f["state"] = trend_state(f["close"], f["sma200"], r.trend_band)
    prev = f["state"].shift(1)
    f["trendwende_auf"] = (f["state"] == 1) & (prev == -1)
    f["trendbruch"] = (f["state"] == -1) & (prev == 1)
    f["ruecksetzer"] = (f["state"] == 1) & (f["rsi14"].shift(1) < r.rsi_buy) & (f["rsi14"] >= r.rsi_buy)
    f["erholung_short"] = (f["state"] == -1) & (f["rsi14"].shift(1) > r.rsi_short) & (f["rsi14"] <= r.rsi_short)
    return f


@dataclass
class Trade:
    entry_date: date
    entry: float
    reason: str
    exit_date: Optional[date] = None
    exit: Optional[float] = None
    exit_reason: str = ""
    stop: Optional[float] = None  # aktueller Trailing-Stop

    @property
    def ret(self) -> Optional[float]:
        return None if self.exit is None else self.exit / self.entry - 1


@dataclass
class Simulation:
    equity: pd.Series  # Strategie, normiert auf 1
    buy_hold: pd.Series
    trades: list[Trade]
    signals: pd.DataFrame  # Zeile je Ereignis (Datum, Art)
    open_trade: Optional[Trade] = None
    position: pd.Series = field(default_factory=pd.Series)


def simulate(df: pd.DataFrame, rules: Optional[TimingRules] = None, use_stop: bool = True) -> Simulation:
    """Long-Strategie: Einstieg bei Kauf-Ereignis, Ausstieg bei Trendbruch oder Trailing-Stop.

    Ausführung jeweils zum Eröffnungskurs des Folgetags (Signal kommt abends/morgens per Mail).
    """
    r = rules or TimingRules()
    f = timing_frame(df, r)
    o, c, a = f["open"].to_numpy(), f["close"].to_numpy(), f["atr14"].to_numpy()
    idx = f.index
    n = len(f)
    eq = np.ones(n)
    pos = np.zeros(n, dtype=int)
    trades: list[Trade] = []
    events = []
    cur: Optional[Trade] = None
    peak = 0.0
    pending: Optional[str] = None  # Auftrag für den nächsten Handelstag

    for i in range(1, n):
        ret = 0.0
        if pending and cur is None and pending in ("trendwende_auf", "ruecksetzer"):
            cur = Trade(idx[i].date(), o[i] * (1 + r.cost_per_side), pending)
            peak = c[i]
            ret = c[i] / cur.entry - 1
            trades.append(cur)
        elif pending and cur is not None and pending in ("trendbruch", "stop"):
            exit_px = o[i] * (1 - r.cost_per_side)
            ret = exit_px / c[i - 1] - 1
            cur.exit_date, cur.exit, cur.exit_reason = idx[i].date(), exit_px, pending
            cur = None
        elif cur is not None:
            ret = c[i] / c[i - 1] - 1
        pending = None
        eq[i] = eq[i - 1] * (1 + ret)
        pos[i] = 1 if cur is not None else 0

        # Signale am Schluss des Tages i auswerten
        row = f.iloc[i]
        if cur is None:
            for ev in ("trendwende_auf", "ruecksetzer"):
                if row[ev]:
                    pending = ev
                    events.append((idx[i], ev))
                    break
        else:
            peak = max(peak, c[i])
            if not np.isnan(a[i]):
                cur.stop = peak - r.atr_stop * a[i]
            if row["trendbruch"]:
                pending = "trendbruch"
                events.append((idx[i], "trendbruch"))
            elif use_stop and cur.stop is not None and c[i] < cur.stop:
                pending = "stop"
                events.append((idx[i], "stop"))
        if row["erholung_short"]:
            events.append((idx[i], "erholung_short"))

    bh = pd.Series(c / c[0], index=idx)
    sig = pd.DataFrame(events, columns=["datum", "signal"])
    return Simulation(pd.Series(eq, index=idx), bh, trades, sig, cur, pd.Series(pos, index=idx))


def perf(equity: pd.Series) -> dict:
    e = equity.dropna()
    if len(e) < 2:
        return {}
    years = (e.index[-1] - e.index[0]).days / 365.25
    rets = e.pct_change().dropna()
    cagr = e.iloc[-1] ** (1 / years) - 1 if years > 0 else 0.0
    vol = rets.std() * np.sqrt(252)
    return {
        "cagr": float(cagr),
        "vola": float(vol),
        "sharpe": float(cagr / vol) if vol else None,
        "max_dd": float((e / e.cummax() - 1).min()),
        "gesamt": float(e.iloc[-1] - 1),
        "jahre": years,
    }


def latest_signals(df: pd.DataFrame, rules: Optional[TimingRules] = None, lookback_days: int = 1) -> tuple[list[str], Simulation]:
    """Ereignisse der letzten ``lookback_days`` Handelstage (Standard: nur der letzte Tag)."""
    sim = simulate(df, rules)
    if sim.signals.empty:
        return [], sim
    last_days = set(df.index[-lookback_days:])
    return [s for d, s in zip(sim.signals["datum"], sim.signals["signal"]) if d in last_days], sim
