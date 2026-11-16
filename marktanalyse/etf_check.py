"""ETF-Check: Ist gerade ein besonders günstiger Zeitpunkt für Extra-Geld in bekannte ETFs?

Gemessen wird, wie weit ein ETF unter seinem bisherigen Höchststand liegt. Dazu
wird gezeigt, wie sich Käufe in derselben Lage früher entwickelt haben (Index
mit möglichst langer Historie als Näherung) – im Vergleich zu einem beliebigen Tag.

Regel (bewusst streng, siehe docs/ETF_CHECK.md):
* „Günstiger Zeitpunkt“ nur bei **breiten** ETFs (Welt, S&P 500) im **Crash**
  (> 20 % unter Hoch). Dort liefen Käufe historisch klar besser (S&P 500 seit
  1950: nach 3 Jahren in 4 % statt 14 % der Fälle im Minus).
* Kleinere Rücksetzer brachten keinen verlässlichen Vorteil; bei Länder-,
  Branchen- und Schwellenländer-ETFs war auch ein Crash kein verlässliches
  Kaufsignal (Nasdaq 2000: ~15 Jahre bis zum alten Hoch).
* Sonst „normaler Zeitpunkt“: Extra-Geld kann man trotzdem investieren – auf
  einen Rücksetzer zu warten, lohnte sich im Schnitt nicht.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from .data.base import DataProvider, normalize_prices

ETFS = [
    dict(ticker="EUNL.DE", breit=True, isin="IE00B4L5Y983", name="iShares Core MSCI World", art="Welt (Industrieländer)",
         proxy="^GSPC", proxy_name="S&P 500 seit 1950 (Näherung, MSCI World ist zu ~70 % USA)", proxy_start=date(1950, 1, 1)),
    dict(ticker="VWCE.DE", breit=True, isin="IE00BK5BQT80", name="Vanguard FTSE All-World", art="Welt inkl. Schwellenländer",
         proxy="^GSPC", proxy_name="S&P 500 seit 1950 (Näherung)", proxy_start=date(1950, 1, 1)),
    dict(ticker="SXR8.DE", breit=True, isin="IE00B5BMR087", name="iShares Core S&P 500", art="USA",
         proxy="^GSPC", proxy_name="S&P 500 seit 1950", proxy_start=date(1950, 1, 1)),
    dict(ticker="EXS1.DE", breit=False, isin="DE0005933931", name="iShares Core DAX", art="Deutschland",
         proxy="^GDAXI", proxy_name="DAX seit 1988", proxy_start=date(1988, 1, 1)),
    dict(ticker="SXRV.DE", breit=False, isin="IE00B53SZB19", name="iShares Nasdaq 100", art="USA Technologie",
         proxy="^NDX", proxy_name="Nasdaq 100 seit 1985", proxy_start=date(1985, 1, 1)),
    dict(ticker="IS3N.DE", breit=False, isin="IE00BKM4GZ66", name="iShares Core MSCI EM IMI", art="Schwellenländer",
         proxy="EEM", proxy_name="MSCI Emerging Markets (EEM) seit 2003", proxy_start=date(2003, 1, 1)),
]

BUCKETS = [(-0.05, "nahe am Höchststand (weniger als 5 % darunter)"),
           (-0.10, "leichter Rücksetzer (5–10 % unter Hoch)"),
           (-0.20, "Korrektur (10–20 % unter Hoch)"),
           (-1.01, "Crash (mehr als 20 % unter Hoch)")]
HORIZON = 756  # 3 Jahre in Handelstagen


def bucket_of(dd: float) -> int:
    for i, (lower, _) in enumerate(BUCKETS):
        if dd > lower:
            return i
    return len(BUCKETS) - 1


@dataclass
class EtfStatus:
    ticker: str
    isin: str
    name: str
    art: str
    kurs: float
    datum: date
    hoch: float
    abstand: float  # ≤ 0
    lage: str
    stufe: int  # 0..3
    urteil: str  # "guenstig" | "normal"
    text: str
    proxy_name: str
    breit: bool = True
    neu_guenstig: bool = False  # heute erstmals in den Crash-Bereich gerutscht (für die Alarm-Mail)
    crash_vorher: bool = False  # in den 6 Monaten davor schon im Crash-Bereich
    hist_lage: dict = field(default_factory=dict)  # Rendite/Verlustquote in dieser Lage
    hist_alle: dict = field(default_factory=dict)  # … an beliebigen Tagen


def _stats(close: pd.Series, mask: pd.Series) -> dict:
    f3 = close.shift(-HORIZON) / close - 1
    f1 = close.shift(-252) / close - 1
    a3, a1 = f3[mask].dropna(), f1[mask].dropna()
    if len(a3) < 60:
        return {}
    return {"r3": float(a3.median()), "verlust3": float((a3 < 0).mean()), "r1": float(a1.median()),
            "tage": int(len(a3))}


def check(provider: DataProvider, as_of: Optional[date] = None, etfs: Optional[list] = None) -> list[EtfStatus]:
    as_of = as_of or date.today()
    out = []
    proxy_cache: dict[str, pd.Series] = {}
    for e in etfs or ETFS:
        px = normalize_prices(provider.prices(e["ticker"], date(2000, 1, 1), as_of))["close"].dropna()
        px = px[px > 0]
        if px.empty:
            continue
        hoch = float(px.max())
        dd = float(px.iloc[-1] / hoch - 1)
        stufe = bucket_of(dd)
        if e["proxy"] not in proxy_cache:
            pc = normalize_prices(provider.prices(e["proxy"], e["proxy_start"], as_of))["close"].dropna()
            proxy_cache[e["proxy"]] = pc[pc > 0]
        pc = proxy_cache[e["proxy"]]
        pdd = pc / pc.cummax() - 1
        buckets = pdd.apply(bucket_of)
        lage = _stats(pc, buckets == stufe)
        alle = _stats(pc, pd.Series(True, index=pc.index))
        guenstig = bool(e.get("breit") and stufe == 3)
        # erstmals seit mindestens 6 Monaten in den Crash-Bereich gerutscht?
        own_dd = px / px.cummax() - 1
        reif = len(own_dd) > 504  # junge ETFs (< 2 Jahre Historie) lösen keinen Alarm aus – Startdaten oft unsauber
        crash_vorher = bool(reif and (own_dd.iloc[-127:-1] <= -0.20).any())
        neu = bool(guenstig and reif and not crash_vorher)
        if guenstig:
            text = ("Guter Zeitpunkt für Extra-Geld: Der Markt ist eingebrochen. Käufe in dieser Lage brachten früher nach "
                    f"3 Jahren im Median {lage['r3'] * 100:+.0f} % (sonst {alle['r3'] * 100:+.0f} %) und endeten seltener "
                    f"im Minus ({lage['verlust3']:.0%} statt {alle['verlust3']:.0%} der Fälle). Es kann aber erst noch "
                    "weiter fallen – nur Geld einsetzen, das du mehrere Jahre nicht brauchst.") if lage and alle else \
                   "Guter Zeitpunkt für Extra-Geld: Der Markt ist eingebrochen."
        elif stufe == 0:
            text = ("Kein besonderer Zeitpunkt. Extra-Geld kannst du trotzdem investieren – auf einen Rücksetzer zu "
                    "warten, lohnte sich im Schnitt nicht.")
        elif not e.get("breit") and stufe == 3:
            text = ("Deutlich eingebrochen. Bei einem Länder-, Branchen- oder Schwellenländer-ETF ist das aber kein "
                    "verlässliches Kaufsignal – Erholungen dauerten hier teils viele Jahre.")
        else:
            text = ("Etwas günstiger als am Höchststand, aber historisch kein klarer Vorteil gegenüber einem "
                    "beliebigen Tag. Extra-Geld kannst du investieren, musst aber nicht auf mehr warten.")
        out.append(EtfStatus(
            ticker=e["ticker"], isin=e["isin"], name=e["name"], art=e["art"], kurs=float(px.iloc[-1]),
            datum=px.index[-1].date(), hoch=hoch, abstand=dd, lage=BUCKETS[stufe][1], stufe=stufe,
            urteil="guenstig" if guenstig else "normal", text=text, proxy_name=e["proxy_name"],
            breit=bool(e.get("breit")), neu_guenstig=neu, crash_vorher=crash_vorher, hist_lage=lage, hist_alle=alle))
    return out


def summary(status: list[EtfStatus]) -> str:
    g = [s for s in status if s.urteil == "guenstig"]
    if not g:
        return "Gerade kein besonders günstiger Zeitpunkt. Dein Sparplan reicht – Extra-Geld kannst du trotzdem jederzeit investieren."
    names = ", ".join(s.name for s in g)
    return f"Günstiger Zeitpunkt für Extra-Geld bei: {names}."


def to_text(status: list[EtfStatus]) -> str:
    lines = [summary(status), ""]
    for s in status:
        lines.append(f"{s.name} ({s.isin}): {s.kurs:.2f} € am {s.datum:%d.%m.%Y}, {s.abstand * 100:+.1f} % vom Hoch "
                     f"– {s.lage} – {'GÜNSTIG' if s.urteil == 'guenstig' else 'normal'}")
        lines.append(f"   {s.text}")
    return "\n".join(lines)


def alarm_mail(status: list[EtfStatus]) -> Optional[dict]:
    """Seltene Mail, wenn ein breiter ETF erstmals (seit ≥ 6 Monaten) in den Crash-Bereich rutscht."""
    neu = [s for s in status if s.neu_guenstig]
    if not neu or any(s.breit and s.crash_vorher for s in status):
        return None  # pro Crash nur eine Mail
    s0 = neu[0]
    names = ", ".join(s.name for s in neu)
    subject = f"ETF-Check – guter Zeitpunkt für Extra-Geld ({names})"
    rows = "".join(f"<li><b>{s.name}</b> (ISIN {s.isin}): {s.abstand * 100:.0f} % unter dem Höchststand</li>" for s in neu)
    html = ('<div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;max-width:600px">'
            '<h2 style="color:#1a7f37">Guter Zeitpunkt für Extra-Geld in deinen Welt-ETF</h2>'
            f"<ul>{rows}</ul><p>{s0.text}</p>"
            "<p><b>So geht's:</b> Wenn du Geld übrig hast, das du mehrere Jahre nicht brauchst: in Trade Republic "
            "deinen ETF öffnen → Kaufen → Betrag eingeben. <b>Deinen Sparplan auf keinen Fall stoppen.</b></p>"
            '<p style="color:#888;font-size:12px">Diese Mail kommt nur selten (seit 2012 nur dreimal: Februar 2016, März 2020, April 2025). '
            "Automatisch erzeugt, keine Anlageberatung.</p></div>")
    text = (f"Guter Zeitpunkt für Extra-Geld: {names} liegt mehr als 20 % unter dem Höchststand.\n{s0.text}\n"
            "Wenn du Geld übrig hast, das du mehrere Jahre nicht brauchst: ETF in Trade Republic kaufen. "
            "Sparplan nicht stoppen. Keine Anlageberatung.")
    return {"betreff": subject, "html": html, "text": text}


def history(provider: DataProvider, as_of: Optional[date] = None, start: date = date(2012, 1, 1),
            etfs: Optional[list] = None) -> list[dict]:
    """Wöchentlicher Abstand zum bisherigen Höchststand je ETF (für den Verlauf im ETF-Check)."""
    as_of = as_of or date.today()
    rows = []
    for e in etfs or ETFS:
        px = normalize_prices(provider.prices(e["ticker"], date(2000, 1, 1), as_of))["close"].dropna()
        px = px[px > 0]
        if px.empty:
            continue
        dd = (px / px.cummax() - 1).loc[pd.Timestamp(start):]
        weekly = dd.groupby(dd.index.to_period("W-FRI")).tail(1)  # letzter echter Handelstag je Woche
        for d, v in weekly.items():
            rows.append({"datum": d.strftime("%Y-%m-%d"), "isin": e["isin"], "abstand_pct": round(float(v) * 100, 2)})
    return rows


def dashboard_rows(status: list[EtfStatus]) -> list[dict]:
    """Zeilen für das Dashboard; Prozentwerte in Prozent (−1.4 = −1,4 %)."""
    def pct(d, k, nd=0):
        return round(d[k] * 100, nd) if d and d.get(k) is not None else None

    return [{
        "isin": s.isin, "name": s.name, "art": s.art, "breit": s.breit,
        "urteil": "Guter Zeitpunkt" if s.urteil == "guenstig" else "Normal",
        "kurs": round(s.kurs, 2), "datum": s.datum.isoformat(), "hoch": round(s.hoch, 2),
        "abstand_pct": round(s.abstand * 100, 1), "lage": s.lage, "text": s.text, "vergleich": s.proxy_name,
        "r3_lage_pct": pct(s.hist_lage, "r3"), "verlust3_lage_pct": pct(s.hist_lage, "verlust3"),
        "r3_alle_pct": pct(s.hist_alle, "r3"), "verlust3_alle_pct": pct(s.hist_alle, "verlust3"),
    } for s in status]
