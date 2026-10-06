---
id: ANF-008
typ: anforderung
titel: BahnCard-Nummer bei der Buchung eintragen
status: entwurf
art: funktional
prioritaet: unbekannt
quellen: [Q-002, Q-003]
aktualisiert: 2026-10-06
---

# ANF-008 · BahnCard-Nummer bei der Buchung eintragen

## Anforderung

Bei der Buchung wird die BahnCard-Nummer der reisenden Person eingetragen, damit der Rabatt abgezogen wird. [Q-002 · 00:01:12]

## Begründung

Der BahnCard-Rabatt wird nur abgezogen, wenn die Nummer bei der Buchung hinterlegt ist. [Q-002 · 00:01:12]

## Herkunft

Abgeleitet aus der Beschreibung des Ist-Zustands in der Prozessaufnahme; nicht vom Fachbereich als Anforderung bestätigt. [Q-002 · 00:01:12]

## Betroffene Prozesse, Systeme, Rollen

- Prozess: [[PRO-001-bahnbuchung|PRO-001]], Schritt 7
- Systeme: [[SYS-001-bahn-de|SYS-001]], [[SYS-003-excel-liste-bahncards|SYS-003]] (Quelle der Nummer)
- Rollen: [[ROL-001-assistenz|ROL-001]], [[ROL-002-reisende-person|ROL-002]]

## Abnahmekriterium

nicht erhoben

## Offene Punkte

- [[OP-008-pflege-bahncard-liste|OP-008]]: Pflege der Liste und Verhältnis zur Pflichtangabe in der Reiseanfrage; laut Q-003 ist die Pflege bei Ablauf nicht geregelt

## Zusammenhang

- [[ANF-001-pflichtangaben-reiseanfrage|ANF-001]]: BahnCard-Status ist Pflichtangabe der Reiseanfrage
- Ist die BahnCard abgelaufen, geht der Rabatt bei der Buchung nicht mehr; die Assistenz merkt den Ablauf meist erst dann. [Q-003 · 00:01:27]

## Quellen

- [[Q-002-bahn-02-buchung-und-bezahlung|Q-002]]
- [[Q-003-bahn-03-aenderungen-und-sonderfaelle|Q-003]]
