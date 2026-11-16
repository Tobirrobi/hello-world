# Kennzahlen, Signale & Methodik

Dieses Dokument beschreibt, **welche Kennzahlen** das Tool auswertet, **welche Signale** daraus für eine
Long- oder Short-Position sprechen und **wie** daraus zu einem Stichtag eine Empfehlung entsteht.

> Keine Anlageberatung. Die Regeln sind bewusst transparent und anpassbar (`config.example.toml`).

---

## 1. Ablauf einer Analyse zu einem Stichtag

1. **Stichtag festlegen** (`--as-of 2025-03-14` oder heute).
2. **Nur Daten verwenden, die zum Stichtag öffentlich waren**: Kurse bis zum Stichtag,
   Quartalszahlen erst ab Veröffentlichung (Periodenende + ca. 45 Tage), Nachrichten bis zum Stichtag.
   Dadurch ist jede Analyse auch rückwirkend ohne Blick in die Zukunft reproduzierbar.
3. **Marktphase** des Vergleichsindex bestimmen (steigend / fallend / seitwärts, plus Volatilitätsstress).
4. **Kennzahlen berechnen**: technisch, fundamental, Erwartungen, Nachrichten.
5. **Signale**: Jede Regel übersetzt eine Kennzahl in einen Score von **−1 (Short)** bis **+1 (Long)**.
6. **Kategorien**: Signale werden je Kategorie gewichtet gemittelt.
7. **Gesamtscore**: Kategorien werden mit **marktphasenabhängigen Gewichten** verdichtet.
8. **Empfehlung**: Vergleich mit **marktphasenabhängigen Schwellen** → Starker Kauf / Kauf / Halten / Short / Starker Short.
9. **Praxisregeln** schwächen rechnerische Empfehlungen ab (Squeeze-Gefahr, fallendes Messer …).
10. **Trade-Plan**: Einstieg, Stop-Loss (ATR-basiert), Kursziel (Chance/Risiko 2:1), Positionsgröße.
11. **Portfolio-Sicht**: Netto-/Brutto-Exposure, Long- und Short-Strategie, Absicherung, Pair-Trades.

---

## 2. Marktphase (Regime)

Aus dem Vergleichsindex (Standard `^GSPC`, bei reinen `.DE`-Watchlists `^GDAXI`) werden vier Komponenten
auf −1 … +1 normiert und gemittelt:

| Komponente | +1 bei | −1 bei |
|---|---|---|
| Kurs vs. 200-Tage-Linie | ≥ 5 % darüber | ≥ 5 % darunter |
| SMA50 vs. SMA200 | SMA50 ≥ 3 % über SMA200 | ≥ 3 % darunter |
| Steigung SMA200 (20 Tage) | ≥ +1,5 % | ≤ −1,5 % |
| 6-Monats-Rendite | ≥ +10 % | ≤ −10 % |

* Trendscore > +0,25 → **steigender Markt (Bullenmarkt)**
* Trendscore < −0,25 → **fallender Markt (Bärenmarkt)**; außerdem immer, wenn der Index > 20 % unter dem
  52-Wochen-Hoch **und** unter der 200-Tage-Linie liegt
* sonst **Seitwärtsmarkt**
* **Volatilitätsstress**, wenn die 20-Tage-Volatilität > 30 % p. a. oder > 1,5× ihrem 3-Jahres-Median liegt:
  Schwellen werden strenger (+0,05), Positionsgrößen halbiert, Stops weiter (3× statt 2,5× ATR).

### Kategorie-Gewichte je Marktphase

| Kategorie | Bullenmarkt | Bärenmarkt | Seitwärts |
|---|---:|---:|---:|
| Bewertung | 12 % | 12 % | 18 % |
| Qualität & Bilanz | 10 % | **18 %** | 14 % |
| Wachstum | 12 % | 8 % | 10 % |
| Trend | **18 %** | 16 % | 10 % |
| Momentum | **18 %** | 12 % | 10 % |
| Überkauft/Überverkauft | 6 % | 6 % | **14 %** |
| Risiko | 6 % | **12 %** | 8 % |
| Nachrichten & Sentiment | 12 % | 10 % | 10 % |
| Markt & Größe | 6 % | 6 % | 6 % |

