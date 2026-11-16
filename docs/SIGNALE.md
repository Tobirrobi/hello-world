# Signal-Wächter: Kaufmails für gezieltes Einkaufen

Der Signal-Wächter prüft jeden Handelstag die 23 Werte aus `beobachtungsliste.csv` und schickt nur dann eine Mail,
wenn ein guter Zeitpunkt zum Kaufen da ist.

## Die Regel (für Einsteiger)

**Kaufmail → in Trade Republic nach der ISIN suchen, für deinen festen Betrag kaufen und behalten.**

Mehr nicht: keine Verkaufsmails, keine Stop-Orders, keine Kurse beobachten.

* **Fester Betrag:** Lege einen Betrag fest, den du pro Kaufmail investierst (z. B. 100, 250 oder 500 €). Es kommen etwa
  **9 Kaufmails pro Jahr**, gehäuft im Februar, April/Mai, Juli/August und Oktober/November. Plane also ungefähr
  9 × deinen Betrag pro Jahr ein.
* **Breit gestreut:** Höchstens **eine Kaufmail pro Aktie innerhalb von 12 Monaten**. Ohne diese Grenze kämen die
  meisten Signale von wenigen US-Tech-Firmen (Alphabet, Meta, NVIDIA, Microsoft, Amazon), und dein Depot würde einseitig.

> Keine Anlageberatung. Alle Zahlen stammen aus historischen Tests mit den heutigen Listenwerten. Das sind die Gewinner
> von heute (Survivorship-Bias), zukünftige Ergebnisse können deutlich schlechter sein. Ohne Verkaufen gibt es auch keine
> Notbremse: Fällt eine Aktie stark, bleibt sie im Depot. Investiere nur Geld, das du langfristig nicht brauchst.

## Wann kommt eine Kaufmail?

Die Firma hat Quartalszahlen gemeldet und

1. der **Gewinn je Aktie lag mindestens 5 % über der Erwartung** der Analysten, **und**
2. die Aktie stieg am Tag der Meldung **mindestens 3 % stärker als der Gesamtmarkt**.

Solche Aktien laufen oft noch wochenlang weiter gut (Fachbegriff: Post-Earnings-Drift), und man kauft eine Firma in einem
Moment, in dem sie nachweislich besser läuft als erwartet.

## Hat gezieltes Einkaufen früher etwas gebracht?

Reproduzierbar mit `marktanalyse signal-studie --start 2000-01-01` (Stand 16.11.2026). Der Standard-Modus ist der
erste Abschnitt, die übrigen Abschnitte betreffen den optionalen Modus mit Verkaufsmails.

#### Gezielt kaufen und behalten (Standard-Modus)

Vorsprung gegenüber dem Markt (Median) nach einem Kauf am Morgen nach der Meldung:

| Kauf nach … | Fälle | nach 1 Jahr | nach 2 Jahren | nach 3 Jahren | bis heute, pro Jahr |
|---|---:|---:|---:|---:|---:|
| **Kaufmail** (max. 1 je Aktie in 12 Monaten) | 170 | +9 % | +20 % | +41 % | +7.2 % |
| jedem Kaufsignal (ohne Begrenzung) | 282 | +10 % | +23 % | +46 % | +7.8 % |
| Quartalszahlen ohne Signal | 1617 | +7 % | +16 % | +26 % | +6.5 % |

Endwert, wenn man bei jedem Kauf denselben Betrag investiert und bis heute gehalten hätte – im Verhältnis zu: derselbe Betrag am selben Tag in den Index (S&P 500 bzw. DAX):

* Kaufmails: **8.4-mal** so viel wie der Index
* Käufe nach Quartalszahlen ohne Signal: 5.2-mal so viel wie der Index

Beide Werte sind stark geschönt, weil die Liste die Gewinner von heute enthält. Aussagekräftig ist nur der Vergleich der beiden Zeilen miteinander.

