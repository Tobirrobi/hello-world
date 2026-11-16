# Marktanalyse

Regelbasierte Aktienmarktanalyse mit **Kauf- und Short-Empfehlungen** für **steigende, fallende und
seitwärts laufende Märkte**. Zu einem beliebigen Stichtag wertet das Tool über 40 Signale aus: Bewertung
(KGV, PEG, KBV, KUV, EV/EBITDA, FCF-Rendite), Qualität und Bilanz (ROE, Verschuldung, Piotroski, Altman Z),
Wachstum, Trend, Momentum, Oszillatoren, Risiko, Marktkapitalisierung, Analysten, Short Interest und **aktuelle
Nachrichten**. Daraus entstehen eine Empfehlung, ein Trade-Plan mit Stop-Loss, Kursziel und Positionsgröße sowie
eine Strategie für die aktuelle Marktphase.

> ⚠️ Keine Anlageberatung. Die Analyse ist automatisch und regelbasiert; Daten können fehlerhaft sein.
> Leerverkäufe bergen ein unbegrenztes Verlustrisiko.

## Signal-Wächter: Kaufmails für gezieltes Einkaufen

```bash
marktanalyse signale --seit 2026-11-16          # prüft beobachtungsliste.csv für den letzten Börsentag
marktanalyse signale --betrag 250 --smtp        # … mit festem Betrag in der Mail, Versand per SMTP
marktanalyse signal-studie --start 2000-01-01   # historische Prüfung
```

**Regel: Kaufmail → für den festen Betrag kaufen und behalten.** Eine Kaufmail kommt, wenn eine Firma deutlich bessere
Quartalszahlen meldet (Gewinn ≥ 5 % über der Erwartung) und die Aktie am Meldetag ≥ 3 % stärker steigt als der Markt.
Es gibt höchstens eine Mail pro Aktie in 12 Monaten, insgesamt etwa 9 im Jahr. Historisch lagen solche Käufe nach
1–3 Jahren im Median deutlich vor Käufen derselben Aktien ohne Signal. Chartsignale wie 200-Tage-Linie, RSI oder MACD
brachten bei Einzelaktien keinen Vorteil. Verkaufsmails sind optional (`--mit-verkauf`).

Alle Regeln, Tests und Einordnungen: **[docs/SIGNALE.md](docs/SIGNALE.md)**.

## Was das Tool macht

```
Stichtag ──► Daten bis zum Stichtag ──► Marktphase (Bulle/Bär/Seitwärts, Volatilitätsstress)
         ──► Kennzahlen ──► ~40 Signale (−1 Short … +1 Long) ──► 9 Kategorien
         ──► Gesamtscore (Gewichte je Marktphase) ──► Empfehlung (Schwellen je Marktphase)
         ──► Praxisregeln (Squeeze-Gefahr, fallendes Messer, Insolvenzrisiko, Quartalszahlen)
         ──► Trade-Plan (ATR-Stop, Ziel 2:1, Positionsgröße) + Portfolio-Strategie + Pair-Trades
```

* **Point-in-Time**: Es fließen nur Daten ein, die zum Stichtag öffentlich waren (Quartalszahlen erst ab
  Veröffentlichung). Ein Test prüft, dass kein Blick in die Zukunft stattfindet.
* **Steigender vs. fallender Markt**: Gewichte, Schwellen, Positionsgrößen und Strategie hängen von der
  Marktphase ab. Im Bärenmarkt zählen Bilanzqualität und Risiko mehr und Shorts brauchen weniger Evidenz,
  im Bullenmarkt zählen Trend und Momentum mehr.
* **Regelmäßig**: per `schedule`-Befehl, cron oder GitHub Actions. Jeder Lauf vergleicht mit dem vorherigen
  (neue Empfehlungen, Phasenwechsel, erreichte Stops und Kursziele).
* **Backtest**: Die Analyse wird in festen Abständen über die Vergangenheit ausgeführt und mit der
  tatsächlichen Folgerendite verglichen (Trefferquote, Long/Short-Rendite, Information Coefficient).

Alle Kennzahlen, Signale, Schwellen und die Logik für Long und Short stehen in
**[docs/KENNZAHLEN.md](docs/KENNZAHLEN.md)**.

## Ergebnis auf echten Daten – bitte lesen

Ein Backtest mit echten Yahoo-Daten (16 Watchlist-Werte, monatlich 06/2023–10/2026) steht in
**[docs/BACKTEST_ECHTDATEN.md](docs/BACKTEST_ECHTDATEN.md)**. Kurz:

