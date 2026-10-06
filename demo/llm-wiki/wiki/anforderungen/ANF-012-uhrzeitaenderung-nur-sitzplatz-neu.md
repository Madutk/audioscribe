---
id: ANF-012
typ: anforderung
titel: Bei Uhrzeitänderung nur die Sitzplatzreservierung neu buchen
status: entwurf
art: funktional
prioritaet: unbekannt
quellen: [Q-003]
aktualisiert: 2026-10-06
---

# ANF-012 · Bei Uhrzeitänderung nur die Sitzplatzreservierung neu buchen

## Anforderung

Ändert sich bei einer Flexpreis-Buchung nur die Uhrzeit, bleibt das Ticket unverändert, und es wird nur die Sitzplatzreservierung neu gebucht. [Q-003 · 00:00:28]

## Begründung

Das Flexpreis-Ticket gilt für jeden Zug an dem Tag. [Q-003 · 00:00:28]

## Herkunft

Abgeleitet aus der Beschreibung des Ist-Zustands in der Prozessaufnahme; nicht vom Fachbereich als Anforderung bestätigt. [Q-003 · 00:00:28]

## Betroffene Prozesse, Systeme, Rollen

- Prozess: [[PRO-003-aenderung-reisezeit|PRO-003]], Schritte 2 und 3
- Systeme: [[SYS-001-bahn-de|SYS-001]] (⚠️ erschlossen als System der Neubuchung)
- Rollen: [[ROL-001-assistenz|ROL-001]]

## Abnahmekriterium

nicht erhoben

## Offene Punkte

- [[OP-010-aenderung-ueber-uhrzeit-hinaus|OP-010]]: Datums- oder Streckenänderung, Sparpreis, Auslöser, Kosten

## Zusammenhang

- [[ANF-003-sitzplatzreservierung-immer|ANF-003]]: die Pflicht zur Sitzplatzreservierung gilt auch nach einer Änderung
- [[ANF-005-flexpreis-als-standardtarif|ANF-005]]: Voraussetzung ist der Flexpreis

## Quellen

- [[Q-003-bahn-03-aenderungen-und-sonderfaelle|Q-003]]
