"""Technische Indikatoren (Trend, Momentum, Oszillatoren, Volatilität, Volumen)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Relative Strength Index nach Wilder."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return line, sig, line - sig


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0):
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std()
    upper, lower = mid + k * sd, mid - k * sd
    pct_b = (close - lower) / (upper - lower)
    bandwidth = (upper - lower) / mid
    return pct_b, bandwidth


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()


def realized_vol(close: pd.Series, n: int) -> Optional[float]:
    r = np.log(close).diff().dropna().tail(n)
    if len(r) < max(10, n // 2):
        return None
    return float(r.std() * np.sqrt(TRADING_DAYS))


def period_return(close: pd.Series, n: int, skip: int = 0) -> Optional[float]:
    """Rendite über n Handelstage, optional ohne die letzten ``skip`` Tage."""
    if len(close) < n + 1:
        return None
    end = close.iloc[-1 - skip]
    start = close.iloc[-1 - n]
    return float(end / start - 1)


def max_drawdown(close: pd.Series) -> Optional[float]:
    if close.empty:
        return None
    peak = close.cummax()
    return float((close / peak - 1).min())


def beta(stock: pd.Series, bench: pd.Series, n: int = TRADING_DAYS) -> Optional[float]:
    df = pd.concat([stock.pct_change(), bench.pct_change()], axis=1, join="inner").dropna().tail(n)
    if len(df) < 60:
        return None
    var = df.iloc[:, 1].var()
    if var == 0 or np.isnan(var):
        return None
    return float(df.iloc[:, 0].cov(df.iloc[:, 1]) / var)


def _last(s: pd.Series) -> Optional[float]:
    if s is None or s.empty:
        return None
    v = s.iloc[-1]
    return None if pd.isna(v) else float(v)


@dataclass
class TechnicalSnapshot:
    close: float
    bars: int
    sma20: Optional[float] = None
    sma50: Optional[float] = None
    sma200: Optional[float] = None
    sma200_slope: Optional[float] = None  # Veränderung SMA200 über 20 Tage
    cross_state: Optional[int] = None  # +1 SMA50 > SMA200, -1 darunter
    days_since_cross: Optional[int] = None
    rsi14: Optional[float] = None
    macd_hist: Optional[float] = None
    macd_hist_prev: Optional[float] = None
    macd_line: Optional[float] = None
    bb_pct_b: Optional[float] = None
    atr14: Optional[float] = None
    ret_1m: Optional[float] = None
    ret_3m: Optional[float] = None
    ret_6m: Optional[float] = None
    ret_12m: Optional[float] = None
    mom_12_1: Optional[float] = None
    vol_20d: Optional[float] = None
    vol_60d: Optional[float] = None
    max_dd_1y: Optional[float] = None
    dist_52w_high: Optional[float] = None  # (Kurs / Hoch - 1), <= 0
    dist_52w_low: Optional[float] = None  # (Kurs / Tief - 1), >= 0
    beta: Optional[float] = None
    rel_strength_6m: Optional[float] = None  # 6M-Rendite minus Benchmark
    obv_slope: Optional[float] = None  # normierte OBV-Steigung (20 Tage)
    volume_ratio: Optional[float] = None  # Ø-Volumen 5T / 50T
    avg_dollar_volume: Optional[float] = None  # Ø Handelsvolumen in Währung, 20T

    def to_dict(self) -> dict:
        return asdict(self)


def compute_technicals(df: pd.DataFrame, bench_close: Optional[pd.Series] = None) -> TechnicalSnapshot:
    """Berechnet alle technischen Kennzahlen zum letzten Datum in ``df``."""
    close = df["close"].astype(float)
    t = TechnicalSnapshot(close=float(close.iloc[-1]), bars=len(close))

    s20, s50, s200 = sma(close, 20), sma(close, 50), sma(close, 200)
    t.sma20, t.sma50, t.sma200 = _last(s20), _last(s50), _last(s200)
    if len(s200.dropna()) > 20:
        t.sma200_slope = float(s200.iloc[-1] / s200.iloc[-21] - 1)

    state = np.sign(s50 - s200).dropna()
    if not state.empty:
        t.cross_state = int(state.iloc[-1])
        changes = state.ne(state.shift()).to_numpy().nonzero()[0]
        last_change = changes[-1] if len(changes) else 0
        t.days_since_cross = int(len(state) - 1 - last_change) if last_change > 0 else None

    t.rsi14 = _last(rsi(close))
    line, _sig, hist = macd(close)
    t.macd_line = _last(line)
    hist = hist.dropna()
    if len(hist) >= 2:
        t.macd_hist, t.macd_hist_prev = float(hist.iloc[-1]), float(hist.iloc[-2])
    pct_b, _bw = bollinger(close)
    t.bb_pct_b = _last(pct_b)
    if {"high", "low"}.issubset(df.columns):
        t.atr14 = _last(atr(df))

    t.ret_1m = period_return(close, 21)
    t.ret_3m = period_return(close, 63)
    t.ret_6m = period_return(close, 126)
    t.ret_12m = period_return(close, 252)
    t.mom_12_1 = period_return(close, 252, skip=21)
    t.vol_20d = realized_vol(close, 20)
    t.vol_60d = realized_vol(close, 60)
    last_year = close.tail(TRADING_DAYS)
    t.max_dd_1y = max_drawdown(last_year)
    t.dist_52w_high = float(close.iloc[-1] / last_year.max() - 1)
    t.dist_52w_low = float(close.iloc[-1] / last_year.min() - 1)

    if "volume" in df.columns and df["volume"].sum() > 0:
        vol = df["volume"].astype(float)
        o = obv(df)
        if len(o) > 21:
            denom = vol.tail(20).sum() or 1.0
            t.obv_slope = float((o.iloc[-1] - o.iloc[-21]) / denom)
        if len(vol) >= 50 and vol.tail(50).mean() > 0:
            t.volume_ratio = float(vol.tail(5).mean() / vol.tail(50).mean())
        t.avg_dollar_volume = float((close * vol).tail(20).mean())

    if bench_close is not None and len(bench_close) > 130:
        b = bench_close.reindex(close.index).ffill()
        t.beta = beta(close, b)
        br = period_return(b.dropna(), 126)
        if br is not None and t.ret_6m is not None:
            t.rel_strength_6m = t.ret_6m - br
    return t
