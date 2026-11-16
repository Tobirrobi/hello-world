"""Ausgabe der Analyse als Markdown-Report, JSON und kompakte Konsolentabelle."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from .config import CATEGORIES
from .models import AnalysisReport, Recommendation, TickerAnalysis
from .signals import money, num, pct, size_class

DISCLAIMER = (
    "Hinweis: Automatisch erzeugte, regelbasierte Analyse – keine Anlageberatung. "
    "Kennzahlen können fehlerhaft oder veraltet sein; Leerverkäufe bergen unbegrenztes Verlustrisiko."
)

ICON = {
    Recommendation.STRONG_LONG: "🟢🟢",
    Recommendation.LONG: "🟢",
    Recommendation.HOLD: "⚪",
    Recommendation.SHORT: "🔴",
    Recommendation.STRONG_SHORT: "🔴🔴",
}


def _bar(score: float, width: int = 10) -> str:
    n = int(round(abs(score) * width))
    return ("+" if score >= 0 else "−") * max(n, 0) or "·"


# --------------------------------------------------------------------------- Markdown
def to_markdown(rep: AnalysisReport, detail: bool = True) -> str:
    r = rep.regime
    L: list[str] = []
    L.append(f"# Marktanalyse zum {rep.as_of:%d.%m.%Y}")
    L.append("")
    L.append(f"_Erstellt am {rep.generated_at:%d.%m.%Y %H:%M} · Benchmark: {rep.benchmark} · {len(rep.analyses)} Werte_")
    L.append("")
    L.append(f"> {DISCLAIMER}")
    L.append("")

    L.append("## 1. Marktphase")
    L.append("")
    L.append(f"**{r.regime.label}**{' · ⚠️ Volatilitätsstress' if r.high_volatility else ''} "
             f"(Trendscore {r.trend_score:+.2f})")
    L.append("")
    L.append(r.description)
    L.append("")
    if r.details:
        L.append("| Komponente | Wert |")
        L.append("|---|---|")
        for k, v in r.details.items():
            if v is None:
                continue
            is_pct = "Drawdown" in k or "Volatilität" in k
            L.append(f"| {k} | {pct(v)} |" if is_pct else f"| {k} | {v:+.2f} |")
        L.append("")

    pv = rep.portfolio
    L.append("### Strategie für diese Marktphase")
    L.append("")
    L.append(f"- **Netto-Exposure:** {pv.net_exposure} · **Brutto-Exposure:** {pv.gross_exposure}")
    L.append("- **Long-Seite:**")
    L += [f"  - {x}" for x in pv.long_strategy]
    L.append("- **Short-Seite:**")
    L += [f"  - {x}" for x in pv.short_strategy]
    L.append("- **Absicherung:**")
    L += [f"  - {x}" for x in pv.hedging]
    L.append("")

    if rep.changes:
        L.append("## 2. Änderungen seit der letzten Analyse")
        L.append("")
        L += [f"- {c}" for c in rep.changes]
        L.append("")

    L.append(f"## {3 if rep.changes else 2}. Übersicht & Empfehlungen")
    L.append("")
    L.append("| | Ticker | Name | Kurs | Marktkap. | KGV | Score | Konfidenz | Empfehlung |")
    L.append("|---|---|---|---:|---:|---:|---:|---:|---|")
    for a in rep.analyses:
        f = a.metrics["fundamental"]
        pe = "Verlust" if f.get("eps_negative") else num(f.get("pe"))
        L.append(
            f"| {ICON[a.recommendation]} | **{a.ticker}** | {a.info.name[:28]} | {a.price:,.2f} | {money(f.get('market_cap'))} "
            f"| {pe} | {a.total_score:+.2f} | {a.confidence:.0%} | {a.recommendation.label} |"
        )
    L.append("")
    if pv.top_longs:
        L.append(f"**Top Long-Ideen:** {', '.join(pv.top_longs)}  ")
    if pv.top_shorts:
        L.append(f"**Top Short-Ideen:** {', '.join(pv.top_shorts)}  ")
    for lng, sht, why in pv.pair_trades:
        L.append(f"**Pair-Trade:** Long {lng} / Short {sht} – {why}  ")
    L.append("")

    if detail:
        L.append(f"## {4 if rep.changes else 3}. Einzelanalysen")
        L.append("")
        for a in rep.analyses:
            L += _ticker_md(a)

    if rep.warnings:
        L.append("## Hinweise zur Datenqualität")
        L.append("")
        L += [f"- {w}" for w in rep.warnings]
        L.append("")

    L.append("---")
    L.append("Methodik: Jede Kennzahl wird über eine Regel in einen Score von −1 (Short) bis +1 (Long) übersetzt, "
             "pro Kategorie gewichtet gemittelt und mit marktphasenabhängigen Kategoriegewichten zum Gesamtscore "
             "verdichtet. Die Schwellen für Long/Short hängen von der Marktphase ab. Details: `docs/KENNZAHLEN.md`.")
    return "\n".join(L) + "\n"


def _ticker_md(a: TickerAnalysis) -> list[str]:
    f, t = a.metrics["fundamental"], a.metrics["technisch"]
    L = [f"### {ICON[a.recommendation]} {a.ticker} – {a.info.name}"]
    L.append("")
    meta = [x for x in (a.info.sector, size_class(f.get("market_cap")), a.info.currency) if x]
    L.append(f"{' · '.join(meta)}  ")
    L.append(f"**Empfehlung: {a.recommendation.label}** · Score {a.total_score:+.2f} · Konfidenz {a.confidence:.0%} "
             f"· Datenabdeckung {a.coverage:.0%}")
    if a.raw_recommendation != a.recommendation:
        L.append(f"  (rechnerisch: {a.raw_recommendation.label}, durch Praxisregeln angepasst)")
    L.append("")

    L.append("| Kategorie | Score | |")
    L.append("|---|---:|---|")
    for key, label in CATEGORIES.items():
        if key in a.category_scores:
            s = a.category_scores[key]
            L.append(f"| {label} | {s:+.2f} | `{_bar(s)}` |")
    L.append("")

    L.append("**Kennzahlen auf einen Blick:** "
             f"KGV {'Verlust' if f.get('eps_negative') else num(f.get('pe'))} · Fwd-KGV {num(f.get('forward_pe'))} · "
             f"PEG {num(f.get('peg'), 2)} · KBV {num(f.get('pb'), 2)} · KUV {num(f.get('ps'), 2)} · "
             f"EV/EBITDA {num(f.get('ev_ebitda'))} · FCF-Rendite {pct(f.get('fcf_yield'))} · "
             f"Div.-Rendite {pct(f.get('dividend_yield'))} · ROE {pct(f.get('roe'))} · "
             f"RSI {num(t.get('rsi14'), 0)} · 12-1-Mom. {pct(t.get('mom_12_1'))} · Vola {pct(t.get('vol_60d'), 0)} · "
             f"Beta {num(t.get('beta'), 2)}")
    L.append("")

    pros, cons = a.pro_signals(), a.contra_signals()
    if pros:
        L.append("**Dafür (Long-Argumente):**")
        L += [f"- {s.rationale} _({s.score:+.2f})_" for s in pros]
        L.append("")
    if cons:
        L.append("**Dagegen (Short-Argumente):**")
        L += [f"- {s.rationale} _({s.score:+.2f})_" for s in cons]
        L.append("")
    if a.notes:
        L.append("**Praxisregeln & Warnungen:**")
        L += [f"- ⚠️ {n}" for n in a.notes]
        L.append("")

    tp = a.trade_plan
    if tp:
        side = "Long (Kauf)" if tp.direction > 0 else "Short (Leerverkauf)"
        L.append(f"**Trade-Plan {side}:** Einstieg ~{tp.entry:,.2f} · Stop-Loss {tp.stop_loss:,.2f} "
                 f"({(tp.stop_loss / tp.entry - 1) * 100:+.1f} %) · Kursziel {tp.take_profit:,.2f} "
                 f"({(tp.take_profit / tp.entry - 1) * 100:+.1f} %) · Chance/Risiko {tp.reward_risk:.1f} · "
                 f"Größe {tp.shares:,} Stück ≈ {tp.position_value:,.0f} ({tp.position_pct:.1%} des Kapitals)")
        L += [f"  - {n}" for n in tp.notes]
        L.append("")

    nw = a.metrics.get("nachrichten") or {}
    if nw.get("anzahl"):
        L.append(f"<details><summary>Nachrichten ({nw['anzahl']} Meldungen, Verfahren: {nw.get('verfahren')})</summary>")
        L.append("")
        for h, s in (nw.get("positiv") or []) + (nw.get("negativ") or []):
            L.append(f"- {s:+.2f} {h}")
        L.append("")
        L.append("</details>")
        L.append("")

    L.append("<details><summary>Alle Signale</summary>")
    L.append("")
    L.append("| Signal | Kategorie | Wert | Score | Gewicht | Begründung |")
    L.append("|---|---|---:|---:|---:|---|")
    for s in sorted(a.signals, key=lambda s: (list(CATEGORIES).index(s.category), -s.score)):
        L.append(f"| {s.name} | {CATEGORIES.get(s.category, s.category)} | {s.value_fmt} | {s.score:+.2f} "
                 f"| {s.weight:.1f} | {s.rationale} |")
    ds = a.metrics.get("datenstand") or {}
    L.append("")
    L.append(f"Datenstand: Kurs {ds.get('kurs')}, Fundamentaldaten veröffentlicht {ds.get('fundamentaldaten') or '–'} "
             f"(Periode {ds.get('periode') or '–'}), Erwartungen {ds.get('erwartungen') or '–'}")
    L.append("")
    L.append("</details>")
    L.append("")
    return L


# --------------------------------------------------------------------------- JSON
def _default(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if isinstance(o, Enum):
        return o.value
    if is_dataclass(o):
        return asdict(o)
    if hasattr(o, "item"):
        return o.item()
    return str(o)


def to_dict(rep: AnalysisReport) -> dict:
    return json.loads(json.dumps(asdict(rep), default=_default))


def to_json(rep: AnalysisReport) -> str:
    return json.dumps(asdict(rep), default=_default, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- Konsole
def to_text(rep: AnalysisReport) -> str:
    r = rep.regime
    lines = [
        f"Marktanalyse {rep.as_of:%d.%m.%Y} | {r.regime.label}{' | VOLATILITÄTSSTRESS' if r.high_volatility else ''} "
        f"| Trend {r.trend_score:+.2f}",
        f"Netto-Exposure: {rep.portfolio.net_exposure}",
        "",
        f"{'Ticker':<10}{'Kurs':>12}{'KGV':>9}{'Score':>8}{'Konf.':>7}  Empfehlung",
        "-" * 68,
    ]
    for a in rep.analyses:
        f = a.metrics["fundamental"]
        pe = "Verlust" if f.get("eps_negative") else num(f.get("pe"))
        lines.append(f"{a.ticker:<10}{a.price:>12,.2f}{pe:>9}{a.total_score:>+8.2f}{a.confidence:>7.0%}  {a.recommendation.label}")
        if a.trade_plan:
            tp = a.trade_plan
            lines.append(f"{'':<10}  Stop {tp.stop_loss:,.2f} | Ziel {tp.take_profit:,.2f} | {tp.shares:,} Stück")
    for c in rep.changes:
        lines.append(f"* {c}")
    for w in rep.warnings:
        lines.append(f"! {w}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- Vergleich & Speichern
def diff_with_previous(rep: AnalysisReport, prev: Optional[dict]) -> list[str]:
    """Vergleicht Empfehlungen mit einem früheren JSON-Report."""
    if not prev:
        return []
    out = []
    old_regime = (prev.get("regime") or {}).get("regime")
    if old_regime and old_regime != rep.regime.regime.value:
        out.append(f"Marktphase gewechselt: {old_regime} → {rep.regime.regime.value} ({rep.regime.regime.label})")
    old = {a["ticker"]: a for a in prev.get("analyses", [])}
    for a in rep.analyses:
        o = old.get(a.ticker)
        if o is None:
            out.append(f"{a.ticker}: neu im Universum – {a.recommendation.label}")
            continue
        if o.get("recommendation") != a.recommendation.value:
            out.append(f"{a.ticker}: {Recommendation(o['recommendation']).label} → {a.recommendation.label} "
                       f"(Score {o.get('total_score', 0):+.2f} → {a.total_score:+.2f})")
        tp = o.get("trade_plan")
        if tp and tp.get("direction") and a.price:
            hit_stop = (tp["direction"] > 0 and a.price <= tp["stop_loss"]) or (tp["direction"] < 0 and a.price >= tp["stop_loss"])
            hit_tp = (tp["direction"] > 0 and a.price >= tp["take_profit"]) or (tp["direction"] < 0 and a.price <= tp["take_profit"])
            if hit_stop:
                out.append(f"{a.ticker}: Stop-Loss {tp['stop_loss']:,.2f} aus der letzten Analyse erreicht – Position schließen.")
            elif hit_tp:
                out.append(f"{a.ticker}: Kursziel {tp['take_profit']:,.2f} erreicht – Gewinne mitnehmen / Stop nachziehen.")
    return out


def save_report(rep: AnalysisReport, out_dir: str | Path, formats=("md", "json")) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = f"{rep.as_of:%Y-%m-%d}"
    paths = []
    if "md" in formats:
        md = to_markdown(rep)
        for name in (f"analyse_{stamp}.md", "latest.md"):
            (out / name).write_text(md, encoding="utf-8")
        paths.append(out / f"analyse_{stamp}.md")
    if "json" in formats:
        js = to_json(rep)
        for name in (f"analyse_{stamp}.json", "latest.json"):
            (out / name).write_text(js, encoding="utf-8")
        paths.append(out / f"analyse_{stamp}.json")
    return paths


def load_previous(out_dir: str | Path, before: date) -> Optional[dict]:
    """Lädt den jüngsten JSON-Report vor ``before`` aus dem Ausgabeordner."""
    out = Path(out_dir)
    if not out.exists():
        return None
    cands = sorted(p for p in out.glob("analyse_*.json") if p.stem.split("_", 1)[1] < f"{before:%Y-%m-%d}")
    if not cands:
        return None
    return json.loads(cands[-1].read_text(encoding="utf-8"))
