"""Signal-Wächter: Kaufmails für gezieltes Einkaufen (Einsteiger-Regel).

Standard (nur Kaufmails)
    **Kaufmail → für den festen Betrag kaufen und langfristig behalten.**
    Es gibt keine Verkaufsmails.

Wann eine Kaufmail kommt
    Die Firma hat Quartalszahlen gemeldet, der Gewinn je Aktie lag ≥ 5 % über
    der Analystenschätzung **und** die Aktie stieg am Meldetag ≥ 3 % stärker als
    der Markt (Post-Earnings-Drift, siehe docs/SIGNALE.md). Höchstens eine
    Kaufmail pro Aktie innerhalb von 12 Monaten, damit sich das Depot nicht auf
    wenige Titel konzentriert.

Optional (``verkauf=True`` bzw. ``--mit-verkauf``)
    Zusätzlich Verkaufsmails nach 63 Handelstagen oder bei −15 % unter Kaufkurs.
    In diesem Modus gibt es keine 12-Monats-Grenze; ein neues Kaufsignal während
    des Haltens verlängert die Haltedauer ohne Mail.
"""

from __future__ import annotations

import html
import json
import logging
import os
import smtplib
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .data.base import DataProvider, normalize_prices

log = logging.getLogger(__name__)


@dataclass
class SignalRules:
    surprise_min: float = 5.0  # Gewinnüberraschung in %
    reaction_min: float = 0.03  # Kursreaktion am Meldetag, marktbereinigt
    hold_days: int = 63  # Haltedauer in Handelstagen
    emergency_stop: float = -0.15  # Notbremse ab Kaufkurs
    bench_us: str = "^GSPC"
    bench_other: str = "^GDAXI"
    cost_per_side: float = 0.001  # Spread/Gebühr in der Studie
    slots: int = 6  # Budget-Aufteilung für die Studie mit Verkauf (= Faustregel "Budget ÷ 6")
    min_days_between_buys: int = 365  # nur Kaufmodus: höchstens eine Kaufmail je Aktie in diesem Zeitraum


@dataclass
class Alert:
    art: str  # "kauf" | "verkauf"
    ticker: str
    name: str
    isin: str = ""
    kurs: Optional[float] = None
    waehrung: str = ""
    datum: Optional[date] = None
    grund: str = ""
    ergebnis: Optional[float] = None  # bei Verkauf: Kursentwicklung seit Kauf

    @property
    def titel(self) -> str:
        return f"{'KAUFEN' if self.art == 'kauf' else 'VERKAUFEN'}: {self.name}"


@dataclass
class SignalReport:
    as_of: date
    alerts: list[Alert]
    geprueft: int
    betrag: Optional[float] = None
    warnungen: list[str] = field(default_factory=list)
    mit_verkauf: bool = False

    @property
    def has_signals(self) -> bool:
        return bool(self.alerts)


@dataclass
class Position:
    """Eine Position, wie sie entsteht, wenn man jede Mail befolgt."""

    buy_pos: int
    buy_date: date
    hold_start: int
    surprise: float
    reaction: float
    entry: Optional[float] = None  # Eröffnungskurs am Tag nach dem Signal
    exit_pos: Optional[int] = None
    exit_reason: str = ""
    verlaengert: int = 0


# --------------------------------------------------------------------------- Hilfen
def load_watchlist(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, comment="#").fillna("")
    if "ticker" not in df.columns:
        raise ValueError("Beobachtungsliste braucht mindestens die Spalte 'ticker'")
    for col in ("isin", "name", "region", "branche"):
        if col not in df.columns:
            df[col] = ""
    return df


