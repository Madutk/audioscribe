---
id: SYS-001
typ: system
titel: bahn.de (Geschäftskundenkonto)
status: beschrieben
quellen: [Q-001, Q-002, Q-003]
aktualisiert: 2026-10-06
---

# SYS-001 · bahn.de (Geschäftskundenkonto)

## Exakter Name

bahn.de, genutzt im Browser. [Q-001 · 00:00:56]

## Zweck in der Domäne

Buchung von Bahnreisen für Teammitglieder. [Q-001 · 00:00:56]

Bezahlung mit der Firmenkreditkarte, die im Geschäftskundenkonto hinterlegt ist. [Q-002 · 00:00:41]

Eintrag der BahnCard-Nummer, damit der Rabatt abgezogen wird. [Q-002 · 00:01:12]

## Wer es nutzt

- [[ROL-001-assistenz|Assistenz]], angemeldet mit einem Geschäftskundenkonto. [Q-001 · 00:00:56]
- [[ROL-005-vertretung-sekretariat|Vertretung der Assistenz]], hat ebenfalls Zugang zum Geschäftskundenkonto. [Q-003 · 00:01:12]

## Prozesse

- [[PRO-001-bahnbuchung|PRO-001]] Bahnbuchung, Schritte 4 bis 11 und 13
- [[PRO-002-stornierung-bahnreise|PRO-002]] Stornierung (⚠️ erschlossen: System der Stornierung nicht belegt)
- [[PRO-003-aenderung-reisezeit|PRO-003]] Änderung der Reisezeit (⚠️ erschlossen: System der Sitzplatz-Neubuchung nicht belegt)

## Schnittstellen und Medienbrüche

- Eingabe: Angaben aus der Reiseanfrage, die per E-Mail im Teampostfach eingeht. [Q-001 · 00:00:18] [Q-001 · 00:00:34]
- Eingabe: BahnCard-Nummer, manuell aus der [[SYS-003-excel-liste-bahncards|Excel-Liste]] übertragen. [Q-002 · 00:01:12]
- Ausgabe: Ticket als PDF-Download, anschließend Versand per E-Mail. [Q-001 · 00:01:42]
- Ausgabe: Rechnung als PDF-Download, anschließend Ablage auf dem [[SYS-004-teamlaufwerk|Teamlaufwerk]]. [Q-002 · 00:01:30]
- ⚠️ erschlossen: Zwischen Teampostfach, bahn.de und PDF-Versand gibt es keine beschriebene Systemverbindung; die Daten werden manuell übertragen. Begründung: Die Quelle beschreibt die Schritte als getrennte Handlungen der Assistenz.

## Bekannte Einschränkungen

- Ist eine BahnCard abgelaufen, geht der Rabatt bei der Buchung nicht mehr; das ist für die Assistenz meist der erste Hinweis auf den Ablauf. [Q-003 · 00:01:27]

## Zugehörige Anforderungen

- [[ANF-002-zweite-klasse-erste-ab-vier-stunden|ANF-002]], [[ANF-003-sitzplatzreservierung-immer|ANF-003]], [[ANF-004-ticket-als-pdf-per-e-mail|ANF-004]]
- [[ANF-005-flexpreis-als-standardtarif|ANF-005]], [[ANF-006-sparpreis-nur-bei-festem-termin|ANF-006]], [[ANF-008-bahncard-nummer-bei-buchung|ANF-008]], [[ANF-009-rechnung-auf-teamlaufwerk|ANF-009]]
- [[ANF-011-stornierung-auf-e-mail|ANF-011]], [[ANF-012-uhrzeitaenderung-nur-sitzplatz-neu|ANF-012]], [[ANF-015-vertretung-zugang-geschaeftskundenkonto|ANF-015]]

## Offene Punkte

- [[OP-011-vertretung-umfang-und-uebergabe|OP-011]]

## Quellen

- [[Q-001-bahn-01-prozessueberblick|Q-001]]
- [[Q-002-bahn-02-buchung-und-bezahlung|Q-002]]
- [[Q-003-bahn-03-aenderungen-und-sonderfaelle|Q-003]]
