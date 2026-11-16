"""Signal-Wächter: tägliche Prüfung einer Beobachtungsliste, Meldung nur bei deutlichen Signalen.

Welche Signale – und warum (Details: docs/SIGNALE.md)
-----------------------------------------------------
Klassische Chartsignale (Trendwende, Rücksetzer, Golden Cross, 52-Wochen-Hoch,
Trendbruch) hatten bei der Beobachtungsliste 2001–2026 **keinen** messbaren
Vorsprung. Belegt waren dagegen:

1. **Kauf nach starken Quartalszahlen** (Post-Earnings-Drift): Gewinn je Aktie
   ≥ 5 % über der Analystenschätzung **und** Kurs am Meldetag ≥ 3 % besser als
   der Markt. Danach lief die Aktie im Schnitt 3 Monate lang weiter besser als
   der Markt.
2. **Verkauf nach Ende der Haltedauer** (63 Handelstage ≈ 3 Monate) bzw. bei
   der **Notbremse** (−15 % unter Einstand).
3. **Marktampel** (MSCI World vs. 200-Tage-Linie mit 2 % Puffer): senkte die
   großen Einbrüche deutlich. Rot = neue Käufe zurückstellen / Risiko senken,
   Grün = wieder investieren.

Short-Signale werden nicht gemeldet: Keines hatte in den Tests einen Vorteil, und
bei Trade Republic wäre Shorten nur über Hebelprodukte möglich.
"""

from __future__ import annotations

import html
import json
import logging
import os
import smtplib
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import pandas as pd

from .data.base import DataProvider, normalize_prices
from .timing import trend_state
from .indicators import sma

log = logging.getLogger(__name__)


@dataclass
class SignalRules:
    surprise_min: float = 5.0  # Gewinnüberraschung in %
    reaction_min: float = 0.03  # Kursreaktion am Meldetag, marktbereinigt
    hold_days: int = 63  # Haltedauer in Handelstagen
    emergency_stop: float = -0.15  # Notbremse ab Einstand
    market_ticker: str = "URTH"  # iShares MSCI World (Proxy für den Weltmarkt)
    market_name: str = "MSCI World"
    trend_band: float = 0.02
    bench_us: str = "^GSPC"
    bench_other: str = "^GDAXI"


@dataclass
class Alert:
    art: str  # "kauf" | "verkauf" | "markt"
    titel: str
    ticker: str = ""
    name: str = ""
    isin: str = ""
    kurs: Optional[float] = None
    datum: Optional[date] = None
    details: list[str] = field(default_factory=list)
    stop: Optional[float] = None
    halten_bis: Optional[date] = None


@dataclass
class SignalReport:
    as_of: date
    alerts: list[Alert]
    marktampel: str  # "grün" | "rot" | "unbekannt"
    marktampel_text: str
    geprueft: int
    warnungen: list[str] = field(default_factory=list)

    @property
    def has_signals(self) -> bool:
        return bool(self.alerts)


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


def earnings_events(
    earnings: pd.DataFrame, px: pd.DataFrame, bench: pd.Series, rules: SignalRules
) -> list[dict]:
    """Alle Kaufsignale nach Quartalszahlen in der Kurshistorie ``px``."""
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
            "kauf": surprise >= rules.surprise_min and react >= rules.reaction_min,
        })
    return out


def _fmt_pct(x: float, digits: int = 1) -> str:
    return f"{x * 100:+.{digits}f} %".replace(".", ",")