Begründung: Im steigenden Markt tragen Trend und Momentum die Rendite („the trend is your friend“),
im fallenden Markt schützen Bilanzqualität und geringes Risiko, seitwärts funktionieren Bewertung
und Mean-Reversion (Oszillatoren) am besten.

### Schwellen für Empfehlungen (Gesamtscore −1 … +1)

| Marktphase | Kauf ab | Starker Kauf ab | Short ab | Starker Short ab |
|---|---:|---:|---:|---:|
| Bullenmarkt | +0,15 | +0,40 | −0,30 | −0,50 |
| Bärenmarkt | +0,30 | +0,50 | −0,15 | −0,40 |
| Seitwärts | +0,20 | +0,45 | −0,20 | −0,45 |

Im Bullenmarkt reicht für einen Long weniger Evidenz, für einen Short braucht es mehr – im Bärenmarkt umgekehrt.

---

## 3. Signalkatalog

Jede Zeile ist eine Regel in `marktanalyse/signals.py`. Die genauen Stützstellen (Kennzahl → Score)
stehen direkt im Code. Das **Gewicht** bestimmt die Bedeutung innerhalb der Kategorie.
Der Katalog lässt sich jederzeit mit `marktanalyse kennzahlen --markdown` neu erzeugen.

| Kategorie | Signal (Schlüssel) | Gewicht | Spricht für LONG | Spricht für SHORT |
|---|---|---:|---|---|
| Bewertung | KGV (Kurs-Gewinn-Verhältnis) (`kgv`) | 1.5 | niedriges KGV (< 15) bei stabilen Gewinnen | sehr hohes KGV (> 35) oder Verluste |
| Bewertung | Forward-KGV vs. KGV (`forward_kgv`) | 0.8 | Forward-KGV deutlich unter KGV (Gewinne sollen steigen) | Forward-KGV über KGV (Gewinnrückgang erwartet) |
| Bewertung | PEG-Ratio (KGV / Gewinnwachstum) (`peg`) | 1.0 | PEG < 1: Wachstum günstig zu haben | PEG > 2,5: Wachstum teuer bezahlt |
| Bewertung | KBV (Kurs-Buchwert-Verhältnis) (`kbv`) | 0.6 | KBV < 1 bei positiver Eigenkapitalrendite | sehr hohes KBV ohne hohe Rendite |
| Bewertung | KUV (Kurs-Umsatz-Verhältnis) (`kuv`) | 0.6 | KUV < 1 | KUV > 8 (hohe Erwartungen eingepreist) |
| Bewertung | EV/EBITDA (`ev_ebitda`) | 1.0 | EV/EBITDA < 8 (inkl. Schulden günstig) | EV/EBITDA > 18 |
| Bewertung | Free-Cashflow-Rendite (`fcf_rendite`) | 1.2 | FCF-Rendite > 5 %: Unternehmen erwirtschaftet viel Geld | negativer Free Cashflow: verbrennt Geld |
| Bewertung | Dividendenrendite & Ausschüttungsquote (`dividende`) | 0.5 | solide Dividende (2–7 %) mit Ausschüttungsquote < 80 % | Ausschüttung > Gewinn oder Rendite > 10 % (Kürzungsgefahr) |
| Bewertung | Relative Bewertung im Universum (Gewinnrendite-Rang) (`rel_bewertung`) | 0.8 | günstigste Aktien des Universums | teuerste Aktien des Universums |
| Qualität & Bilanz | Eigenkapitalrendite (ROE) (`roe`) | 1.0 | ROE > 15 %: profitables Geschäftsmodell | negative oder sehr niedrige ROE |
| Qualität & Bilanz | Operative Marge (`marge`) | 0.6 | operative Marge > 15 % | operative Verluste |
| Qualität & Bilanz | Margenentwicklung (ggü. Vorjahr) (`marge_trend`) | 0.6 | steigende Margen (Preissetzungsmacht) | fallende Margen (Wettbewerbs-/Kostendruck) |
| Qualität & Bilanz | Verschuldungsgrad (Debt/Equity) (`verschuldung`) | 0.7 | geringe Verschuldung (< 0,5) | hohe Verschuldung (> 2) oder negatives Eigenkapital |
| Qualität & Bilanz | Nettoverschuldung / EBITDA (`nettoverschuldung`) | 0.8 | Netto-Cash oder < 1x EBITDA | > 4x EBITDA: Refinanzierungsrisiko |
| Qualität & Bilanz | Current Ratio (Liquidität 2. Grades) (`liquiditaet`) | 0.4 | Current Ratio > 1,5 | Current Ratio < 1 (kurzfristige Zahlungsengpässe möglich) |
| Qualität & Bilanz | Zinsdeckungsgrad (EBIT / Zinsen) (`zinsdeckung`) | 0.5 | Zinsen > 6-fach durch EBIT gedeckt | Zinsen kaum gedeckt (< 2x) |
| Qualität & Bilanz | Piotroski F-Score (0–9) (`piotroski`) | 1.2 | F-Score ≥ 7: sich verbessernde Fundamentaldaten | F-Score ≤ 3: sich verschlechternde Fundamentaldaten |
| Qualität & Bilanz | Altman Z-Score (Insolvenzrisiko) (`altman_z`) | 1.0 | Z > 3: finanziell solide | Z < 1,8: erhöhtes Insolvenzrisiko |
| Wachstum | Umsatzwachstum (ggü. Vorjahr) (`umsatzwachstum`) | 1.0 | Umsatzwachstum > 10 % | schrumpfender Umsatz |
| Wachstum | Gewinnwachstum je Aktie (EPS) (`gewinnwachstum`) | 1.0 | EPS-Wachstum > 10 % | fallende Gewinne je Aktie |
| Trend | Kurs vs. 200-Tage-Linie (`sma200`) | 1.3 | Kurs über steigender 200-Tage-Linie (langfristiger Aufwärtstrend) | Kurs unter 200-Tage-Linie (Abwärtstrend) |
| Trend | Golden Cross / Death Cross (SMA50 vs. SMA200) (`golden_cross`) | 1.0 | SMA50 kreuzt SMA200 nach oben (Golden Cross) | SMA50 kreuzt SMA200 nach unten (Death Cross) |
| Trend | Steigung der 200-Tage-Linie (`sma200_steigung`) | 0.6 | steigende 200-Tage-Linie | fallende 200-Tage-Linie |
| Trend | MACD-Histogramm (`macd`) | 0.7 | MACD dreht über Signallinie | MACD fällt unter Signallinie |
| Momentum | 12-Monats-Momentum (ohne letzten Monat) (`momentum_12_1`) | 1.3 | starke 12-Monats-Performance (Gewinner bleiben oft Gewinner) | schwache 12-Monats-Performance |
| Momentum | 3-Monats-Rendite (`rendite_3m`) | 0.7 | positive mittelfristige Dynamik | negative mittelfristige Dynamik |
| Momentum | Relative Stärke vs. Index (6 Monate) (`relative_staerke`) | 1.0 | Aktie schlägt den Markt | Aktie läuft schlechter als der Markt |
| Momentum | Abstand zum 52-Wochen-Hoch (`hoch_52w`) | 0.6 | nahe am 52-Wochen-Hoch (Ausbruchsstärke) | weit unter dem 52-Wochen-Hoch |
| Momentum | Volumen / On-Balance-Volume (`volumen`) | 0.6 | steigende Kurse mit hohem Volumen (Akkumulation) | fallende Kurse mit hohem Volumen (Distribution) |
| Momentum | Relatives Momentum im Universum (Rang) (`rel_momentum`) | 0.8 | stärkste Aktien des Universums | schwächste Aktien des Universums |
| Überkauft/Überverkauft | RSI (14 Tage) (`rsi`) | 1.0 | RSI < 30 im Aufwärtstrend (Rücksetzer kaufen) | RSI > 70 im Abwärtstrend (Erholung shorten) |
| Überkauft/Überverkauft | Bollinger-Bänder (%B) (`bollinger`) | 0.5 | Kurs am/unter dem unteren Band | Kurs am/über dem oberen Band |
| Überkauft/Überverkauft | Abstand zur 50-Tage-Linie (`abstand_sma50`) | 0.5 | deutlich unter SMA50 (Rückkehr zum Mittelwert) | deutlich über SMA50 (überdehnt) |
| Risiko | Volatilität (60 Tage, annualisiert) (`volatilitaet`) | 0.8 | niedrige Schwankung (Low-Volatility-Effekt) | extreme Schwankung (Lotterie-Aktie) |
| Risiko | Maximaler Drawdown (1 Jahr) (`drawdown`) | 0.5 | geringe Rückschläge im letzten Jahr | tiefer Einbruch im letzten Jahr |
| Nachrichten & Sentiment | Nachrichten-Sentiment (`nachrichten`) | 1.2 | überwiegend positive aktuelle Nachrichten | negative Schlagzeilen (Gewinnwarnung, Klage, Herabstufung …) |
| Nachrichten & Sentiment | Analysten-Konsens (`analysten`) | 0.6 | überwiegend Kaufempfehlungen | überwiegend Verkaufsempfehlungen |
| Nachrichten & Sentiment | Kurspotenzial bis Analysten-Kursziel (`kursziel`) | 0.7 | Kursziel > 20 % über aktuellem Kurs | Kursziel unter aktuellem Kurs |
| Nachrichten & Sentiment | Short Interest (Leerverkaufsquote) (`short_interest`) | 0.6 | geringe Leerverkaufsquote | hohe Leerverkaufsquote (Profis wetten auf Fall) – aber Squeeze-Gefahr |
| Nachrichten & Sentiment | Insider-Transaktionen (`insider`) | 0.6 | Insider kaufen eigene Aktien | Insider verkaufen massiv |
| Markt & Größe | Rückenwind durch Gesamtmarkt (`marktphase`) | 1.0 | Index im Aufwärtstrend (die Flut hebt alle Boote) | Index im Abwärtstrend (Gegenwind für alle Longs) |
| Markt & Größe | Beta (Marktsensitivität) (`beta`) | 0.8 | hohes Beta im Bullenmarkt / niedriges Beta im Bärenmarkt | hohes Beta im Bärenmarkt |
| Markt & Größe | Marktkapitalisierung (Size) (`groesse`) | 0.6 | Small Caps im frühen Bullenmarkt, Mega Caps im Bärenmarkt | Micro/Small Caps im Bärenmarkt (Flucht in Qualität) |

