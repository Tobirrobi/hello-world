# Signal-Wächter: Kaufmail und Verkaufsmail

Der Signal-Wächter prüft jeden Handelstag die 23 Werte aus `beobachtungsliste.csv` und schickt nur dann eine Mail,
wenn etwas zu tun ist.

## Die Regel (für Einsteiger)

| Mail | Was du tust |
|---|---|
| 🟢 **KAUFEN: Firma** | In Trade Republic nach der ISIN aus der Mail suchen und für deinen festen Betrag kaufen. Dann einfach halten. |
| 🔴 **VERKAUFEN: Firma** | In Trade Republic die Aktie im Depot antippen und alles verkaufen. |

Sonst nichts: keine Stop-Orders einstellen, keine Kurse beobachten, nicht nachkaufen.

**Fester Betrag:** Teile das Geld, das du in Aktien stecken willst, in **6 gleiche Teile**. Pro Kaufmail kaufst du für einen
Teil. In der Vergangenheit waren meist 3, selten mehr als 5 Aktien gleichzeitig im Depot. Sind ausnahmsweise alle 6 Teile
investiert, lässt du die Kaufmail aus.

> Keine Anlageberatung. Alle Zahlen stammen aus historischen Tests mit den heutigen Listenwerten. Das sind die Gewinner
> von heute (Survivorship-Bias), zukünftige Ergebnisse können deutlich schlechter sein. Investiere nur Geld, auf das du
> verzichten kannst.

## Wann kommt welche Mail?

* **Kaufmail:** Die Firma hat Quartalszahlen gemeldet. Der Gewinn je Aktie lag **mindestens 5 % über der Erwartung der
  Analysten** und die Aktie stieg am Tag der Meldung **mindestens 3 % stärker als der Gesamtmarkt**. Solche Aktien laufen
  oft noch wochenlang weiter gut (Fachbegriff: Post-Earnings-Drift).
* **Verkaufsmail**, sobald eins davon eintritt:
  * **3 Monate** (63 Handelstage) nach dem Kaufsignal: Der Effekt ist dann vorbei.
  * **Notbremse:** Die Aktie liegt mehr als **15 % unter dem Kaufkurs**. Das begrenzt Verluste.
* Kommt für eine Aktie, die du schon hast, erneut ein Kaufsignal, gibt es **keine** Mail. Du hältst einfach weiter, die
  3 Monate beginnen neu.
* Verkaufsmails gibt es nur für Aktien, zu denen du eine Kaufmail bekommen hast (Start: 16.11.2026).

## Wie gut hat das früher funktioniert?

Reproduzierbar mit `marktanalyse signal-studie --start 2000-01-01` (Stand 16.11.2026):

### Jedes Kaufsignal einzeln (3 Monate gehalten)

| Gruppe | Fälle | Ø Rendite 3 Mon. | Ø vs. Markt | Anteil positiv | schlechtester Fall |
|---|---:|---:|---:|---:|---:|
| Alle Quartalszahlen | 1876 | +4.5 % | +2.1 % | 65% | -63 % |
| **Kaufsignal** | 279 | +6.7 % | +5.1 % | 67% | -47 % |
| Kaufsignal mit Notbremse −15 % | 279 | +5.3 % | +3.6 % | 64% | -26 % |

### Depot, wenn man jede Mail befolgt hätte (ab 04/2002, Budget ÷ 6, 0,1 % Kosten je Kauf/Verkauf, Cash ohne Zinsen)

| | Rendite p. a. | Gesamt | größter Einbruch |
|---|---:|---:|---:|
| **Signal-Strategie** (249 Käufe, 4 mangels freiem Budgetteil ausgelassen) | 10.3 % | +1002 % | -37 % |
| Alle Listenwerte gleichgewichtet halten | 22.2 % | +13823 % | -52 % |
| S&P 500 halten (ohne Dividenden) | 8.1 % | +572 % | -57 % |
| DAX halten | 6.8 % | +408 % | -58 % |

Im Schnitt waren 44% des Budgets investiert, der Rest lag als Cash bereit (z. B. auf dem Verrechnungskonto mit Zinsen – in der Simulation nicht berücksichtigt).

