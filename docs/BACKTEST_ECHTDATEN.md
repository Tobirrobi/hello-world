# Backtest auf echten Daten (Stand 16.11.2026)

**Aufbau:** 16 Werte aus `watchlist.txt` (10 US-, 6 DAX-Werte), Yahoo-Finance-Daten, Benchmark S&P 500 (`^GSPC`),
41 monatliche Stichtage von Juni 2023 bis Oktober 2026. Zu jedem Stichtag nur damals verfügbare Daten
(Kurse, Quartals-/Jahreszahlen ab Veröffentlichung). Analystendaten und Nachrichten liefert Yahoo nur aktuell –
sie fließen in den Backtest daher nicht ein.

## Fazit

| Frage | Ergebnis |
|---|---|
| Sagt der **Gesamtscore** die Reihenfolge der Folgerenditen voraus? | **Nein** – Ø Information Coefficient ≈ 0,00 (1 Monat) bzw. +0,01 (3 Monate) |
| Schlagen die Long-Empfehlungen den Index? | Ja (+24 % vs. +18 % p. a.), **aber** alle 16 Werte gleichgewichtet hätten +25,7 % p. a. gebracht. Der Vorsprung kommt aus der Auswahl der Watchlist (heutige Gewinner, Survivorship-Bias), nicht aus den Signalen |
| Welche Kennzahlgruppen funktionierten? | **Wachstum** (IC +0,12 / +0,22) und **Qualität & Bilanz** (+0,08 / +0,16), an 67–88 % der Stichtage positiv |
| Welche liefen gegenläufig? | **Bewertung** (−0,11 / −0,17) und **Trend** (−0,06): Günstige Aktien liefen 2023–2026 schlechter (Wachstums-Bullenmarkt) |
| Short-Signale | nur 9 Fälle, im Schnitt verlustreich – im fast durchgehenden Bullenmarkt kaum testbar |
| Marktphasen | 38 von 41 Stichtagen Bullenmarkt – Bärenmarkt-Logik ist mit diesem Zeitraum **nicht** validiert |

**Konsequenz:** Die Mechanik funktioniert auf echten Daten, eine verlässliche Prognosekraft des Gesamtscores ist
in diesem Test **nicht** belegt. Die Standardgewichte wurden bewusst nicht auf diesen kleinen Datensatz
angepasst (Gefahr der Überanpassung). Aussagekräftiger wäre ein Test mit einem größeren Universum
(z. B. DAX 40 + S&P 100) und einem Zeitraum, der einen echten Bärenmarkt enthält.

---

## Backtest echte Daten 2023-06 bis 2026-10 (16 Werte der Watchlist, monatlich, Haltedauer 21 Handelstage)

41 Stichtage, 656 Einzelbeobachtungen. Rendite = Kursentwicklung im Haltezeitraum nach dem Stichtag.

### Ergebnis nach Empfehlung

| Empfehlung | Anzahl | Ø Rendite | Ø vs. Index | Trefferquote |
|---|---:|---:|---:|---:|
| STARKER KAUF (Long) | 15 | +0.1 % | -0.6 % | 60% |
| KAUF (Long) | 357 | +1.8 % | +0.8 % | 63% |
| HALTEN / NEUTRAL | 275 | +2.4 % | +0.3 % | – |
| VERKAUF / SHORT | 9 | +1.8 % | -1.5 % | 33% |

### Strategien

Rendite der Strategie, wenn zu jedem Stichtag gemäß Empfehlung umgeschichtet wird.

| Strategie | Gesamt | p. a. | Volatilität | Sharpe | Max. Drawdown |
|---|---:|---:|---:|---:|---:|
| Long/Short nach Empfehlung | +88.2 % | +20.3 % | 17.1 % | 1.19 | -25.3 % |
| Nur Long-Empfehlungen | +109.1 % | +24.1 % | 17.2 % | 1.40 | -19.3 % |
| Index (Buy & Hold) | +74.2 % | +17.6 % | 14.7 % | 1.20 | -16.1 % |

Ø Information Coefficient (Rangkorrelation Score ↔ Folgerendite): -0.000

### Nach Marktphase