### Kennzahlen kurz erklärt

| Kennzahl | Formel | Interpretation |
|---|---|---|
| **KGV** | Kurs / Gewinn je Aktie (12 Monate) | Wie viele Jahresgewinne kostet die Aktie? Branchenabhängig, < 15 eher günstig, > 35 teuer |
| **Forward-KGV** | Kurs / erwarteter Gewinn je Aktie | Liegt es unter dem KGV, erwarten Analysten steigende Gewinne |
| **PEG** | KGV / (Gewinnwachstum in %) | Bewertung relativ zum Wachstum, < 1 günstig |
| **KBV** | Marktkapitalisierung / Eigenkapital | < 1: Börse bewertet unter Buchwert (Achtung Value-Falle bei Verlusten) |
| **KUV** | Marktkapitalisierung / Umsatz | Für Verlustfirmen nutzbar, > 8 = viel Zukunft eingepreist |
| **EV/EBITDA** | (Marktkap. + Schulden − Cash) / EBITDA | Bewertung inkl. Verschuldung, gut für Branchenvergleiche |
| **FCF-Rendite** | Free Cashflow / Marktkapitalisierung | Wie viel freies Geld erwirtschaftet das Unternehmen je investiertem Euro |
| **Marktkapitalisierung** | Kurs × Aktienanzahl | Größenklasse: Micro < 300 Mio., Small < 2 Mrd., Mid < 10 Mrd., Large < 200 Mrd., Mega |
| **ROE** | Nettogewinn / Eigenkapital | Profitabilität, > 15 % gut |
| **Debt/Equity, Nettoverschuldung/EBITDA** | | Bilanzrisiko; > 4× EBITDA kritisch |
| **Piotroski F-Score** | 9 Ja/Nein-Tests (Rentabilität, Cashflow, Verschuldung, Liquidität, Verwässerung, Marge, Kapitalumschlag) | ≥ 7 starke, ≤ 3 schwache Fundamentaldynamik |
| **Altman Z-Score** | 1,2·WC/TA + 1,4·RE/TA + 3,3·EBIT/TA + 0,6·MK/FK + 1,0·Umsatz/TA | < 1,81 Insolvenzgefahr, > 2,99 sicher (nicht für Banken/Versicherer) |
| **SMA50/SMA200** | gleitende Durchschnitte | Golden Cross (50 kreuzt 200 nach oben) / Death Cross |
| **RSI** | Relative Strength Index (14) | < 30 überverkauft, > 70 überkauft – Bedeutung hängt vom Trend ab |
| **MACD** | EMA12 − EMA26 vs. Signallinie | Kreuzungen = Trendwechsel-Signale |
| **Bollinger %B** | Lage im 20-Tage-±2σ-Band | < 0 / > 1 statistisch überdehnt |
| **Momentum 12-1** | 12-Monats-Rendite ohne letzten Monat | Bekanntester Momentum-Faktor: Gewinner bleiben oft Gewinner |
| **Relative Stärke** | 6M-Rendite Aktie − Index | Schlägt die Aktie den Markt? |
| **Beta** | Kovarianz(Aktie, Index) / Varianz(Index) | > 1 schwankt stärker als der Markt |
| **ATR** | Average True Range (14) | Typische Tagesschwankung → Stop-Abstand |
| **OBV** | On-Balance-Volume | Steigt das Volumen mit steigenden Kursen (Akkumulation) oder fallenden (Distribution)? |
| **Short Interest** | leerverkaufte Aktien / Free Float | Hohe Quote = Profis bearish, aber Short-Squeeze-Gefahr |
| **Nachrichten-Sentiment** | Lexikon DE/EN oder Claude, Halbwertszeit 3 Tage | Gewinnwarnungen, Prognoseänderungen, Herabstufungen, Klagen … |