def reaction_day(ts: pd.Timestamp, index: pd.DatetimeIndex) -> Optional[int]:
    """Position des ersten Handelstags, an dem der Kurs auf die Meldung reagieren konnte.

    Yahoo liefert Meldezeitpunkte in New Yorker Zeit. Meldungen ab 16 Uhr New York
    (nach US-Börsenschluss, abends in Europa) wirken am nächsten Handelstag.
    """
    ts = pd.Timestamp(ts)
    if ts.tzinfo is not None:
        ny = ts.tz_convert("America/New_York")
        day = pd.Timestamp(ny.date())
        if ny.hour >= 16:
            day += pd.Timedelta(days=1)
    else:
        day = pd.Timestamp(ts.date())
    pos = int(index.searchsorted(day))
    return pos if pos < len(index) else None


def earnings_events(earnings: pd.DataFrame, px: pd.DataFrame, bench: pd.Series, rules: SignalRules) -> list[dict]:
    """Alle Quartalsmeldungen in der Kurshistorie ``px`` mit Überraschung, Reaktion und Kaufsignal-Flag."""
    out = []
    if earnings is None or earnings.empty or len(px) < 2:
        return out
    idx = px.index
    b = bench.reindex(idx).ffill()
    for ts, row in earnings.iterrows():
        surprise = row.get("surprise")
        if surprise is None or pd.isna(surprise):
            continue
        pos = reaction_day(ts, idx)
        if pos is None or pos < 1:
            continue
        react = px["close"].iloc[pos] / px["close"].iloc[pos - 1] - 1
        if pd.notna(b.iloc[pos]) and pd.notna(b.iloc[pos - 1]):
            react -= b.iloc[pos] / b.iloc[pos - 1] - 1
        out.append({
            "pos": pos, "datum": idx[pos].date(), "surprise": float(surprise), "reaktion": float(react),
            "eps": row.get("reported"), "schaetzung": row.get("estimate"),
            "kauf": bool(surprise >= rules.surprise_min and react >= rules.reaction_min),
        })
    return out


def replay(px: pd.DataFrame, events: list[dict], rules: SignalRules, since: Optional[date] = None) -> list[Position]:
    """Spielt die Regel „Kaufmail → kaufen & halten, Verkaufsmail → verkaufen“ über die Historie ab.

    Kaufsignale vor ``since`` werden ignoriert (dafür gab es noch keine Mail).
    """
    buys = {}
    for ev in events:
        if ev["kauf"]:
            buys.setdefault(ev["pos"], ev)
    o, c, idx = px["open"].to_numpy(), px["close"].to_numpy(), px.index
    positions: list[Position] = []
    cur: Optional[Position] = None
    for i in range(len(px)):
        if cur is not None and cur.entry is None and i == cur.buy_pos + 1:
            cur.entry = float(o[i]) if np.isfinite(o[i]) and o[i] > 0 else float(c[i - 1])
        if i in buys:
            ev = buys[i]
            if cur is None:
                if since is None or idx[i].date() >= since:
                    cur = Position(i, idx[i].date(), i, ev["surprise"], ev["reaktion"])
                    positions.append(cur)
            else:
                cur.hold_start = i  # neues Signal: weiter halten, 3 Monate beginnen neu
                cur.verlaengert += 1
            continue
        if cur is not None and cur.entry is not None:
            if c[i] < cur.entry * (1 + rules.emergency_stop):
                cur.exit_pos, cur.exit_reason, cur = i, "notbremse", None
            elif i - cur.hold_start >= rules.hold_days:
                cur.exit_pos, cur.exit_reason, cur = i, "haltedauer", None
    return positions


def _fmt_pct(x: float, digits: int = 1) -> str:
    return f"{x * 100:+.{digits}f} %".replace(".", ",")


def _fmt_px(x: float) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_eur(x: float) -> str:
    return f"{x:,.0f} €".replace(",", ".")


def currency_of(ticker: str) -> str:
    """Kurswährung aus dem Yahoo-Börsenkürzel (Trade Republic zeigt Kurse in EUR)."""
    suffix = ticker.rsplit(".", 1)[-1].upper() if "." in ticker else ""
    return {"DE": "EUR", "F": "EUR", "AS": "EUR", "PA": "EUR", "MI": "EUR", "MC": "EUR", "BR": "EUR",
            "CO": "DKK", "L": "GBp", "SW": "CHF", "ST": "SEK", "OL": "NOK"}.get(suffix, "USD" if not suffix else "")


