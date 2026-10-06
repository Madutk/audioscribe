# Übersicht Domäne Assistenz

> KI-erzeugtes Lagebild auf Basis des Wiki-Stands vom 2026-10-06.

## Stand

Drei Quellen sind eingearbeitet: der Prozessüberblick zur Bahnbuchung vom 2026-09-08 ([[Q-001-bahn-01-prozessueberblick|Q-001]]), die Vertiefung zu Tarif, Bezahlung und Ablage vom 2026-09-15 ([[Q-002-bahn-02-buchung-und-bezahlung|Q-002]]) und die Aufnahme zu Änderungen, Storno und Sonderfällen vom 2026-09-22 ([[Q-003-bahn-03-aenderungen-und-sonderfaelle|Q-003]]). Das Wiki kennt drei Prozesse, fünfzehn Anforderungen im Entwurf, vier Systeme, sechs Rollen und dreizehn offene Punkte, davon einer geklärt. Widersprüche und Entscheidungen gibt es keine.

## Prozesse

- [[PRO-001-bahnbuchung|PRO-001]] Bahnbuchung für Teammitglieder, 14 Schritte: Reiseanfrage per E-Mail an das Teampostfach, Vollständigkeitsprüfung, Buchung auf bahn.de mit Geschäftskundenkonto (Klasse, Tarif, BahnCard, Sitzplatz, ggf. Freigabe), Bezahlung mit Firmenkreditkarte, Ticket per E-Mail, Rechnung aufs Teamlaufwerk, monatliche Übergabe an die Buchhaltung. Etwa zehn Buchungen pro Woche, je etwa zehn Minuten.
- [[PRO-002-stornierung-bahnreise|PRO-002]] Stornierung einer Bahnreise (Skizze): E-Mail der reisenden Person, Assistenz storniert; beim Flexpreis bis einen Tag vorher kostenlos. Sparpreis- und Kurzfristfall nicht erhoben.
- [[PRO-003-aenderung-reisezeit|PRO-003]] Änderung der Reisezeit (Skizze): Flexpreis-Ticket bleibt, nur die Sitzplatzreservierung wird neu gebucht. Auslöser und andere Änderungsarten nicht erhoben.

## Feste Regeln (als Anforderungen im Entwurf)

- Pflichtangaben der Reiseanfrage ([[ANF-001-pflichtangaben-reiseanfrage|ANF-001]])
- Zweite Klasse, erste Klasse ab mehr als vier Stunden ([[ANF-002-zweite-klasse-erste-ab-vier-stunden|ANF-002]])
- Immer Sitzplatzreservierung ([[ANF-003-sitzplatzreservierung-immer|ANF-003]])
- Ticket als PDF per E-Mail ([[ANF-004-ticket-als-pdf-per-e-mail|ANF-004]])
- Flexpreis als Standard, Sparpreis nur bei festem Termin und mehr als vierzehn Tagen Vorlauf ([[ANF-005-flexpreis-als-standardtarif|ANF-005]], [[ANF-006-sparpreis-nur-bei-festem-termin|ANF-006]])
- Freigabe der Teamleitung ab 250 Euro pro Buchung ([[ANF-007-freigabe-ab-250-euro|ANF-007]])
- BahnCard-Nummer bei der Buchung eintragen ([[ANF-008-bahncard-nummer-bei-buchung|ANF-008]])
- Rechnung aufs Teamlaufwerk, monatlich an die Buchhaltung ([[ANF-009-rechnung-auf-teamlaufwerk|ANF-009]], [[ANF-010-rechnungen-monatlich-an-buchhaltung|ANF-010]])
- Stornierung auf E-Mail, bei Uhrzeitänderung nur Sitzplatz neu ([[ANF-011-stornierung-auf-e-mail|ANF-011]], [[ANF-012-uhrzeitaenderung-nur-sitzplatz-neu|ANF-012]])
- Abgrenzungen: Verspätungserstattung macht die reisende Person, Auslandsreisen laufen über das Reisebüro ([[ANF-013-erstattung-bei-verspaetung-durch-reisende-person|ANF-013]], [[ANF-014-auslandsreisen-ueber-reisebuero|ANF-014]])
- Vertretung mit Zugang zum Geschäftskundenkonto ([[ANF-015-vertretung-zugang-geschaeftskundenkonto|ANF-015]])

Alle fünfzehn sind aus der Ist-Beschreibung abgeleitet und vom Fachbereich noch nicht als Anforderung bestätigt.

## Rollen

[[ROL-001-assistenz|Assistenz]] (führt den Prozess), [[ROL-002-reisende-person|Reisende Person]] (Anfrage, Ticket), [[ROL-003-teamleitung|Teamleitung]] (Freigabe ab 250 Euro), [[ROL-004-buchhaltung|Buchhaltung]] (Rechnungen monatlich), [[ROL-005-vertretung-sekretariat|Vertretung der Assistenz]] (Sekretariat, Zugang zum Geschäftskundenkonto), [[ROL-006-reisebuero|Reisebüro]] (Auslandsreisen, nur genannt).

## Systemlandschaft

- [[SYS-002-teampostfach|Teampostfach]] (E-Mail) → manuell → [[SYS-001-bahn-de|bahn.de]] ← manuell ← [[SYS-003-excel-liste-bahncards|Excel-Liste BahnCards]]; aus bahn.de PDF-Downloads → E-Mail (Ticket) und [[SYS-004-teamlaufwerk|Teamlaufwerk]] (Rechnung) → Buchhaltung. Keine Systemschnittstelle beschrieben, alle Übergänge sind manuelle Übertragungen (⚠️ erschlossen).

## Größte Lücken

- Schmerzpunkte sind kaum erhoben; einziger belegter Schmerzpunkt ist der unbemerkte Ablauf von BahnCards, weil die Pflege der Liste nicht geregelt ist ([[OP-008-pflege-bahncard-liste|OP-008]]).
- Die Regeln zu Klasse, Sitzplatz, Sparpreis und Freigabe sind in Bezugsgröße und Ausnahmen unklar ([[OP-002-regel-erste-klasse-praezisieren|OP-002]], [[OP-004-keine-sitzplatzreservierung-moeglich|OP-004]], [[OP-005-kriterium-fester-termin|OP-005]], [[OP-006-freigabegrenze-praezisieren|OP-006]]).
- Der Übergabeweg an die Buchhaltung und das Verhältnis von Ticket und Rechnung sind offen ([[OP-007-uebergabe-an-buchhaltung|OP-007]]).
- BahnCard-Status in der Anfrage und BahnCard-Liste der Assistenz sind möglicherweise redundant ([[OP-008-pflege-bahncard-liste|OP-008]]).
- Stornierung und Änderung sind nur für den Flexpreis-Normalfall beschrieben; Sparpreis, Kurzfrist, Datumsänderung, Erstattungsfluss und Korrektur der Ablage fehlen ([[OP-009-stornierung-sonderfaelle|OP-009]], [[OP-010-aenderung-ueber-uhrzeit-hinaus|OP-010]], [[OP-013-erstattung-verspaetung-empfaenger|OP-013]]).
- Die Vertretung ist nur über den Zugang zum Geschäftskundenkonto belegt; Umfang und übrige Systemzugänge sind offen ([[OP-011-vertretung-umfang-und-uebergabe|OP-011]]).
- Die Abgrenzung zu Auslandsreisen und zum Reisebüro ist unscharf ([[OP-012-abgrenzung-auslandsreisen|OP-012]]).