---

## 4. Playbook: Was spricht wann für Long, was für Short?

### Steigender Markt (Bullenmarkt)
**Long bevorzugt**, Netto-Exposure +60 … +100 %.
* ✅ Long: Kurs über steigender 200-Tage-Linie, frisches Golden Cross, starkes 12-1-Momentum, positive
  relative Stärke, Rücksetzer auf RSI 30–40, Gewinnwachstum mit PEG < 2, positive Nachrichten/Prognoseanhebungen.
* ⚠️ Short nur selektiv: Death Cross + negative Gewinndynamik + hohe Bewertung + schlechte Nachrichten.
  **Niemals gegen einen intakten Aufwärtstrend shorten** (Praxisregel).

### Fallender Markt (Bärenmarkt)
**Kapitalerhalt**, Netto-Exposure −30 … +30 %, Index-Absicherung.
* ✅ Short: hohe Bewertung (KGV > 35, KUV > 8) **und** schwache Bilanz (Nettoverschuldung > 4× EBITDA,
  Altman Z < 1,8, negativer FCF) **und** Abwärtstrend (unter fallender SMA200, Death Cross, negatives Momentum)
  **und** negative Nachrichten. Einstieg bevorzugt in Erholungen (RSI > 60–70 unter SMA200).
* ✅ Long nur defensiv: niedriges Beta, Netto-Cash, hohe FCF-Rendite, stabile Dividende.
  **Nicht ins fallende Messer greifen** (Praxisregel).