* Der **Gesamtscore hat in diesem Test keine nachweisbare Prognosekraft** (Information Coefficient ≈ 0).
  Der Vorsprung der Long-Empfehlungen gegenüber dem Index stammt aus der Watchlist-Auswahl, nicht aus den Signalen.
* **Wachstum** und **Qualität & Bilanz** sagten die Folgerenditen konsistent voraus,
  **Bewertung** und **Trend** liefen im Wachstums-Bullenmarkt 2023–2026 gegenläufig.
* Der Zeitraum enthält fast nur Bullenmarkt – die Bärenmarkt- und Short-Logik ist damit nicht validiert.

Die Empfehlungen sind daher als strukturierte Zusammenfassung der Kennzahlen zu verstehen, nicht als belegte
Handelsstrategie. Vor echtem Einsatz: Backtest auf eigenem, größerem Universum laufen lassen
(`marktanalyse backtest ...`) und Gewichte per `--config` anpassen.

## Installation

```bash
pip install -e ".[yahoo]"        # mit echten Kursdaten von Yahoo Finance
pip install -e ".[yahoo,llm]"    # zusätzlich Nachrichtenbewertung mit Claude
pip install -e ".[all]"          # alles inkl. Tests
```

Python ≥ 3.10.

In Cloud-Umgebungen mit eingeschränktem Netz müssen diese Hosts erlaubt sein: `query1.finance.yahoo.com`,
`query2.finance.yahoo.com`, `finance.yahoo.com`, `fc.yahoo.com`, `guce.yahoo.com`, `consent.yahoo.com`
und für Nachrichten `nexus-finance-prod.media.yahoo.com`.

## Schnellstart

```bash
# 1. Demo ohne Internet: synthetische Daten mit Bullen-, Seitwärts- und Bärenphase + Backtest
marktanalyse demo
#    → reports/demo/analyse_*.md, backtest.md

# 2. Analyse heute (echte Daten)
marktanalyse analyze AAPL MSFT NVDA SAP.DE

# 3. Analyse zu einem bestimmten Zeitpunkt
marktanalyse analyze AAPL MSFT NVDA --as-of 2025-04-08

# 4. Watchlist analysieren und Reports speichern (inkl. Vergleich mit dem letzten Lauf)
marktanalyse analyze --watchlist watchlist.txt --output reports

# 5. Backtest: monatlich seit 2023, Haltedauer 1 Monat
marktanalyse backtest --watchlist watchlist.txt --start 2023-01-01 --interval 21 --horizon 21 --output reports/backtest

# 6. Dauerbetrieb: werktags um 22:15 Uhr
marktanalyse schedule --watchlist watchlist.txt --every 1d --at 22:15 --output reports

# 7. Katalog aller Kennzahlen und Signale
marktanalyse kennzahlen
```

Weitere Optionen: `--format md|json|text`, `--benchmark ^GDAXI`, `--capital 50000`,
`--config config.example.toml`, `--llm-sentiment`, `--provider yahoo|csv|demo`.

### Regelmäßige Ausführung

| Variante | Einrichtung |
|---|---|
| **GitHub Actions** (empfohlen) | `.github/workflows/marktanalyse.yml` läuft Mo–Fr 22:30 UTC, archiviert die Daten, analysiert `watchlist.txt`, zeigt den Report in der Job-Zusammenfassung und lädt ihn als Artefakt hoch. Manuell startbar, auch mit Stichtag. Der Zeitplan greift erst, wenn der Workflow im Default-Branch liegt. |
| **cron** | `30 22 * * 1-5 cd /pfad/zum/repo && marktanalyse analyze --watchlist watchlist.txt --output reports` |
| **Python-Prozess** | `marktanalyse schedule --every 1d --at 22:15` (Intervalle: `30m`, `6h`, `1d`, `1w`) |

### Eigene Point-in-Time-Historie aufbauen

Yahoo liefert Analystenmeinungen, Short Interest und Nachrichten nur als aktuellen Stand. Wer diese Daten
später auch für historische Stichtage nutzen will, archiviert sie regelmäßig:

```bash
marktanalyse archive --watchlist watchlist.txt --target daten        # z. B. täglich
marktanalyse analyze --provider csv --data-dir daten --as-of 2026-03-02 AAPL MSFT
```

Eigene Daten (z. B. von einem anderen Anbieter) lassen sich im selben CSV-Format einspielen; das Format ist in
`marktanalyse/data/csv_store.py` beschrieben.

### Nachrichten mit Claude bewerten