def _fmt_px(x: float) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# --------------------------------------------------------------------------- Prüfung
def scan(
    provider: DataProvider,
    watchlist: pd.DataFrame,
    as_of: Optional[date] = None,
    rules: Optional[SignalRules] = None,
    analyzer=None,
) -> SignalReport:
    """Prüft alle Werte zum Stichtag. Es zählen nur abgeschlossene Handelstage ≤ ``as_of``."""
    r = rules or SignalRules()
    as_of = as_of or (date.today() - timedelta(days=1))
    start = as_of - timedelta(days=500)
    alerts: list[Alert] = []
    warnings: list[str] = []

    def prices(t: str) -> pd.DataFrame:
        df = normalize_prices(provider.prices(t, start, as_of))
        return df.loc[: pd.Timestamp(as_of)]

    # ---- Marktampel
    ampel, ampel_text = "unbekannt", "Marktdaten nicht verfügbar"
    try:
        m = prices(r.market_ticker)
        st = trend_state(m["close"], sma(m["close"], 200), r.trend_band)
        if len(st) > 1 and st.iloc[-1] != 0:
            ampel = "grün" if st.iloc[-1] > 0 else "rot"
            dist = m["close"].iloc[-1] / sma(m["close"], 200).iloc[-1] - 1
            ampel_text = (f"{r.market_name} {_fmt_pct(dist)} {'über' if dist > 0 else 'unter'} der 200-Tage-Linie "
                          f"(Stand {m.index[-1]:%d.%m.%Y})")
            if st.iloc[-2] != st.iloc[-1] and st.iloc[-2] != 0:
                if st.iloc[-1] > 0:
                    alerts.append(Alert("markt", f"Marktampel springt auf GRÜN ({r.market_name})", r.market_ticker,
                                        r.market_name, kurs=float(m['close'].iloc[-1]), datum=m.index[-1].date(),
                                        details=[ampel_text, "Der Weltmarkt ist wieder im Aufwärtstrend: Käufe und "
                                                 "Sparpläne wieder normal ausführen, abgesicherte Positionen wieder aufbauen."]))
                else:
                    alerts.append(Alert("markt", f"Marktampel springt auf ROT ({r.market_name})", r.market_ticker,
                                        r.market_name, kurs=float(m['close'].iloc[-1]), datum=m.index[-1].date(),
                                        details=[ampel_text, "Der Weltmarkt hat seinen langfristigen Aufwärtstrend "
                                                 "verlassen: neue Einzelkäufe zurückstellen, Risiko reduzieren "
                                                 "(z. B. Gewinne sichern, Cash-Quote erhöhen). Historisch halbierte "
                                                 "diese Regel die großen Einbrüche."]))
    except Exception as exc:
        warnings.append(f"Marktampel ({r.market_ticker}): {exc}")

    # ---- Einzelwerte
    bench_cache: dict[str, pd.Series] = {}
    buy_tickers = []
    for _, w in watchlist.iterrows():
        t = w["ticker"]
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
        name = w.get("name") or t
        buys = [ev for ev in events if ev["kauf"] and ev["pos"] <= last]
        today = [ev for ev in buys if ev["pos"] == last]
        prior = [ev for ev in buys if ev["pos"] < last]
        # jüngstes früheres Kaufsignal: nur dieses zählt für Notbremse/Haltedauer (neues Signal verlängert)
        ref = prior[-1] if prior else None

        for ev in today:  # Signal am letzten Handelstag -> Kauf zur nächsten Eröffnung
            p = ev["pos"]
            stop = px["close"].iloc[p] * (1 + r.emergency_stop)
            until = (pd.Timestamp(ev["datum"]) + pd.tseries.offsets.BDay(r.hold_days)).date()
            details = [
                f"Gewinn je Aktie {ev['eps']} statt erwartet {ev['schaetzung']} "
                f"(Überraschung {ev['surprise']:+.1f} %)".replace(".", ","),
                f"Kursreaktion am Meldetag {_fmt_pct(ev['reaktion'])} gegenüber dem Markt",
                "Historisch (279 Fälle seit 2002 bei diesen Aktien): in den 3 Monaten danach Ø +6,7 %, "
                "das sind +5,1 % mehr als der Markt (nach normalen Quartalszahlen: +2,1 %). "
                "In 67 % der Fälle positiv, schlechtester Fall −47 % (mit Notbremse −26 %).",
            ]
            if ref is not None and last - ref["pos"] <= r.hold_days:
                details.append(f"Falls du die Aktie aus dem Kaufsignal vom {ref['datum']:%d.%m.%Y} noch hältst: "
                               "weiter halten – die Haltedauer beginnt neu.")
            alerts.append(Alert("kauf", f"KAUFEN: {name} nach starken Quartalszahlen", t, name, w.get("isin", ""),
                                float(px["close"].iloc[p]), ev["datum"], details=details, stop=float(stop),
                                halten_bis=until))
            buy_tickers.append(t)

        if ref is not None and not today:
            p = ref["pos"]
            held = px.iloc[p + 1:]  # ab Einstieg (Eröffnung am Folgetag)
            entry = float(held["open"].iloc[0])
            days_held = last - p
            stop_px = entry * (1 + r.emergency_stop)
            closes = held["close"].iloc[: r.hold_days]
            broke = closes[closes < stop_px]
            stopped_before = len(broke) and broke.index[0] < px.index[last]
            if len(broke) and broke.index[0] == px.index[last] and days_held <= r.hold_days:
                alerts.append(Alert(
                    "verkauf", f"VERKAUFEN: {name} – Notbremse ausgelöst", t, name, w.get("isin", ""),
                    float(px["close"].iloc[last]), px.index[last].date(),
                    details=[f"Kaufsignal vom {ref['datum']:%d.%m.%Y}, Einstand ca. {_fmt_px(entry)}",
                             f"Schlusskurs {_fmt_px(float(px['close'].iloc[last]))} = "
                             f"{_fmt_pct(px['close'].iloc[last] / entry - 1)} – Verlust begrenzen."],
                ))
            elif days_held == r.hold_days and not stopped_before:
                perf = px["close"].iloc[last] / entry - 1
                alerts.append(Alert(
                    "verkauf", f"VERKAUFEN: {name} – Haltedauer von 3 Monaten erreicht", t, name, w.get("isin", ""),
                    float(px["close"].iloc[last]), px.index[last].date(),
                    details=[f"Kaufsignal vom {ref['datum']:%d.%m.%Y}, Einstand ca. {_fmt_px(entry)}",
                             f"Ergebnis seit Einstieg: {_fmt_pct(perf)}",
                             "Der typische Nachlauf nach Quartalszahlen ist vorbei – Position schließen "
                             "(oder bewusst als Langfrist-Investment weiterhalten)."],
                ))

    # ---- Kontext aus der Fundamentalanalyse für neue Kaufsignale
    if analyzer is not None and buy_tickers:
        try:
            rep = analyzer.analyze(buy_tickers, as_of)
            by_t = {a.ticker: a for a in rep.analyses}
            for al in alerts:
                a = by_t.get(al.ticker)
                if al.art != "kauf" or a is None:
                    continue
                f = a.metrics["fundamental"]
                pe = "Verlust" if f.get("eps_negative") else (f"{f['pe']:.1f}".replace(".", ",") if f.get("pe") else "–")
                al.details.append(f"Gesamtanalyse: {a.recommendation.label}, Score {a.total_score:+.2f}, KGV {pe}")
                z = f.get("altman_z")
                if z is not None and z < 1.81:
                    al.details.append(f"⚠️ Altman Z {z:.2f}: erhöhtes Insolvenzrisiko – Position klein halten.")
                for n in a.notes:
                    al.details.append(f"⚠️ {n}")
        except Exception as exc:
            warnings.append(f"Fundamentalanalyse: {exc}")

    if ampel == "rot":
        for al in alerts:
            if al.art == "kauf":
                al.details.append("⚠️ Marktampel ist ROT – nur mit kleiner Position oder abwarten.")
    return SignalReport(as_of, alerts, ampel, ampel_text, len(watchlist), warnings)