### Seitwärtsmarkt
**Selektiv**, Netto-Exposure +20 … +60 %, Pair-Trades.
* ✅ Long: günstige Bewertung + gute Qualität an Unterstützungen (unteres Bollinger-Band, RSI < 35).
* ✅ Short: teure, schwache Titel an Widerständen (oberes Band, RSI > 70).
* ✅ Pair-Trade: Long bester / Short schwächster Wert derselben Branche neutralisiert das Marktrisiko.

---

## 5. Praxisregeln (Vetos)

| Regel | Wirkung |
|---|---|
| Short-Squeeze-Gefahr (Short Interest ≥ 20 %) | Short um eine Stufe abgeschwächt, bei steigendem Kurs → Halten |
| Geringe Liquidität (< 1 Mio. Ø-Tagesumsatz) | kein Short (Leihe knapp/teuer) |
| Bullenmarkt + Aktie im intakten Aufwärtstrend (Momentum > 20 %) | Short eine Stufe abgeschwächt |
| Bärenmarkt + Aktie im Abwärtstrend (Momentum < −20 %) | Long eine Stufe abgeschwächt („fallendes Messer“) |
| Altman Z < 1,81 | kein „Starker Kauf“ |
| Quartalszahlen in ≤ 7 Tagen | Hinweis, Positionsgröße halbiert |
| Datenabdeckung < 50 % | Hinweis auf eingeschränkte Aussagekraft |

