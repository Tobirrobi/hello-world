"""Kommandozeile: ``marktanalyse <befehl> ...`` bzw. ``python -m marktanalyse <befehl> ...``."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from .config import CATEGORIES, load_config
from .data import DEMO_BENCHMARK, SyntheticProvider, archive, make_provider
from .engine import Analyzer
from .report import diff_with_previous, load_previous, save_report, to_json, to_markdown, to_text


def _date(s: str) -> date:
    return date.fromisoformat(s)


def _tickers(args) -> list[str]:
    out = list(args.tickers or [])
    if getattr(args, "watchlist", None):
        for line in Path(args.watchlist).read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                out += [t.strip() for t in line.replace(";", ",").split(",") if t.strip()]
    if not out and args.provider == "demo":
        out = SyntheticProvider.tickers()
    if not out:
        sys.exit("Bitte Ticker angeben (z. B. AAPL MSFT SAP.DE) oder --watchlist datei.txt")
    return list(dict.fromkeys(out))


def _benchmark(args, tickers: list[str]) -> str:
    if args.benchmark:
        return args.benchmark
    if args.provider == "demo":
        return DEMO_BENCHMARK
    if tickers and all(t.upper().endswith(".DE") for t in tickers):
        return "^GDAXI"
    return "^GSPC"


def _analyzer(args, tickers):
    cfg = load_config(args.config)
    if getattr(args, "capital", None):
        cfg.capital = args.capital
    scorer = None
    if getattr(args, "llm_sentiment", False):
        from .sentiment import ClaudeSentimentScorer

        scorer = ClaudeSentimentScorer()
    return Analyzer(make_provider(args.provider, args.data_dir), _benchmark(args, tickers), cfg, scorer)


def _common(p: argparse.ArgumentParser, with_tickers: bool = True) -> None:
    if with_tickers:
        p.add_argument("tickers", nargs="*", help="Ticker-Symbole (Yahoo-Schreibweise, z. B. AAPL, SAP.DE, ^GDAXI)")
        p.add_argument("--watchlist", help="Textdatei mit Tickern (einer pro Zeile oder kommagetrennt)")
    p.add_argument("--provider", default="yahoo", choices=["yahoo", "csv", "demo"], help="Datenquelle (Standard: yahoo)")
    p.add_argument("--data-dir", help="Verzeichnis der CSV-Datenablage (für --provider csv)")
    p.add_argument("--benchmark", help="Vergleichsindex für Marktphase/Beta (Standard: ^GSPC bzw. ^GDAXI)")
    p.add_argument("--config", help="TOML-Datei mit eigenen Gewichten/Schwellen")
    p.add_argument("--capital", type=float, help="Depotgröße für die Positionsgrößen (Standard 100000)")
    p.add_argument("--llm-sentiment", action="store_true", help="Nachrichten mit Claude bewerten (anthropic + API-Zugang nötig)")


def cmd_analyze(args) -> None:
    tickers = _tickers(args)
    an = _analyzer(args, tickers)
    as_of = args.as_of or date.today()
    rep = an.analyze(tickers, as_of)
    if not rep.analyses:
        print("\n".join(["Keine Analyse möglich – keine verwertbaren Daten:"] + [f"  {w}" for w in rep.warnings]), file=sys.stderr)
        sys.exit(2)
    if args.output:
        rep.changes = diff_with_previous(rep, load_previous(args.output, as_of))
        paths = save_report(rep, args.output)
        print(to_text(rep))
        print("\nGespeichert: " + ", ".join(str(p) for p in paths))
        return
    print({"md": to_markdown, "json": to_json, "text": to_text}[args.format](rep))


def cmd_backtest(args) -> None:
    from .backtest import backtest_markdown, run_backtest

    tickers = _tickers(args)
    cfg = load_config(args.config)
    prov = make_provider(args.provider, args.data_dir)
    res = run_backtest(prov, tickers, args.start, args.end, _benchmark(args, tickers), args.interval, args.horizon, cfg,
                       progress=lambda d: print(f"  Stichtag {d}", file=sys.stderr))
    md = backtest_markdown(res, f"Backtest {args.start} bis {args.end} ({len(tickers)} Werte, alle {args.interval} "
                                f"Handelstage, Haltedauer {args.horizon} Tage)")
    if args.output:
        out = Path(args.output)
        out.mkdir(parents=True, exist_ok=True)
        (out / "backtest.md").write_text(md, encoding="utf-8")
        res.records.to_csv(out / "backtest_einzelwerte.csv", index=False)
        res.periods.to_csv(out / "backtest_perioden.csv", index=False)
        print(f"Gespeichert in {out}/")
    print(md)


def cmd_schedule(args) -> None:
    from .scheduler import run_schedule

    tickers = _tickers(args)
    print(f"Starte regelmäßige Analyse von {len(tickers)} Werten alle {args.every}"
          + (f" um {args.at} Uhr" if args.at else "") + f" → {args.output}")
    run_schedule(lambda: _analyzer(args, tickers), tickers, args.output, args.every, args.at, args.max_runs)


def cmd_archive(args) -> None:
    tickers = _tickers(args)
    prov = make_provider(args.provider, args.data_dir)
    bench = _benchmark(args, tickers)
    stats = archive(prov, tickers + [bench], args.target, args.history_days)
    for k, v in stats.items():
        print(f"{k:<40} +{v} Zeilen")
    print(f"Archiv aktualisiert: {args.target}")


def cmd_kennzahlen(args) -> None:
    from .signals import CROSS_SECTIONAL, RULES

    by_cat: dict[str, list] = {}
    for r in RULES:
        by_cat.setdefault(r.category, []).append((r.key, r.name, r.weight, r.long_case, r.short_case))
    for key, name, cat, w, lc, sc in CROSS_SECTIONAL:
        by_cat.setdefault(cat, []).append((key, name, w, lc, sc))
    if args.markdown:
        print("| Kategorie | Signal (Schlüssel) | Gewicht | Spricht für LONG | Spricht für SHORT |")
        print("|---|---|---:|---|---|")
        for cat, label in CATEGORIES.items():
            for key, name, w, lc, sc in by_cat.get(cat, []):
                print(f"| {label} | {name} (`{key}`) | {w:.1f} | {lc} | {sc} |")
        return
    for cat, label in CATEGORIES.items():
        print(f"\n== {label} ==")
        for key, name, w, lc, sc in by_cat.get(cat, []):
            print(f"  {name}  [{key}, Gewicht {w}]")
            print(f"     LONG:  {lc}")
            print(f"     SHORT: {sc}")


def cmd_demo(args) -> None:
    from .backtest import backtest_markdown, run_backtest
    from .data.synthetic import demo_dates

    prov = SyntheticProvider()
    an = Analyzer(prov, DEMO_BENCHMARK, load_config(args.config))
    out = Path(args.output)
    for label, d in demo_dates().items():
        rep = an.analyze(SyntheticProvider.tickers(), d)
        rep.changes = diff_with_previous(rep, load_previous(out, d))
        save_report(rep, out)
        print(f"\n######## {label} ########")
        print(to_text(rep))
    if not args.no_backtest:
        print("\nBacktest über die Demo-Historie läuft …")
        res = run_backtest(prov, SyntheticProvider.tickers(), date(2019, 1, 2), date(2026, 9, 30), DEMO_BENCHMARK, 21, 21)
        md = backtest_markdown(res, "Backtest Demo-Universum 2019–2026 (monatlich, Haltedauer 21 Tage)")
        (out / "backtest.md").write_text(md, encoding="utf-8")
        print(md)
    print(f"\nReports gespeichert in {out}/ (Markdown + JSON)")


def cmd_signale(args) -> None:
    from datetime import timedelta

    from .signale import load_watchlist, scan, send_smtp, subject, to_html, to_json
    from .signale import to_text as sig_text

    wl = load_watchlist(args.liste)
    prov = make_provider(args.provider, args.data_dir)
    analyzer = None if args.ohne_analyse else Analyzer(prov, "URTH", load_config(args.config))
    as_of = args.as_of or (date.today() - timedelta(days=1))
    rep = scan(prov, wl, as_of, analyzer=analyzer)
    print(subject(rep))
    print(sig_text(rep))
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(to_json(rep), encoding="utf-8")
    if args.html:
        Path(args.html).parent.mkdir(parents=True, exist_ok=True)
        Path(args.html).write_text(to_html(rep), encoding="utf-8")
    if args.smtp and rep.has_signals:
        print("Mail versendet." if send_smtp(rep) else "Mail NICHT versendet (SMTP nicht konfiguriert).")


def cmd_signal_studie(args) -> None:
    from .signale import load_watchlist, study

    wl = load_watchlist(args.liste)
    df, md = study(make_provider(args.provider, args.data_dir), wl, args.start, args.end)
    print(md)
    if args.output:
        out = Path(args.output)
        out.mkdir(parents=True, exist_ok=True)
        df.to_csv(out / "signal_ereignisse.csv", index=False)
        (out / "signal_studie.md").write_text(md + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="marktanalyse", description="Regelbasierte Aktienmarktanalyse mit Long-/Short-Empfehlungen")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="Analyse zu einem Stichtag (Standard: heute)")
    _common(a)
    a.add_argument("--as-of", type=_date, help="Stichtag JJJJ-MM-TT (Point-in-Time-Analyse)")
    a.add_argument("--format", default="md", choices=["md", "json", "text"])
    a.add_argument("--output", help="Reports in dieses Verzeichnis schreiben (inkl. Vergleich mit letztem Lauf)")
    a.set_defaults(func=cmd_analyze)

    b = sub.add_parser("backtest", help="Analyse in regelmäßigen Abständen über die Vergangenheit + Erfolgsmessung")
    _common(b)
    b.add_argument("--start", type=_date, required=True)
    b.add_argument("--end", type=_date, default=date.today())
    b.add_argument("--interval", type=int, default=21, help="Abstand der Stichtage in Handelstagen (Standard 21 ≈ monatlich)")
    b.add_argument("--horizon", type=int, default=21, help="Haltedauer in Handelstagen für die Erfolgsmessung")
    b.add_argument("--output", help="Ergebnisse (Markdown + CSV) in dieses Verzeichnis schreiben")
    b.set_defaults(func=cmd_backtest)

    s = sub.add_parser("schedule", help="Dauerbetrieb: Analyse in festem Takt (z. B. täglich 22:15)")
    _common(s)
    s.add_argument("--every", default="1d", help="Intervall: 30m, 6h, 1d, 1w (Standard 1d)")
    s.add_argument("--at", help="Uhrzeit HH:MM für Tages-/Wochentakt")
    s.add_argument("--output", default="reports", help="Ausgabeverzeichnis (Standard: reports)")
    s.add_argument("--max-runs", type=int, help="Nach N Läufen beenden")
    s.set_defaults(func=cmd_schedule)

    r = sub.add_parser("archive", help="Daten in CSV-Ablage sichern (baut eigene Point-in-Time-Historie auf)")
    _common(r)
    r.add_argument("--target", default="daten", help="Zielverzeichnis (Standard: daten)")
    r.add_argument("--history-days", type=int, default=800)
    r.set_defaults(func=cmd_archive)

    g = sub.add_parser("signale", help="Signal-Wächter: deutliche Kauf-/Verkaufssignale der Beobachtungsliste (für tägliche Mail)")
    g.add_argument("--liste", default="beobachtungsliste.csv", help="CSV mit ticker,isin,name,region")
    g.add_argument("--provider", default="yahoo", choices=["yahoo", "csv", "demo"])
    g.add_argument("--data-dir")
    g.add_argument("--config")
    g.add_argument("--as-of", type=_date, help="Stichtag (Standard: gestern = letzter abgeschlossener Handelstag)")
    g.add_argument("--json", help="Ergebnis als JSON (inkl. Betreff, HTML, Text) speichern")
    g.add_argument("--html", help="Mail-Text als HTML speichern")
    g.add_argument("--smtp", action="store_true", help="Bei Signalen Mail per SMTP senden (MAIL_TO, SMTP_HOST, …)")
    g.add_argument("--ohne-analyse", action="store_true", help="Keine Fundamentalanalyse für Kaufsignale")
    g.set_defaults(func=cmd_signale)

    st = sub.add_parser("signal-studie", help="Historische Prüfung der Signale (Ereignisstudie + Marktampel)")
    st.add_argument("--liste", default="beobachtungsliste.csv")
    st.add_argument("--provider", default="yahoo", choices=["yahoo", "csv", "demo"])
    st.add_argument("--data-dir")
    st.add_argument("--start", type=_date, default=date(2000, 1, 1))
    st.add_argument("--end", type=_date, default=date.today())
    st.add_argument("--output")
    st.set_defaults(func=cmd_signal_studie)

    k = sub.add_parser("kennzahlen", help="Katalog aller Kennzahlen und Signale anzeigen")
    k.add_argument("--markdown", action="store_true")
    k.set_defaults(func=cmd_kennzahlen)

    d = sub.add_parser("demo", help="Demo mit synthetischen Daten (Bullen-, Seitwärts-, Bärenmarkt + Backtest)")
    d.add_argument("--output", default="reports/demo")
    d.add_argument("--config")
    d.add_argument("--no-backtest", action="store_true")
    d.set_defaults(func=cmd_demo)
    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    args.func(args)


if __name__ == "__main__":
    main()