def _buy_reason(surprise: float, reaction: float) -> str:
    return (f"Die Quartalszahlen waren deutlich besser als erwartet (Gewinn {surprise:+.0f} % über der Schätzung) "
            f"und die Aktie stieg {reaction * 100:.0f} % stärker als der Gesamtmarkt.")


def mailed_buys(events: list[dict], index: pd.DatetimeIndex, rules: SignalRules,
                since: Optional[date] = None) -> list[dict]:
    """Kaufsignale, für die im Kaufmodus eine Mail kommt (max. eine je Aktie in ``min_days_between_buys``)."""
    out, last_mail = [], None
    for ev in sorted((e for e in events if e["kauf"]), key=lambda e: e["pos"]):
        d = index[ev["pos"]].date()
        if since is not None and d < since:
            continue
        if last_mail is not None and (d - last_mail).days < rules.min_days_between_buys:
            continue
        out.append(ev)
        last_mail = d
    return out


# --------------------------------------------------------------------------- Prüfung
def scan(
    provider: DataProvider,
    watchlist: pd.DataFrame,
    as_of: Optional[date] = None,
    rules: Optional[SignalRules] = None,
    since: Optional[date] = None,
    betrag: Optional[float] = None,
    verkauf: bool = False,
) -> SignalReport:
    """Prüft alle Werte zum Stichtag (letzter abgeschlossener Handelstag ≤ ``as_of``).

    ``since``: Start der Mails – frühere Signale zählen weder für Verkäufe noch für die 12-Monats-Grenze.
    """
    r = rules or SignalRules()
    as_of = as_of or (date.today() - timedelta(days=1))
    start = as_of - timedelta(days=550)
    alerts: list[Alert] = []
    warnings: list[str] = []
    bench_cache: dict[str, pd.Series] = {}

    def prices(t: str) -> pd.DataFrame:
        return normalize_prices(provider.prices(t, start, as_of)).loc[: pd.Timestamp(as_of)]

    for _, w in watchlist.iterrows():
        t = w["ticker"]
        name = w.get("name") or t
        try:
            px = prices(t)
            if len(px) < 30:
                raise ValueError("zu wenige Kursdaten")
            bt = r.bench_us if w.get("region", "") == "US" else r.bench_other
            if bt not in bench_cache:
                bench_cache[bt] = prices(bt)["close"]
            earnings = provider.earnings_history(t) if hasattr(provider, "earnings_history") else None
            events = earnings_events(earnings, px, bench_cache[bt], r)
        except Exception as exc:
            warnings.append(f"{t}: {exc}")
            continue
        last = len(px) - 1
        cur_ccy = currency_of(t)
        if not verkauf:
            for ev in mailed_buys(events, px.index, r, since):
                if ev["pos"] == last:
                    alerts.append(Alert(
                        "kauf", t, name, w.get("isin", ""), float(px["close"].iloc[last]), cur_ccy,
                        px.index[last].date(), grund=_buy_reason(ev["surprise"], ev["reaktion"])))
            continue
        for p in replay(px, events, r, since):
            if p.buy_pos == last:
                alerts.append(Alert(
                    "kauf", t, name, w.get("isin", ""), float(px["close"].iloc[last]), cur_ccy, px.index[last].date(),
                    grund=_buy_reason(p.surprise, p.reaction),
                ))
            elif p.exit_pos == last:
                res = float(px["close"].iloc[last] / p.entry - 1) if p.entry else None
                grund = ("Die 3 Monate seit dem Kaufsignal sind vorbei." if p.exit_reason == "haltedauer" else
                         "Die Aktie ist mehr als 15 % unter deinen Kaufkurs gefallen. Verkaufen begrenzt den Verlust.")
                alerts.append(Alert("verkauf", t, name, w.get("isin", ""), float(px["close"].iloc[last]), cur_ccy,
                                    px.index[last].date(), grund=grund, ergebnis=res))
    # Verkäufe zuerst (Geld wird frei), dann Käufe
    alerts.sort(key=lambda a: 0 if a.art == "verkauf" else 1)
    return SignalReport(as_of, alerts, len(watchlist), betrag, warnings, verkauf)