---

## 6. Risiko & Positionsgröße

* **Stop-Loss** = Einstieg ∓ 2,5 × ATR(14) (bei Volatilitätsstress 3 × ATR)
* **Kursziel** = Einstieg ± 2 × Stop-Abstand (Chance/Risiko 2:1)
* **Positionsgröße** = (Kapital × 1 % Risiko × Konfidenz-Faktor × Marktphasen-Faktor) / Stop-Abstand,
  begrenzt auf 10 % des Kapitals
* Marktphasen-Faktor: Bullenmarkt Long 1,0 / Short 0,5 · Bärenmarkt Long 0,5 / Short 1,0 · seitwärts 0,75 / 0,75
* Bei jedem regelmäßigen Lauf prüft das Tool, ob Stop-Loss oder Kursziel der letzten Analyse erreicht wurden.

---

## 7. Datenquellen & Point-in-Time-Grenzen

| Daten | Yahoo Finance | Historisch nutzbar? |
|---|---|---|
| Kurse, Volumen | ✅ | ✅ vollständig |
| Quartals-/Jahreszahlen | ✅ ca. 5 Quartale / 4 Jahre | ✅ ab Veröffentlichung (+45 bzw. +75 Tage) |
| Analysten, Kursziele, Forward-EPS, Short Interest, Insider | nur aktueller Stand | ❌ – nur in Analysen der letzten Wochen |
| Nachrichten | nur aktuelle Meldungen | ❌ – außer selbst archiviert |

Lösung: `marktanalyse archive` regelmäßig ausführen (z. B. täglich per GitHub Actions oder cron). So entsteht
eine eigene Point-in-Time-Datenbank (`--provider csv --data-dir daten`), mit der später auch historische
Analysen inklusive Nachrichten und Analystenmeinungen möglich sind.

## 8. Grenzen

* Feste Schwellen ignorieren Branchenunterschiede (ein KGV von 25 ist für Software normal, für Versorger teuer).
  Die **relative Bewertung im Universum** mildert das, wenn Sie Werte einer Branche gemeinsam analysieren.
* Das Lexikon-Sentiment erkennt keine Ironie oder Zusammenhänge – `--llm-sentiment` nutzt dafür Claude.
* Der Demo-Backtest läuft auf synthetischen Daten, in die die Profile (z. B. „Krisen AG“) bewusst eingebaut sind –
  er zeigt die Mechanik, beweist aber keine Prognosekraft. Aussagekräftig ist nur ein Backtest auf echten Daten.