# --------------------------------------------------------------------------- Mail
def subject(rep: SignalReport) -> str:
    k = [a.name for a in rep.alerts if a.art == "kauf"]
    v = [a.name for a in rep.alerts if a.art == "verkauf"]
    m = [a.titel for a in rep.alerts if a.art == "markt"]
    parts = []
    if m:
        parts.append(m[0])
    if k:
        parts.append("Kauf: " + ", ".join(k))
    if v:
        parts.append("Verkauf: " + ", ".join(v))
    return "Marktanalyse – " + " | ".join(parts) if parts else "Marktanalyse – keine Signale"


def to_html(rep: SignalReport) -> str:
    e = html.escape
    color = {"kauf": "#1a7f37", "verkauf": "#cf222e", "markt": "#9a6700"}
    blocks = []
    for a in rep.alerts:
        rows = "".join(f"<li>{e(d)}</li>" for d in a.details)
        meta = []
        if a.isin:
            meta.append(f"ISIN <b>{e(a.isin)}</b> (in Trade Republic suchen)")
        if a.ticker:
            meta.append(f"Ticker {e(a.ticker)}")
        if a.kurs is not None:
            meta.append(f"Schlusskurs {e(_fmt_px(a.kurs))}" + (f" am {a.datum:%d.%m.%Y}" if a.datum else ""))
        plan = ""
        if a.art == "kauf":
            plan = (f"<p><b>Plan:</b> heute kaufen · Notbremse (Stop-Loss) bei <b>{e(_fmt_px(a.stop))}</b> (−15 %) · "
                    f"Haltedauer bis ca. <b>{a.halten_bis:%d.%m.%Y}</b> – du bekommst dann eine Verkaufsmail.</p>")
        blocks.append(
            f'<div style="border-left:4px solid {color[a.art]};padding:4px 12px;margin:14px 0">'
            f'<h3 style="margin:4px 0;color:{color[a.art]}">{e(a.titel)}</h3>'
            f'<p style="margin:4px 0;color:#555">{" · ".join(meta)}</p><ul>{rows}</ul>{plan}</div>'
        )
    ampel_col = {"grün": "#1a7f37", "rot": "#cf222e"}.get(rep.marktampel, "#555")
    warn = "".join(f"<li>{e(w)}</li>" for w in rep.warnungen)
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;max-width:640px">'
        f"<h2>Signale zum {rep.as_of:%d.%m.%Y}</h2>"
        f'<p>Marktampel: <b style="color:{ampel_col}">{e(rep.marktampel.upper())}</b> – {e(rep.marktampel_text)}</p>'
        + "".join(blocks)
        + (f"<p style='color:#888'>Datenhinweise:</p><ul style='color:#888'>{warn}</ul>" if warn else "")
        + f"<p style='color:#888;font-size:12px'>Geprüft: {rep.geprueft} Werte der Beobachtungsliste. "
        "Automatisch erzeugte, regelbasierte Signale – keine Anlageberatung. Ausführung zum Eröffnungskurs, "
        "Ordergebühren und Steuern sind nicht berücksichtigt.</p></div>"
    )