Standardmäßig bewertet ein transparentes Wörterbuch-Verfahren (Deutsch und Englisch, mit Negationserkennung)
die Schlagzeilen. Mit `--llm-sentiment` übernimmt Claude (`claude-opus-5-5`) die Bewertung. Das erfasst
Zusammenhänge deutlich besser. Dafür muss das Paket `anthropic` installiert und ein API-Zugang eingerichtet
sein (`ANTHROPIC_API_KEY` oder `ant auth login`). Bei Fehlern fällt das Tool automatisch auf das Wörterbuch zurück.

## Beispielausgabe (Demo, Bärenmarkt)

```
Marktanalyse 31.03.2026 | Fallender Markt (Bärenmarkt) | Trend -0.69
Netto-Exposure: −30 % bis +30 % (Kapitalerhalt hat Vorrang)

Ticker            Kurs      KGV   Score  Konf.  Empfehlung
--------------------------------------------------------------------
VALUE            23.93      7.2   +0.18    58%  HALTEN / NEUTRAL
DIVI             40.63     16.5   -0.03    35%  HALTEN / NEUTRAL
QUALI           337.87     14.2   -0.05    42%  HALTEN / NEUTRAL
ZYKL            131.70     45.0   -0.18    60%  VERKAUF / SHORT
            Stop 149.66 | Ziel 95.79 | 44 Stück
HYPE            261.44  Verlust   -0.45    93%  VERKAUF / SHORT
            Stop 303.24 | Ziel 177.83 | 23 Stück
PLEITE            1.73  Verlust   -0.46    94%  STARKER SHORT
            Stop 1.98 | Ziel 1.23 | 3,874 Stück
* Marktphase gewechselt: sideways → bear (Fallender Markt (Bärenmarkt))
* PLEITE: VERKAUF / SHORT → STARKER SHORT (Score -0.35 → -0.46)
```

Der Markdown-Report enthält je Aktie zusätzlich Kategorie-Scores, die stärksten Argumente **dafür** und
**dagegen**, Praxisregeln (z. B. „Short-Squeeze-Gefahr: 22 % Leerverkaufsquote – Short abgeschwächt“),
den Trade-Plan, die Nachrichten und eine Tabelle aller Signale mit Begründung.

## Anpassen

* **Gewichte und Schwellen**: `config.example.toml` kopieren, anpassen, mit `--config` übergeben.
* **Eigenes Signal**: in `marktanalyse/signals.py` eine Funktion mit `@rule(...)` registrieren. Sie erscheint
  automatisch in Analyse, Report und Katalog:

```python
@rule("kgv_extrem", "Extrem niedriges KGV", "bewertung", 0.5,
      "KGV < 5", "–")
def _kgv_extrem(c: SignalContext):
    if c.fund.pe is None or c.fund.pe >= 5:
        return None
    return 0.5, c.fund.pe, f"{c.fund.pe:.1f}", "Sehr niedriges KGV"
```

* **Python-API**:

```python
from datetime import date
from marktanalyse import Analyzer
from marktanalyse.data import make_provider
from marktanalyse.report import to_markdown

rep = Analyzer(make_provider("yahoo"), benchmark="^GSPC").analyze(["AAPL", "MSFT"], date(2025, 6, 30))
for a in rep.analyses:
    print(a.ticker, a.recommendation.label, round(a.total_score, 2))
print(to_markdown(rep))
```

## Projektstruktur

```
marktanalyse/
  engine.py        Analyse zu einem Stichtag (Orchestrierung, Point-in-Time)
  indicators.py    Technische Indikatoren (SMA, RSI, MACD, Bollinger, ATR, OBV, Beta, Momentum …)
  fundamentals.py  KGV, PEG, KBV, KUV, EV/EBITDA, FCF-Rendite, ROE, Piotroski, Altman Z …
  sentiment.py     Nachrichten-Sentiment (Wörterbuch DE/EN, optional Claude)
  regime.py        Marktphasen-Erkennung
  signals.py       Signalkatalog (Regeln → Score −1 … +1)
  scoring.py       Verdichtung, Empfehlung, Praxisregeln, Trade-Plan, Portfolio-Sicht
  report.py        Markdown/JSON/Text-Report, Vergleich mit Vorlauf
  backtest.py      Walk-Forward-Backtest in regelmäßigen Abständen
  scheduler.py     Dauerbetrieb im festen Takt
  data/            Datenquellen: Yahoo, CSV-Ablage, synthetische Demo-Daten
docs/KENNZAHLEN.md Methodik & vollständiger Kennzahlen-/Signalkatalog
tests/             Tests (u. a. Look-ahead-Freiheit, Kennzahlen, Backtest, CSV-Ablage)
```

## Tests

```bash
pip install -e ".[dev]"
pytest
```