#### Optionaler Modus mit Verkauf: jedes Kaufsignal einzeln (3 Monate gehalten)

| Gruppe | Fälle | Ø Rendite 3 Mon. | Ø vs. Markt | Anteil positiv | schlechtester Fall |
|---|---:|---:|---:|---:|---:|
| Alle Quartalszahlen | 1876 | +4.5 % | +2.1 % | 66% | -63 % |
| **Kaufsignal** | 279 | +6.7 % | +5.1 % | 67% | -47 % |
| Kaufsignal mit Notbremse −15 % | 279 | +5.3 % | +3.6 % | 64% | -26 % |

#### Optionaler Modus mit Verkauf: Depot, wenn man jede Mail befolgt hätte (ab 04/2002, Budget ÷ 6, 0,1 % Kosten je Kauf/Verkauf, Cash ohne Zinsen)

| | Rendite p. a. | Gesamt | größter Einbruch |
|---|---:|---:|---:|
| **Signal-Strategie** (249 Käufe, 4 mangels freiem Budgetteil ausgelassen) | 10.3 % | +1002 % | -37 % |
| Alle Listenwerte gleichgewichtet halten | 22.2 % | +13823 % | -52 % |
| S&P 500 halten (ohne Dividenden) | 8.1 % | +572 % | -57 % |
| DAX halten | 6.8 % | +408 % | -58 % |

Im Schnitt waren 44% des Budgets investiert, der Rest lag als Cash bereit (z. B. auf dem Verrechnungskonto mit Zinsen – in der Simulation nicht berücksichtigt).

**Einordnung:**
* Käufe auf eine Kaufmail hin lagen nach 1, 2 und 3 Jahren im Median deutlich weiter vor dem Markt als Käufe derselben
  Aktien zu anderen Zeitpunkten (nach 3 Jahren +41 % statt +26 %). Das zeigte sich vor und nach 2015 und auch ohne
  NVIDIA.
* Der Vorteil gilt im Durchschnitt, **nicht bei jeder Aktie**: Bei etwa der Hälfte der Aktien war er sichtbar, bei der
  anderen Hälfte nicht.
* Die absoluten Zahlen (z. B. „8,4-mal so viel wie der Index“) sind stark geschönt, weil die Liste die erfolgreichen Firmen
  von heute enthält. Aussagekräftig ist nur der Vergleich „mit Signal“ gegen „ohne Signal“.
* Für viele Einsteiger ist ein **ETF-Sparplan** (z. B. MSCI World) die einfachere Basis. Gezielte Einzelkäufe können eine
  Ergänzung sein.

## Fairer Vergleich: sofort kaufen oder auf ein Signal warten?

Die entscheidende Frage für Anleger: *Ich will Aktie X kaufen. Kaufe ich heute, oder warte ich auf ein Signal?*
Getestet für jeden möglichen Starttag seit 2001: Variante A kauft sofort. Variante B wartet bis zum Signal (höchstens
12 Monate, sonst wird trotzdem gekauft). Beide werden am selben Tag 3 Jahre später abgerechnet, wartendes Geld ohne Zinsen.

| Warten auf … | deine Liste: Warten besser / gleich / schlechter | Ø Ergebnis ggü. sofort | Problemfirmen: Ø Ergebnis ggü. sofort | Lufthansa: Ø ggü. sofort |
|---|---|---:|---:|---:|
| Dip −20 % vom 52-Wochen-Hoch | 34 / 23 / 43 % | −4,5 % | −1,1 % | +0,3 % |
| Dip −30 % vom 52-Wochen-Hoch | 31 / 13 / 55 % | −5,8 % | +0,5 % | +2,6 % |
| Quartalszahlen-Kaufmail für genau diese Aktie | – | −4,8 % | +3,4 % | +2,7 % |