# --------------------------------------------------------------------------- Mail
def subject(rep: SignalReport) -> str:
    parts = [a.titel for a in rep.alerts]
    return "Aktien-Signal – " + (" | ".join(parts) if parts else "keine Signale")


def _betrag_text(rep: SignalReport) -> str:
    if rep.betrag:
        return f"für {_fmt_eur(rep.betrag)}"
    if rep.mit_verkauf:
        return "für deinen festen Betrag pro Kauf (Faustregel: ein Sechstel deines Aktien-Budgets)"
    return "für deinen festen Betrag pro Kauf"


def _rule_text(rep: SignalReport) -> str:
    if rep.mit_verkauf:
        return "Kaufmail → kaufen und halten. Verkaufsmail → verkaufen."
    return "Kaufmail → für deinen festen Betrag kaufen und behalten."


def to_html(rep: SignalReport) -> str:
    e = html.escape
    blocks = []
    for a in rep.alerts:
        if a.art == "kauf":
            col = "#1a7f37"
            todo = (f"Trade Republic öffnen → nach <b>{e(a.isin or a.ticker)}</b> suchen → <b>Kaufen</b> "
                    f"{e(_betrag_text(rep))}.")
            after = ("Danach einfach <b>halten</b>. Du bekommst eine Mail, wenn du verkaufen sollst (meist nach etwa 3 Monaten)."
                     if rep.mit_verkauf else "Danach einfach <b>behalten</b> – langfristig, ohne Verkaufen.")
        else:
            col = "#cf222e"
            todo = f"Trade Republic öffnen → <b>{e(a.name)}</b> in deinem Depot antippen → <b>alles verkaufen</b>."
            after = ""
            if a.ergebnis is not None:
                after = f"Ergebnis seit dem Kauf: <b>{e(_fmt_pct(a.ergebnis, 0))}</b> (ungefähr, ohne Wechselkurs und Gebühren)."
        blocks.append(
            f'<div style="border-left:6px solid {col};padding:6px 14px;margin:16px 0">'
            f'<h2 style="margin:4px 0;color:{col}">{e(a.titel)}</h2>'
            f"<p><b>So geht's:</b> {todo}</p>"
            + (f"<p>{after}</p>" if after else "")
            + f'<p style="color:#666">Grund: {e(a.grund)}</p></div>'
        )
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;max-width:600px">'
        + "".join(blocks)
        + f'<p style="color:#888;font-size:12px">Deine Regel: {_rule_text(rep)} '
        f"Stand: Börsenschluss {rep.as_of:%d.%m.%Y}. Automatisch erzeugt, keine Anlageberatung.</p></div>"
    )


def to_text(rep: SignalReport) -> str:
    lines = []
    for a in rep.alerts:
        lines.append(a.titel)
        if a.art == "kauf":
            lines.append(f"So geht's: Trade Republic öffnen, nach {a.isin or a.ticker} suchen, kaufen {_betrag_text(rep)}.")
            lines.append("Danach einfach halten. Du bekommst eine Mail, wenn du verkaufen sollst (meist nach etwa 3 Monaten)."
                         if rep.mit_verkauf else "Danach einfach behalten - langfristig, ohne Verkaufen.")
        else:
            lines.append(f"So geht's: Trade Republic öffnen, {a.name} im Depot antippen, alles verkaufen.")
            if a.ergebnis is not None:
                lines.append(f"Ergebnis seit dem Kauf: {_fmt_pct(a.ergebnis, 0)} (ungefähr).")
        lines.append(f"Grund: {a.grund}")
        lines.append("")
    if not rep.alerts:
        lines.append("Keine Signale.")
    lines.append(f"Deine Regel: {_rule_text(rep)} Keine Anlageberatung.".replace("→", "->"))
    return "\n".join(lines)


