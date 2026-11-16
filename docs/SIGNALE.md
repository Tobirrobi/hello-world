# Signal-Wächter: tägliche Kauf-/Verkaufssignale per Mail

Der Signal-Wächter (`marktanalyse signale`) prüft jeden Handelstag die Werte aus `beobachtungsliste.csv` und meldet
**nur deutliche Signale**: Er verschickt eine Mail, wenn es etwas zu tun gibt, an allen anderen Tagen bleibt er still.

> Keine Anlageberatung. Alle Zahlen stammen aus historischen Tests mit den heutigen Listenwerten
> (Survivorship-Bias: Es sind die Gewinner von heute). Zukünftige Ergebnisse können deutlich schlechter sein.

## Die Signale

| Signal | Bedingung | Was tun |
|---|---|---|
| 🟢 **KAUFEN nach starken Quartalszahlen** | Gewinn je Aktie ≥ 5 % über der Analystenschätzung **und** Kurs am Meldetag ≥ 3 % besser als der Markt | Am Morgen nach der Meldung kaufen, Notbremse −15 %, ca. 3 Monate halten |
| 🔴 **VERKAUFEN – Haltedauer erreicht** | 63 Handelstage (≈ 3 Monate) nach dem Kaufsignal | Position schließen (der Nachlauf ist vorbei) |
| 🔴 **VERKAUFEN – Notbremse** | Schlusskurs fällt > 15 % unter den Einstand | Verlust begrenzen |
| 🟡 **Marktampel ROT / GRÜN** | MSCI World (URTH) fällt > 2 % unter bzw. steigt > 2 % über seine 200-Tage-Linie | Rot: neue Käufe zurückstellen, Risiko senken · Grün: wieder normal investieren |

Ein neues Kaufsignal während der Haltedauer verlängert diese; ein widersprüchliches Verkaufssignal wird dann nicht
gemeldet. Für jedes Kaufsignal hängt der Wächter Kontext aus der Fundamentalanalyse an (Empfehlung, Score, KGV,
Warnungen wie Insolvenzrisiko).

**Kein Short-Signal**: Keines der getesteten Short-Signale hatte einen Vorteil (siehe unten). Bei Trade Republic
ginge Shorten ohnehin nur über Hebelprodukte (Knock-outs) mit hohem Risiko.

## Warum genau diese Signale? Ergebnisse der Tests

### 1. Klassische Chartsignale: kein Vorteil

Ereignisstudie über 23 Aktien, 2001–2026. Die Werte zeigen die Rendite nach dem Signal **minus** die normale
Rendite derselben Aktie:

| Signal | Fälle | nach 3 Monaten | nach 12 Monaten |
|---|---:|---:|---:|
| Trendwende über 200-Tage-Linie | 866 | −0,7 % | −1,4 % |
| Rücksetzer im Aufwärtstrend (RSI > 30) | 263 | −0,3 % | −0,7 % |
| Golden Cross (SMA50 > SMA200) | 397 | −0,8 % | −0,5 % |
| Ausbruch auf 52-Wochen-Hoch | 416 | 0,0 % | +0,2 % |
| Trendbruch unter 200-Tage-Linie | 861 | +0,3 % | −1,1 % |
| Death Cross | 393 | +0,8 % | −0,8 % |
| Erholung im Abwärtstrend (Short-Idee) | 143 | **+2,3 %** (Short hätte verloren) | +4,1 % |

Alle Abweichungen liegen im Bereich des Zufalls. Als Mail-Signal für Einzelaktien sind diese Regeln daher ungeeignet.
Auch eine Trendfolge-Strategie je Aktie (nur über der 200-Tage-Linie investiert) halbierte die Rendite
(Median 6,6 % statt 13,0 % p. a.). Die Verluste in Crashs sanken dabei zwar (Median −51 % statt −77 %), ein
zusätzlicher Trailing-Stop machte es aber nur schlechter.

### 2. Gewinnüberraschungen: belegter Vorteil (Post-Earnings-Drift)

Reproduzierbar mit `marktanalyse signal-studie --start 2000-01-01` (Stand 16.11.2026):

| Gruppe | Fälle | Ø Rendite 3 Mon. | Ø vs. Markt | Anteil positiv | schlechtester Fall |
|---|---:|---:|---:|---:|---:|
| Alle Quartalszahlen | 1876 | +4.5 % | +2.1 % | 65% | -63 % |
| **Kaufsignal** | 279 | +6.7 % | +5.1 % | 67% | -47 % |
| Kaufsignal mit Notbremse −15 % | 279 | +5.3 % | +3.6 % | 64% | -26 % |

