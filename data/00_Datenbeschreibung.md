# Datenpaket: Bestandsabgleich (Case-Aufgabe AI Solutions Partner)

Szenario: LARS NYSØM, acht Produkte, fünf Kanäle (Amazon DE, FR, IT, UK und Shopify), 22.09.2026 bis 28.09.2026 (7 Tage).
Die Produkttypen stammen aus unserem Sortiment; Mengen, Preise und alle übrigen Zahlen sind fiktiv.
Alle Exporte wurden am Dienstag, 29.09.2026, gezogen.

## So hängen die Dateien zusammen

Lagerbestand (01) → Push-Job überträgt alle 30 Minuten an jeden Kanal (03) → Kanal verarbeitet die Übertragung (04, verbunden über `submission_id`) → Abfrage-Job liest 15 Minuten später zurück, was der Kanal anzeigt (05). Bestellungen (02) verringern laufend Lager und Kanalbestand. Interne SKU und Kanal-SKU verbindet Datei 06, die Übertragungsregeln je Kanal stehen in Datei 07.

## Dateien

| Datei | Quelle | Granularität | Inhalt |
| --- | --- | --- | --- |
| 01_lagerbestand.csv | Lager (Data Warehouse) | 30 Minuten × SKU | Frei verfügbarer Bestand im eigenen Lager |
| 02_bestellungen.csv | Auftragsverwaltung | Bestellung | Bestellungen mit Versand durch uns, je Kanal |
| 03_push_protokoll.csv | Push-Job | Lauf × Kanal × SKU | Übertragene Bestände und Antwort der Schnittstelle |
| 04_verarbeitungsstatus.csv | Kanal-Schnittstellen | Übertragung | Ergebnis der Verarbeitung je Übertragung |
| 05_kanalbestand_abfragen.csv | Abfrage-Job | 30 Minuten × Kanal × Angebot | Bestand und Listing-Status, wie der Kanal ihn anzeigt |
| 06_sku_zuordnung.csv | Stammdaten | SKU × Kanal | Zuordnung interne SKU ↔ Kanal-SKU, Verkaufspreis |
| 07_kanalregeln.csv | Stammdaten | Kanal | Sicherheitspuffer und Maximalmenge je Kanal |

## Wichtige Felder

| Feld | Datei | Bedeutung |
| --- | --- | --- |
| verfuegbar | 01 | Frei verfügbarer Bestand nach allen Bestellungen bis zum Zeitpunkt (Stück); kann negativ werden |
| menge_gesendet | 03 | An den Kanal übertragener Bestand (Stück) |
| versuch | 03 | 1 = erster Versuch, 2 = Wiederholung nach Fehler |
| http_status / antwort | 03 | Unmittelbare Antwort der Schnittstelle beim Absenden |
| submission_id | 03, 04 | Kennung der Übertragung; verbindet Push und Verarbeitung |
| ergebnis / meldung | 04 | SUCCESS oder ERROR, bei ERROR mit Fehlermeldung |
| fulfillment | 05 | DEFAULT = Versand durch uns; AMAZON_EU / AMAZON_UK = Versand durch Amazon (FBA) |
| menge_angezeigt | 05 | Kaufbarer Bestand, den der Kanal zum Abfragezeitpunkt anzeigt (Stück) |
| listing_status | 05 | ACTIVE oder INACTIVE |
| abfrage_status | 05 | OK oder Fehler der Abfrage |

## Geschäftsregeln

- Zeitangaben mit Endung `Z` (Spalten `*_utc`) sind UTC. Zeitangaben ohne Zeitzone (Dateien 01 und 02) sind Ortszeit Wien (MESZ = UTC+2).
- Der Push-Job überträgt alle 30 Minuten (zur vollen und halben Stunde) den Bestand jeder SKU an alle fünf Kanäle. Der Abfrage-Job liest die Kanalbestände jeweils 15 Minuten später zurück.
- Übertragener Bestand = Lagerbestand − Sicherheitspuffer des Kanals, nicht unter 0 und höchstens die Maximalmenge (Datei 07).
- Amazon verarbeitet Übertragungen asynchron: Die Antwort beim Absenden bestätigt nur den Empfang, das Ergebnis steht in Datei 04. Shopify verarbeitet sofort.
- Nach der Übernahme eines Bestands ziehen die Kanäle neue Bestellungen selbst davon ab.
- Bestände mit Versand durch Amazon (FBA) liegen im Amazon-Lager und werden nicht von uns übertragen.
- Alle Bestellungen mit Versand durch uns werden aus demselben Lager in Wien geliefert.
- Vereinfachungen: Retouren, Stornos und Lieferzeiten sind nicht enthalten.