def to_json(rep: SignalReport) -> str:
    d = asdict(rep)
    d.update({"anzahl": len(rep.alerts), "betreff": subject(rep), "html": to_html(rep), "text": to_text(rep)})
    return json.dumps(d, default=str, ensure_ascii=False, indent=2)


def send_smtp(rep: SignalReport, to: Optional[str] = None) -> bool:
    """Versand per SMTP. Konfiguration über Umgebungsvariablen:
    MAIL_TO, SMTP_HOST, SMTP_PORT (Standard 587), SMTP_USER, SMTP_PASSWORD, MAIL_FROM (optional)."""
    to = to or os.environ.get("MAIL_TO")
    host = os.environ.get("SMTP_HOST")
    if not to or not host:
        log.warning("SMTP nicht konfiguriert (MAIL_TO/SMTP_HOST fehlen) – keine Mail versendet.")
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject(rep)
    msg["From"] = os.environ.get("MAIL_FROM") or os.environ.get("SMTP_USER", to)
    msg["To"] = to
    msg.attach(MIMEText(to_text(rep), "plain", "utf-8"))
    msg.attach(MIMEText(to_html(rep), "html", "utf-8"))
    port = int(os.environ.get("SMTP_PORT") or "587")
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls()
        if os.environ.get("SMTP_USER"):
            s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
        s.send_message(msg)
    return True


# --------------------------------------------------------------------------- Studie
def _stats(equity: pd.Series) -> dict:
    e = equity.dropna()
    years = (e.index[-1] - e.index[0]).days / 365.25
    cagr = e.iloc[-1] ** (1 / years) - 1 if years > 0 else 0.0
    return {"cagr": float(cagr), "max_dd": float((e / e.cummax() - 1).min()), "gesamt": float(e.iloc[-1] - 1)}