| Marktampel | CAGR | Max. Drawdown | Sharpe | Halten: CAGR | Halten: Max. DD |
|---|---:|---:|---:|---:|---:|
| URTH ab 2012 | 8.6 % | -22 % | 0.70 | 11.9 % | -34 % |
| ^GSPC ab 2000 | 6.0 % | -23 % | 0.55 | 6.8 % | -57 % |
| ^GDAXI ab 2000 | 6.9 % | -25 % | 0.51 | 5.5 % | -69 % |

* Nach einem Kaufsignal lief die Aktie in den 3 Monaten im Schnitt **+5,1 % besser als der Markt**, nach normalen
  Quartalszahlen nur +2,1 %. Der Vorteil von rund +3 Prozentpunkten zeigte sich vor und nach 2015.
* Die Notbremse bei −15 % kostet im Schnitt etwa 1,4 Prozentpunkte, begrenzt aber den schlimmsten Fall von −47 % auf −26 %.
* Engere Stops (2–3 ATR, −10 %) schnitten schlechter ab, weil sie zu oft durch normale Schwankungen auslösten.
* Gegenrichtung: Nach deutlich verfehlten Erwartungen mit Kurseinbruch lief die Aktie **nicht** schlechter als der
  Markt. Daraus wurde deshalb kein Verkaufs- oder Short-Signal.

### 3. Marktampel: weniger Absturzrisiko

Trendfolge auf Indexebene (siehe zweite Tabelle oben) halbierte bis drittelte die maximalen Einbrüche. Die Rendite
lag mal etwas darunter (S&P 500, MSCI World), mal darüber (DAX). Die Ampel wechselt im Schnitt etwa 2-mal pro Jahr.

## Häufigkeit

Rückblickend Juli bis November 2026: 12 Meldungen (5 Käufe, 7 Verkäufe), also etwa 2–3 Mails pro Monat. Rund um die
Berichtssaisons (Ende Januar, April, Juli, Oktober) kommen sie gehäuft.

## Beobachtungsliste

`beobachtungsliste.csv`: 23 liquide Qualitäts- und Wachstumswerte, alle bei Trade Republic handelbar (Suche per
ISIN), verteilt auf Branchen und Regionen:

* **Deutschland:** SAP, Siemens, Allianz, Münchener Rück, Deutsche Telekom, Rheinmetall, Infineon, Deutsche Börse, Mercedes-Benz
* **Europa:** ASML, Airbus, Novo Nordisk
* **USA:** Apple, Microsoft, NVIDIA, Amazon, Alphabet, Meta, JPMorgan, Visa, Eli Lilly, Costco, ExxonMobil

Begründung: Große, liquide Werte haben enge Spreads (wichtig bei Trade Republic, Ausführung über LS Exchange),
regelmäßige Analystenschätzungen (Voraussetzung für das Quartalszahlen-Signal) und gute Datenqualität bei Yahoo.
Die Liste lässt sich frei ändern. Voraussetzung für Kaufsignale: Yahoo muss Gewinnschätzungen liefern (für LVMH, Hermès
und L'Oréal z. B. nicht, daher sind sie nicht in der Liste).

## Täglicher Lauf und Mail

* **Zeitpunkt:** werktags 6:47 Uhr (Europe/Berlin). Ausgewertet wird der letzte abgeschlossene Handelstag, eine Kauforder
  ist also vor bzw. bei Handelsbeginn möglich.
* **Variante A (eingerichtet):** geplante Claude-Aufgabe, die den Wächter ausführt und bei Signalen über Gmail mailt.
* **Variante B:** GitHub Actions (`.github/workflows/marktanalyse.yml`) mit SMTP. Dafür im Repository unter
  Settings → Secrets die Werte `MAIL_TO`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER` und `SMTP_PASSWORD` hinterlegen,
  z. B. ein Gmail-App-Passwort. Nur eine der beiden Varianten nutzen, sonst kommen Mails doppelt.
* **Variante C:** auf dem eigenen Rechner per cron oder Aufgabenplanung:
  `marktanalyse signale --smtp` mit denselben Umgebungsvariablen.