def to_text(rep: SignalReport) -> str:
    lines = [f"Signale zum {rep.as_of:%d.%m.%Y}", f"Marktampel: {rep.marktampel.upper()} – {rep.marktampel_text}", ""]
    for a in rep.alerts:
        lines.append(a.titel)
        if a.isin:
            lines.append(f"  ISIN {a.isin} | Ticker {a.ticker}")
        if a.kurs is not None:
            lines.append(f"  Schlusskurs {_fmt_px(a.kurs)}")
        lines += [f"  - {d}" for d in a.details]
        if a.art == "kauf":
            lines.append(f"  Plan: kaufen, Notbremse {_fmt_px(a.stop)}, halten bis ca. {a.halten_bis:%d.%m.%Y}")
        lines.append("")
    if not rep.alerts:
        lines.append("Keine deutlichen Signale.")
    lines += [f"! {w}" for w in rep.warnungen]
    lines.append("Keine Anlageberatung.")
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
    port = int(os.environ.get("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls()
        if os.environ.get("SMTP_USER"):
            s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
        s.send_message(msg)
    return True


# --------------------------------------------------------------------------- Studie
def study(provider: DataProvider, watchlist: pd.DataFrame, start: date, end: Optional[date] = None,
          rules: Optional[SignalRules] = None) -> tuple[pd.DataFrame, str]:
    """Wiederholt die Ereignisstudie: Was passierte nach jedem Kaufsignal (mit/ohne Notbremse)?"""
    from .timing import perf, simulate

    r = rules or SignalRules()
    end = end or date.today()
    rows = []
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
            market = b.iloc[p + r.hold_days] / b.iloc[p] - 1
            rows.append({**{k: v for k, v in e.items() if k != "pos"}, "ticker": t,
                         "rendite": exit_close / entry - 1,
                         "rendite_notbremse": (stop_exit if stop_exit is not None else exit_close) / entry - 1,
                         "markt": market})
    df = pd.DataFrame(rows)
    if df.empty:
        return df, "Keine Ereignisse gefunden."
    df["ueber_markt"] = df["rendite"] - df["markt"]
    buy = df[df["kauf"]]

    def line(name, g, col="ueber_markt"):
        return (f"| {name} | {len(g)} | {g['rendite'].mean() * 100:+.1f} % | {g[col].mean() * 100:+.1f} % | "
                f"{(g['rendite'] > 0).mean():.0%} | {g['rendite'].min() * 100:+.0f} % |")

    md = ["| Gruppe | Fälle | Ø Rendite 3 Mon. | Ø vs. Markt | Anteil positiv | schlechtester Fall |",
          "|---|---:|---:|---:|---:|---:|", line("Alle Quartalszahlen", df), line("**Kaufsignal**", buy)]
    if len(buy):
        g = buy.assign(rendite=buy["rendite_notbremse"])
        md.append(line("Kaufsignal mit Notbremse −15 %", g.assign(ueber_markt=g["rendite"] - g["markt"])))
    md.append("")
    md.append("| Marktampel | CAGR | Max. Drawdown | Sharpe | Halten: CAGR | Halten: Max. DD |")
    md.append("|---|---:|---:|---:|---:|---:|")
    for t in (r.market_ticker, r.bench_us, r.bench_other):
        try:
            m = normalize_prices(provider.prices(t, start, end))
            sim = simulate(m, use_stop=False)
            s0 = sim.equity.index[min(200, len(m) - 1)]
            a, h = perf(sim.equity[s0:] / sim.equity[s0]), perf(sim.buy_hold[s0:] / sim.buy_hold[s0])
            md.append(f"| {t} ab {s0:%Y} | {a['cagr'] * 100:.1f} % | {a['max_dd'] * 100:.0f} % | {a['sharpe']:.2f} | "
                      f"{h['cagr'] * 100:.1f} % | {h['max_dd'] * 100:.0f} % |")
        except Exception as exc:
            md.append(f"| {t} | Fehler: {exc} | | | | |")
    return df, "\n".join(md)
