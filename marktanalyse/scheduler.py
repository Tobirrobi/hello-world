"""Regelmäßige Ausführung: Analyse im festen Takt, Reports speichern, Änderungen melden."""

from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Optional, Sequence

from .engine import Analyzer
from .report import diff_with_previous, load_previous, save_report, to_text

log = logging.getLogger(__name__)

_UNITS = {"m": 60, "h": 3600, "d": 86400, "w": 7 * 86400}


def parse_interval(text: str) -> timedelta:
    """'30m', '6h', '1d', '1w' -> timedelta."""
    m = re.fullmatch(r"\s*(\d+)\s*([mhdw])\s*", text.lower())
    if not m:
        raise ValueError(f"Ungültiges Intervall: {text!r} (Beispiele: 30m, 6h, 1d, 1w)")
    return timedelta(seconds=int(m.group(1)) * _UNITS[m.group(2)])


def next_run(
    now: datetime,
    interval: timedelta,
    at: Optional[str] = None,
    weekdays_only: bool = True,
    last_run: Optional[datetime] = None,
) -> datetime:
    """Nächster Ausführungszeitpunkt.

    Mit ``at`` ('HH:MM') und Tages-/Wochentakt wird zu fester Uhrzeit gestartet
    (z. B. täglich 22:15 nach US-Börsenschluss). Wochenenden werden übersprungen.
    """
    if at and interval >= timedelta(days=1):
        hh, mm = (int(x) for x in at.split(":"))
        earliest = max(now, last_run + interval - timedelta(hours=12)) if last_run else now
        cand = earliest.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if cand <= earliest:
            cand += timedelta(days=1)
    else:
        cand = max(now, last_run + interval) if last_run else now + interval
    while weekdays_only and cand.weekday() >= 5:
        cand += timedelta(days=1)
    return cand


def run_once(analyzer: Analyzer, tickers: Sequence[str], out_dir: str | Path, as_of: Optional[date] = None):
    as_of = as_of or date.today()
    rep = analyzer.analyze(tickers, as_of)
    rep.changes = diff_with_previous(rep, load_previous(out_dir, as_of))
    paths = save_report(rep, out_dir)
    return rep, paths


def run_schedule(
    analyzer_factory: Callable[[], Analyzer],
    tickers: Sequence[str],
    out_dir: str | Path,
    every: str = "1d",
    at: Optional[str] = None,
    max_runs: Optional[int] = None,
    on_report=None,
) -> None:
    interval = parse_interval(every)
    runs = 0
    while True:
        last_run = datetime.now()
        try:
            rep, paths = run_once(analyzer_factory(), tickers, out_dir)
            print(to_text(rep))
            print(f"\nGespeichert: {', '.join(str(p) for p in paths)}")
            if on_report:
                on_report(rep)
        except Exception:
            log.exception("Analyse-Lauf fehlgeschlagen")
        runs += 1
        if max_runs is not None and runs >= max_runs:
            return
        nxt = next_run(datetime.now(), interval, at, last_run=last_run)
        print(f"Nächste Analyse: {nxt:%d.%m.%Y %H:%M}")
        time.sleep(max(1.0, (nxt - datetime.now()).total_seconds()))
