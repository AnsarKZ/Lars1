# Datenpaket: Performance-Dashboard (Case-Aufgabe AI Solutions Partner)

Szenario: LARS NYSØM, acht Produkte, vier Amazon-Marktplätze (DE, FR, IT, UK), 30.03.2026 bis 27.09.2026 (26 Wochen).
Die Produkttypen stammen aus unserem Sortiment; Mengen, Preise und alle übrigen Zahlen sind fiktiv.
Alle Exporte wurden am Montag, 28.09.2026, gezogen.

## Dateien

| Datei | Quelle | Granularität | Inhalt |
| --- | --- | --- | --- |
| 01_amazon_sales_traffic_2026.csv | Amazon Business Report | Tag × Marktplatz × SKU | Traffic, Bestellungen, Umsatz, Buy-Box-Anteil |
| 02_amazon_ads_sponsored_products_2026.csv | Amazon Advertising | Tag × Kampagne × SKU | Budget, Impressionen, Klicks, Kosten, Werbeumsatz |
| 03_fba_bestand_wochenstichtag.csv | Lager-Export | Woche × Region × SKU | Verfügbarer, reservierter und eingehender Bestand |
| 04_produktstamm_controlling.xlsx | Controlling | SKU | Kosten, Gebühren, Wiederbeschaffungszeit, Listenpreise |
| 05_fx_monatskurse.csv | Finanzbuchhaltung | Monat | Durchschnittskurs GBP → EUR |

## Wichtige Felder

| Feld | Datei | Bedeutung |
| --- | --- | --- |
| sessions | 01 | Besuche der Produktseite |
| units_ordered | 01 | Bestellte Einheiten |
| ordered_product_sales | 01 | Umsatz der bestellten Einheiten, in Landeswährung |
| buy_box_pct | 01 | Anteil der Seitenaufrufe, bei denen unser Angebot im Warenkorb-Feld stand (%) |
| daily_budget | 02 | Tagesbudget der Kampagne |
| spend | 02 | Werbekosten |
| sales_7d / orders_7d | 02 | Werbeumsatz und Bestellungen, die einem Werbeklick innerhalb von 7 Tagen zugeordnet werden |
| Verfuegbar / Reserviert / Eingehend | 03 | Verkaufbarer Bestand, reservierter Bestand, Ware auf dem Weg ins Lager (Stück) |
| Bestandswert_EUR | 03 | Verfügbarer Bestand bewertet zu Landed Cost |

## Geschäftsregeln

- Umsätze in Datei 01 und Werbeumsätze in Datei 02 sind brutto inklusive Umsatzsteuer. Sätze: DE 19 %, FR 20 %, IT 22 %, UK 20 %.
- Werbekosten (spend) sind netto.
- Der Marktplatz UK rechnet in GBP, alle anderen in EUR. Für die Umrechnung gilt der Monatsdurchschnittskurs aus Datei 05.
- Amazon-Kosten je verkaufter Einheit: 15 % Verkaufsgebühr vom Bruttopreis plus die FBA-Gebühr laut Produktstamm (vereinfacht in EUR für alle Marktplätze).
- Der Bestand für DE, FR und IT liegt in einem gemeinsamen EU-Lagerpool. UK hat ein eigenes Lager.
- Ein Bestands-Stichtag (Montag) zeigt den Bestand nach allen Verkäufen bis einschließlich Sonntag.
- Vereinfachungen: Retouren, Rabattaktionen und die tatsächliche Abrechnung der Lagergebühren sind nicht enthalten. Die Lagergebühr je Einheit und Monat steht im Produktstamm.
