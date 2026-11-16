"""Konfiguration: Gewichte, Schwellen und Risikoparameter je Marktphase.

Alle Werte lassen sich per TOML-Datei überschreiben (siehe ``config.example.toml``).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Optional

CATEGORIES = {
    "bewertung": "Bewertung",
    "qualitaet": "Qualität & Bilanz",
    "wachstum": "Wachstum",
    "trend": "Trend",
    "momentum": "Momentum",
    "oszillator": "Überkauft/Überverkauft",
    "risiko": "Risiko",
    "sentiment": "Nachrichten & Sentiment",
    "markt": "Markt & Größe",
}

# Kategorie-Gewichte je Marktphase. Im Bullenmarkt zählen Trend/Momentum mehr,
# im Bärenmarkt Qualität, Bilanz und Risiko, seitwärts Bewertung und Oszillatoren.
DEFAULT_CATEGORY_WEIGHTS = {
    "bull": {"bewertung": 0.12, "qualitaet": 0.10, "wachstum": 0.12, "trend": 0.18, "momentum": 0.18,
             "oszillator": 0.06, "risiko": 0.06, "sentiment": 0.12, "markt": 0.06},
    "bear": {"bewertung": 0.12, "qualitaet": 0.18, "wachstum": 0.08, "trend": 0.16, "momentum": 0.12,
             "oszillator": 0.06, "risiko": 0.12, "sentiment": 0.10, "markt": 0.06},
    "sideways": {"bewertung": 0.18, "qualitaet": 0.14, "wachstum": 0.10, "trend": 0.10, "momentum": 0.10,
                 "oszillator": 0.14, "risiko": 0.08, "sentiment": 0.10, "markt": 0.06},
}

# Schwellen für den Gesamtscore (-1..+1). Im Bärenmarkt braucht ein Long mehr
# Evidenz, ein Short weniger – im Bullenmarkt umgekehrt.
DEFAULT_THRESHOLDS = {
    "bull": {"long": 0.15, "strong_long": 0.40, "short": 0.30, "strong_short": 0.50},
    "bear": {"long": 0.30, "strong_long": 0.50, "short": 0.15, "strong_short": 0.40},
    "sideways": {"long": 0.20, "strong_long": 0.45, "short": 0.20, "strong_short": 0.45},
}

# Faktor auf das Risikobudget je Richtung und Marktphase
DEFAULT_EXPOSURE = {
    "bull": {"long": 1.0, "short": 0.5},
    "bear": {"long": 0.5, "short": 1.0},
    "sideways": {"long": 0.75, "short": 0.75},
}


@dataclass
class Config:
    category_weights: dict = field(default_factory=lambda: copy.deepcopy(DEFAULT_CATEGORY_WEIGHTS))
    thresholds: dict = field(default_factory=lambda: copy.deepcopy(DEFAULT_THRESHOLDS))
    exposure: dict = field(default_factory=lambda: copy.deepcopy(DEFAULT_EXPOSURE))
    signal_weights: dict = field(default_factory=dict)  # Überschreibt einzelne Signalgewichte (key -> weight)
    disabled_signals: list = field(default_factory=list)

    high_vol_threshold_add: float = 0.05  # Schwellen werden bei Stress strenger
    high_vol_size_factor: float = 0.5

    # Risikomanagement
    capital: float = 100_000.0
    risk_per_trade: float = 0.01  # 1 % des Kapitals pro Trade riskieren
    max_position_pct: float = 0.10
    atr_stop_multiple: float = 2.5
    atr_stop_multiple_high_vol: float = 3.0
    reward_risk: float = 2.0

    # Nachrichten
    news_lookback_days: int = 14
    news_half_life_days: float = 3.0

    # Datenalter
    max_fundamental_age_days: int = 200
    max_sentiment_age_days: int = 45
    price_history_days: int = 450

    # Vetos & Warnregeln
    squeeze_short_interest: float = 0.20
    min_dollar_volume_short: float = 1_000_000.0
    earnings_blackout_days: int = 7
    distress_altman_z: float = 1.81

    def category_weight(self, regime: str, category: str) -> float:
        return float(self.category_weights.get(regime, {}).get(category, 0.0))


def _deep_update(base: dict, upd: dict) -> dict:
    for k, v in upd.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v
    return base


def load_config(path: Optional[str | Path] = None) -> Config:
    cfg = Config()
    if not path:
        return cfg
    try:
        import tomllib  # Python >= 3.11
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib  # type: ignore
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    names = {f.name for f in fields(Config)}
    for key, value in data.items():
        if key not in names:
            raise ValueError(f"Unbekannter Konfigurationsschlüssel: {key}")
        current = getattr(cfg, key)
        if isinstance(current, dict) and isinstance(value, dict):
            _deep_update(current, value)
        else:
            setattr(cfg, key, value)
    return cfg