def study(provider: DataProvider, watchlist: pd.DataFrame, start: date, end: Optional[date] = None,
          rules: Optional[SignalRules] = None) -> tuple[pd.DataFrame, str]:
    """Historische Prüfung: (1) jedes Kaufsignal einzeln, (2) Depot, wenn man jede Mail befolgt hätte."""
    r = rules or SignalRules()
    end = end or date.today()
    rows, trades, longrows = [], [], []
    closes: dict[str, pd.Series] = {}
    benches: dict[str, pd.Series] = {}
    for _, w in watchlist.iterrows():
        t = w["ticker"]
        try:
            px = normalize_prices(provider.prices(t, start, end))
            bt = r.bench_us if w.get("region", "") == "US" else r.bench_other
            if bt not in benches:
                benches[bt] = normalize_prices(provider.prices(bt, start, end))["close"]
            b = benches[bt].reindex(px.index).ffill()
            ev = earnings_events(provider.earnings_history(t, 100), px, benches[bt], r)
        except Exception as exc:
            log.warning("%s: %s", t, exc)
            continue
        closes[t] = px["close"]
        mailed = {e["pos"] for e in mailed_buys(ev, px.index, r)}
        n = len(px)
        for e in ev:  # Langfrist: kaufen am Folgetag, nie verkaufen
            i = e["pos"] + 1
            if i >= n:
                continue
            entry, b0 = px["open"].iloc[i], b.iloc[i - 1]
            lr = {"ticker": t, "mail": e["pos"] in mailed, "kauf": e["kauf"]}
            for h, lab in ((252, "1J"), (504, "2J"), (756, "3J")):
                if i + h < n:
                    lr[lab] = px["close"].iloc[i + h] / entry - 1 - (b.iloc[i + h] / b0 - 1)
            yrs = (px.index[-1] - px.index[i]).days / 365.25
            if yrs > 0.5:
                lr["heute"] = ((px["close"].iloc[-1] / entry) / (b.iloc[-1] / b0)) ** (1 / yrs) - 1
                lr["endwert"], lr["endwert_index"] = px["close"].iloc[-1] / entry, b.iloc[-1] / b0
            longrows.append(lr)
        for e in ev:
            p = e["pos"]
            if p + r.hold_days >= len(px):
                continue
            entry = px["open"].iloc[p + 1]
            exit_close = px["close"].iloc[p + r.hold_days]
            stop_exit = None
            for j in range(p + 1, p + r.hold_days):
                if px["close"].iloc[j] < entry * (1 + r.emergency_stop):
                    stop_exit = px["open"].iloc[j + 1]
                    break
            rows.append({**{k: v for k, v in e.items() if k != "pos"}, "ticker": t,
                         "rendite": exit_close / entry - 1,
                         "rendite_notbremse": (stop_exit if stop_exit is not None else exit_close) / entry - 1,
                         "markt": b.iloc[p + r.hold_days] / b.iloc[p] - 1})
        for pos in replay(px, ev, r):
            if pos.exit_pos is None or pos.exit_pos + 1 >= len(px):
                continue
            trades.append({"ticker": t, "kauf": px.index[pos.buy_pos + 1], "verkauf": px.index[pos.exit_pos + 1],
                           "entry": pos.entry, "exit": float(px["open"].iloc[pos.exit_pos + 1]),
                           "grund": pos.exit_reason})
    df = pd.DataFrame(rows)
    if df.empty:
        return df, "Keine Ereignisse gefunden."
    df["ueber_markt"] = df["rendite"] - df["markt"]
    buy = df[df["kauf"]]

    def line(name, g):
        return (f"| {name} | {len(g)} | {g['rendite'].mean() * 100:+.1f} % | {g['ueber_markt'].mean() * 100:+.1f} % | "
                f"{(g['rendite'] > 0).mean():.0%} | {g['rendite'].min() * 100:+.0f} % |")

    lg = pd.DataFrame(longrows)
    md = []
    if not lg.empty:
        def lline(name, g):
            cells = " | ".join(f"{g[lab].median() * 100:+.0f} %" if lab in g and g[lab].notna().any() else "–"
                               for lab in ("1J", "2J", "3J"))
            return f"| {name} | {len(g)} | {cells} | {g['heute'].median() * 100:+.1f} % |"

        mail = lg[lg["mail"]]
        md += ["### Gezielt kaufen und behalten (Standard-Modus)", "",
               "Vorsprung gegenüber dem Markt (Median) nach einem Kauf am Morgen nach der Meldung:", "",
               "| Kauf nach … | Fälle | nach 1 Jahr | nach 2 Jahren | nach 3 Jahren | bis heute, pro Jahr |",
               "|---|---:|---:|---:|---:|---:|",
               lline("**Kaufmail** (max. 1 je Aktie in 12 Monaten)", mail),
               lline("jedem Kaufsignal (ohne Begrenzung)", lg[lg["kauf"]]),
               lline("Quartalszahlen ohne Signal", lg[~lg["kauf"]])]
        if "endwert" in lg and len(mail):
            other = lg[~lg["kauf"]].dropna(subset=["endwert"])
            md += ["", "Endwert, wenn man bei jedem Kauf denselben Betrag investiert und bis heute gehalten hätte – im "
                       "Verhältnis zu: derselbe Betrag am selben Tag in den Index (S&P 500 bzw. DAX):", "",
                   f"* Kaufmails: **{mail['endwert'].sum() / mail['endwert_index'].sum():.1f}-mal** so viel wie der Index",
                   f"* Käufe nach Quartalszahlen ohne Signal: {other['endwert'].sum() / other['endwert_index'].sum():.1f}-mal "
                   "so viel wie der Index",
                   "", "Beide Werte sind stark geschönt, weil die Liste die Gewinner von heute enthält. Aussagekräftig ist "
                       "nur der Vergleich der beiden Zeilen miteinander."]
        md.append("")
    md += ["### Optionaler Modus mit Verkauf: jedes Kaufsignal einzeln (3 Monate gehalten)", "",
          "| Gruppe | Fälle | Ø Rendite 3 Mon. | Ø vs. Markt | Anteil positiv | schlechtester Fall |",
          "|---|---:|---:|---:|---:|---:|", line("Alle Quartalszahlen", df), line("**Kaufsignal**", buy)]
    if len(buy):
        g = buy.assign(rendite=buy["rendite_notbremse"])
        md.append(line("Kaufsignal mit Notbremse −15 %", g.assign(ueber_markt=g["rendite"] - g["markt"])))

    # ---- Depot-Simulation: Budget in r.slots Teile, jede Mail befolgt
    tr = pd.DataFrame(trades)
    if not tr.empty:
        tr = tr.sort_values("kauf")
        cal = pd.DatetimeIndex(sorted(set().union(*[s.index for s in closes.values()])))
        cal = cal[cal >= tr["kauf"].min()]
        px_all = pd.DataFrame({t: s.reindex(cal).ffill() for t, s in closes.items()})
        cash, hold, skipped, taken = 1.0, {}, 0, 0
        eq, inv = [], []
        entries = {d: g for d, g in tr.groupby("kauf")}
        exits = {d: g for d, g in tr.groupby("verkauf")}
        for d in cal:
            if d in exits:
                for _, x in exits[d].iterrows():
                    key = (x["ticker"], x["kauf"])
                    if key in hold:
                        val, last_px = hold.pop(key)
                        cash += val * x["exit"] / last_px * (1 - r.cost_per_side)
            for key in list(hold):
                val, last_px = hold[key]
                now = px_all.at[d, key[0]]
                if pd.notna(now):
                    hold[key] = (val * now / last_px, now)
            total = cash + sum(v for v, _ in hold.values())
            if d in entries:
                for _, x in entries[d].iterrows():
                    if len(hold) >= r.slots:
                        skipped += 1
                        continue
                    alloc = min(cash, total / r.slots)
                    cash -= alloc
                    now = px_all.at[d, x["ticker"]]
                    hold[(x["ticker"], x["kauf"])] = (alloc * (1 - r.cost_per_side) * now / x["entry"], now)
                    taken += 1
            eq.append(cash + sum(v for v, _ in hold.values()))
            inv.append(1 - cash / eq[-1] if eq[-1] else 0.0)
        equity = pd.Series(eq, index=cal)
        s = _stats(equity)
        md += ["", f"### Optionaler Modus mit Verkauf: Depot, wenn man jede Mail befolgt hätte (ab {cal[0]:%m/%Y}, Budget ÷ {r.slots}, "
                   "0,1 % Kosten je Kauf/Verkauf, Cash ohne Zinsen)", "",
               "| | Rendite p. a. | Gesamt | größter Einbruch |", "|---|---:|---:|---:|",
               f"| **Signal-Strategie** ({taken} Käufe, {skipped} mangels freiem Budgetteil ausgelassen) | "
               f"{s['cagr'] * 100:.1f} % | {s['gesamt'] * 100:+.0f} % | {s['max_dd'] * 100:.0f} % |"]
        ew = px_all.pct_change().mean(axis=1).fillna(0).add(1).cumprod()
        s2 = _stats(ew)
        md.append(f"| Alle Listenwerte gleichgewichtet halten | {s2['cagr'] * 100:.1f} % | {s2['gesamt'] * 100:+.0f} % | "
                  f"{s2['max_dd'] * 100:.0f} % |")
        for bt, label in ((r.bench_us, "S&P 500 halten (ohne Dividenden)"), (r.bench_other, "DAX halten")):
            bs = benches.get(bt)
            if bs is not None:
                bs = bs.reindex(cal).ffill().dropna()
                s3 = _stats(bs / bs.iloc[0])
                md.append(f"| {label} | {s3['cagr'] * 100:.1f} % | {s3['gesamt'] * 100:+.0f} % | {s3['max_dd'] * 100:.0f} % |")
        md += ["", f"Im Schnitt waren {np.mean(inv):.0%} des Budgets investiert, der Rest lag als Cash bereit "
                   "(z. B. auf dem Verrechnungskonto mit Zinsen – in der Simulation nicht berücksichtigt)."]
    return df, "\n".join(md)