**Ergebnis:** Warten hat sich im Schnitt **nicht** gelohnt. Aktien steigen öfter, als sie fallen. Während man wartet, verpasst
man Gewinne, und der „Dip“ liegt oft über dem heutigen Kurs. Bei schwachen Firmen war Warten etwa gleich gut wie Sofortkaufen.

**Gegenprobe mit Problemfirmen** (Deutsche Bank, Commerzbank, Bayer, Lufthansa, Thyssenkrupp, VW, Continental, Fresenius,
Nokia, Intel, Boeing, Citigroup, Pfizer u. a.): Dort brachte das Quartalszahlen-Kaufsignal nach 3 Monaten nur
+0,5 Prozentpunkte gegenüber Käufen ohne Signal, nach 1–2 Jahren nichts. Ein Teil des Vorteils in der eigenen Liste
dürfte also daran liegen, dass sie aus den Gewinnern von heute besteht.

**Fazit:** Kein getestetes Signal schlug „sofort kaufen und langfristig halten“ verlässlich. Über das Ergebnis entscheidet
vor allem, *welche* Firmen man langfristig hält und wie breit man streut, nicht der Zeitpunkt. Die Kaufmails sind deshalb
eher eine Ideenquelle als ein belegter Vorteil. Für Einsteiger bleibt ein regelmäßiger ETF-Sparplan die robusteste Basis
(„Time in the market beats timing the market“).

## Was getestet und bewusst weggelassen wurde

* **Chartsignale mit Linien** (Kurs über/unter der 200-Tage-Linie, Golden/Death Cross, RSI über 70/unter 30, MACD,
  52-Wochen-Hoch): In einer Ereignisstudie über 23 Aktien 2001–2026 lag die Rendite danach nicht spürbar über oder unter
  dem Normalen. Bei Einzelaktien sind diese Signale Rauschen. Die 200-Tage-Linie verringert nur bei ganzen Indizes (ETFs)
  die großen Einbrüche.
* **Verkaufssignale:** auf Wunsch abgeschaltet. Mit `--mit-verkauf` gibt es sie weiterhin (nach 3 Monaten oder bei −15 %).
* **Short-Signale:** Keines hatte einen Vorteil.

## Beobachtungsliste

`beobachtungsliste.csv`: 23 große, liquide Werte, alle bei Trade Republic handelbar (Suche per ISIN):

* **Deutschland:** SAP, Siemens, Allianz, Münchener Rück, Deutsche Telekom, Rheinmetall, Infineon, Deutsche Börse, Mercedes-Benz
* **Europa:** ASML, Airbus, Novo Nordisk
* **USA:** Apple, Microsoft, NVIDIA, Amazon, Alphabet, Meta, JPMorgan, Visa, Eli Lilly, Costco, ExxonMobil

Begründung: enge Spreads beim Handel, regelmäßige Analystenschätzungen (Voraussetzung für das Signal) und gute
Datenqualität. Die Liste lässt sich ändern; für neue Werte muss Yahoo Gewinnschätzungen liefern (für LVMH, Hermès und
L'Oréal z. B. nicht).

## Täglicher Lauf

* **Zeitpunkt:** werktags 6:47 Uhr (Europe/Berlin). Ausgewertet wird der letzte abgeschlossene Börsentag, gekauft wird
  dann im Laufe des Tages.
* **Eingerichtet:** Eine geplante Claude-Aufgabe weckt werktags die Claude-Sitzung, in der das Tool entstanden ist. Sie
  führt `marktanalyse signale --seit 2026-11-16` aus und mailt bei Signalen über das verbundene Gmail-Konto. Verwalten
  oder abschalten lässt sich das in claude.ai unter den geplanten Aufgaben.
* **Alternative:** GitHub Actions (`.github/workflows/marktanalyse.yml`) mit SMTP. Dafür im Repository unter
  Settings → Secrets die Werte `MAIL_TO`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER` und `SMTP_PASSWORD` hinterlegen.
  Nur eine Variante nutzen, sonst kommen Mails doppelt.