| Marktphase | Stichtage | Ø Long/Short je Periode | Ø Index je Periode |
|---|---:|---:|---:|
| bear | 2 | -3.6 % | +8.2 % |
| bull | 38 | +1.9 % | +1.0 % |
| sideways | 1 | +2.5 % | +4.8 % |

### Vorhersagekraft je Kategorie

Information Coefficient (Ø Rangkorrelation Kategorie-Score ↔ Folgerendite, ab 10 Stichtagen). > +0,05 gilt als nützlich, um 0 als wirkungslos, negativ als gegenläufig.

| Kategorie | Ø IC | Anteil Stichtage mit IC > 0 |
|---|---:|---:|
| Wachstum | +0.119 | 68% |
| Qualität & Bilanz | +0.082 | 67% |
| Überkauft/Überverkauft | +0.075 | 63% |
| Markt & Größe | +0.018 | 59% |
| Momentum | -0.014 | 41% |
| Risiko | -0.032 | 46% |
| Trend | -0.061 | 34% |
| Bewertung | -0.108 | 33% |
| Nachrichten & Sentiment | zu wenig Daten | 1 Stichtag(e) |

> Ein Backtest ist kein Beweis für zukünftige Ergebnisse. Transaktionskosten, Leihgebühren und Slippage sind nicht berücksichtigt.

---

## Backtest echte Daten 2023-06 bis 2026-10 (16 Werte der Watchlist, monatlich, Haltedauer 63 Handelstage)

39 Stichtage, 624 Einzelbeobachtungen. Rendite = Kursentwicklung im Haltezeitraum nach dem Stichtag.

### Ergebnis nach Empfehlung

| Empfehlung | Anzahl | Ø Rendite | Ø vs. Index | Trefferquote |
|---|---:|---:|---:|---:|
| STARKER KAUF (Long) | 15 | +3.9 % | +0.3 % | 73% |
| KAUF (Long) | 336 | +5.6 % | +1.9 % | 67% |
| HALTEN / NEUTRAL | 264 | +6.4 % | +0.7 % | – |
| VERKAUF / SHORT | 9 | +10.8 % | +4.1 % | 44% |

### Strategien

Rendite der Strategie, wenn zu jedem Stichtag gemäß Empfehlung umgeschichtet wird (überlappende Haltezeiträume auf den Stichtagsabstand umgerechnet).

| Strategie | Gesamt | p. a. | Volatilität | Sharpe | Max. Drawdown |
|---|---:|---:|---:|---:|---:|
| Long/Short nach Empfehlung | +69.6 % | +17.6 % | 10.0 % | 1.77 | -17.5 % |
| Nur Long-Empfehlungen | +91.6 % | +22.1 % | 8.4 % | 2.63 | -6.4 % |
| Index (Buy & Hold) | +73.1 % | +18.4 % | 7.8 % | 2.36 | -8.7 % |

Ø Information Coefficient (Rangkorrelation Score ↔ Folgerendite): +0.011

### Nach Marktphase

| Marktphase | Stichtage | Ø Long/Short je Periode | Ø Index je Periode |
|---|---:|---:|---:|
| bear | 2 | -17.0 % | +17.9 % |
| bull | 36 | +5.7 % | +3.7 % |
| sideways | 1 | +6.5 % | +9.1 % |

### Vorhersagekraft je Kategorie

Information Coefficient (Ø Rangkorrelation Kategorie-Score ↔ Folgerendite, ab 10 Stichtagen). > +0,05 gilt als nützlich, um 0 als wirkungslos, negativ als gegenläufig.

| Kategorie | Ø IC | Anteil Stichtage mit IC > 0 |
|---|---:|---:|
| Wachstum | +0.221 | 88% |
| Qualität & Bilanz | +0.156 | 86% |
| Überkauft/Überverkauft | +0.054 | 59% |
| Markt & Größe | +0.038 | 56% |
| Momentum | +0.003 | 51% |
| Risiko | -0.013 | 49% |
| Trend | -0.062 | 44% |
| Bewertung | -0.174 | 23% |

> Ein Backtest ist kein Beweis für zukünftige Ergebnisse. Transaktionskosten, Leihgebühren und Slippage sind nicht berücksichtigt.

_Hinweis zur 3-Monats-Auswertung: Die Haltezeiträume überlappen sich (Stichtage monatlich), daher sind Volatilität und Drawdown dort geglättet und zu niedrig ausgewiesen._