**Einordnung:**
* Die Signal-Strategie brachte gut 10 % pro Jahr, mit deutlich kleineren Einbrüchen als die Indizes
  (−37 % statt −57 %). Dabei war im Schnitt weniger als die Hälfte des Geldes investiert.
* Ein breiter **ETF (z. B. S&P 500 oder MSCI World) mit Dividenden** hätte über die Zeit ungefähr ähnlich viel gebracht,
  bei größeren Schwankungen und ganz ohne Aufwand. Für viele Einsteiger ist ein ETF-Sparplan die einfachere Basis; die
  Signale können eine Ergänzung sein.
* „Alle Listenwerte halten“ sieht spektakulär aus, ist aber nicht erreichbar: Niemand wusste 2002, dass genau diese
  Firmen (z. B. NVIDIA) die Gewinner werden.

## Was getestet und bewusst weggelassen wurde

* **Klassische Chartsignale** (Trendwende an der 200-Tage-Linie, RSI-Rücksetzer, Golden/Death Cross, 52-Wochen-Hoch,
  Trendbruch): In einer Ereignisstudie über 23 Aktien 2001–2026 lag die Rendite danach nicht spürbar über oder unter dem
  Normalen. Diese Signale wären reines Rauschen.
* **Trailing-Stop / enge Stops (2–3 ATR, −10 %):** Sie schnitten schlechter ab als die Notbremse bei −15 %, weil sie bei
  normalen Schwankungen auslösen.
* **Marktampel** (Index über/unter der 200-Tage-Linie): Sie verringert große Einbrüche bei Index-Investments. Für die
  Kaufsignale brachte sie aber nichts, denn Kaufsignale in schwachen Marktphasen liefen nicht schlechter. Für die
  Einfachheit ist sie deshalb nicht Teil der Mails.
* **Short-Signale:** Keines hatte einen Vorteil. Bei Trade Republic wären sie ohnehin nur über Hebelprodukte möglich.

## Häufigkeit

Rückblickend Juli bis November 2026: 8 Mails (5 Käufe, 3 Verkäufe), also etwa 1–3 pro Monat, gehäuft in den
Berichtssaisons (Ende Januar, April, Juli, Oktober). An den übrigen Tagen kommt nichts.

## Beobachtungsliste

`beobachtungsliste.csv`: 23 große, liquide Werte, alle bei Trade Republic handelbar (Suche per ISIN):

* **Deutschland:** SAP, Siemens, Allianz, Münchener Rück, Deutsche Telekom, Rheinmetall, Infineon, Deutsche Börse, Mercedes-Benz
* **Europa:** ASML, Airbus, Novo Nordisk
* **USA:** Apple, Microsoft, NVIDIA, Amazon, Alphabet, Meta, JPMorgan, Visa, Eli Lilly, Costco, ExxonMobil

Begründung: enge Spreads beim Handel, regelmäßige Analystenschätzungen (Voraussetzung für das Signal) und gute
Datenqualität. Die Liste lässt sich ändern; für neue Werte muss Yahoo Gewinnschätzungen liefern (für LVMH, Hermès und
L'Oréal z. B. nicht).

## Täglicher Lauf

* **Zeitpunkt:** werktags 6:47 Uhr (Europe/Berlin). Ausgewertet wird der letzte abgeschlossene Börsentag, gekauft bzw.
  verkauft wird dann im Laufe des Tages.
* **Eingerichtet:** Eine geplante Claude-Aufgabe weckt werktags die Claude-Sitzung, in der das Tool entstanden ist. Sie
  führt `marktanalyse signale --seit 2026-11-16` aus und mailt bei Signalen über das verbundene Gmail-Konto. Verwalten
  oder abschalten lässt sich das in claude.ai unter den geplanten Aufgaben.
* **Alternative:** GitHub Actions (`.github/workflows/marktanalyse.yml`) mit SMTP. Dafür im Repository unter
  Settings → Secrets die Werte `MAIL_TO`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER` und `SMTP_PASSWORD` hinterlegen
  (z. B. ein Gmail-App-Passwort). Nur eine Variante nutzen, sonst kommen Mails doppelt.
* Kurse in der Studie stehen in der Börsenwährung (USD bei US-Aktien). Dein Ergebnis bei Trade Republic in Euro weicht
  wegen des Wechselkurses etwas ab.
