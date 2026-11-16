# ETF-Check: Lohnt sich gerade Extra-Geld zusätzlich zum Sparplan?

Der ETF-Check zeigt für bekannte ETFs, wie weit sie unter ihrem bisherigen Höchststand liegen und ob das historisch ein
besonders guter Zeitpunkt für zusätzliches Geld war. Er ergänzt einen laufenden Sparplan und ersetzt ihn nicht.

```bash
marktanalyse etf-check                       # Text-Ausgabe
marktanalyse etf-check --json etf.json       # inkl. Alarm-Mail, falls fällig
marktanalyse etf-check --dashboard-dir out/  # Dateien für die Dashboard-Seite
```

## Beobachtete ETFs

| ETF | ISIN | Art | kann „guter Zeitpunkt“ zeigen |
|---|---|---|---|
| iShares Core MSCI World | IE00B4L5Y983 | Welt (Industrieländer) | ja |
| Vanguard FTSE All-World (thesaurierend) | IE00BK5BQT80 | Welt inkl. Schwellenländer | ja |
| iShares Core S&P 500 | IE00B5BMR087 | USA | ja |
| iShares Core DAX | DE0005933931 | Deutschland | nein |
| iShares Nasdaq 100 | IE00B53SZB19 | USA Technologie | nein |
| iShares Core MSCI EM IMI | IE00BKM4GZ66 | Schwellenländer | nein |

## Die Regel

* **Guter Zeitpunkt:** nur bei breiten ETFs und nur, wenn sie **mehr als 20 % unter ihrem Höchststand** liegen.
* **Sonst normaler Zeitpunkt:** Extra-Geld kann man trotzdem investieren, denn Warten auf einen Rücksetzer lohnte sich im
  Schnitt nicht.
* **Alarm-Mail**, wenn ein breiter ETF neu unter −20 % rutscht. Seit 2012 wäre das dreimal passiert: Februar 2016,
  März 2020 und April 2025.

## Warum so streng? Die Tests (Stand 16.11.2026)

**1. Kauf in Abhängigkeit vom Abstand zum Höchststand.** Rendite in den 3 Jahren danach (Median) und Anteil der Fälle
mit Verlust:

| Index | normal (beliebiger Tag) | 10–20 % unter Hoch | mehr als 20 % unter Hoch |
|---|---|---|---|
| S&P 500 (seit 1950) | +28 %, Verlust 14 % | +29 %, Verlust 21 % | **+34 %, Verlust 4 %** |
| DAX (seit 1988) | +28 %, Verlust 20 % | +25 %, Verlust 19 % | +36 %, Verlust 24 % |
| Nasdaq 100 (seit 1985) | +53 %, Verlust 12 % | +64 %, Verlust 6 % | +44 %, Verlust 18 % |
| Schwellenländer EEM (seit 2003) | +13 %, Verlust 29 % | +3 %, Verlust 42 % | +27 %, Verlust 4 % |

Nur beim breiten US-Markt war ein Crash durchgängig ein klar besserer Einstieg. Beim DAX stieg die Rendite, aber auch
das Verlustrisiko. Beim Nasdaq liefen Käufe im Crash schlechter, weil die Erholung nach 2000 rund 15 Jahre dauerte.
Kleinere Rücksetzer brachten nirgends einen verlässlichen Vorteil.

**2. Geld zurückhalten für Einbrüche lohnt sich nicht.** Verglichen wurde ein Sparplan mit 100 € im Monat gegen
80 € im Monat plus 20 € Reserve, die erst bei einem Einbruch investiert wird. Über alle 10-Jahres-Zeiträume war die
Reserve-Variante im Schnitt **schlechter**: S&P 500 −2,0 %, DAX −0,9 % (Reserve bei −20 % investiert). Selbst mit
2 % Zinsen auf die Reserve blieb sie schlechter.

**Fazit:** Der Sparplan bleibt die Basis. Der ETF-Check sagt, wann *zusätzliches* Geld, das man ohnehin übrig hat,
historisch besonders gut angelegt war, und das ist selten.

## Technik

* Daten: Yahoo Finance, Schlusskurse der ETFs (Xetra/Euronext, in Euro). Als Vergleich dienen Indizes mit langer
  Historie (S&P 500, DAX, Nasdaq 100, EEM).
* Die Dashboard-Seite liest zwei Dateien (`etf_status.json`, `etf_verlauf.json`), die der tägliche Lauf werktags
  um 6:47 Uhr neu berechnet und hochlädt.
* Keine Anlageberatung. Vergangene Entwicklungen sind keine Garantie für die Zukunft.
