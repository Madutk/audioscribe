---
id: ANF-003
typ: anforderung
titel: Jede Buchung mit Sitzplatzreservierung
status: entwurf
art: randbedingung
prioritaet: unbekannt
quellen: [Q-001, Q-003]
aktualisiert: 2026-10-06
---

# ANF-003 · Jede Buchung mit Sitzplatzreservierung

## Anforderung

Jede Bahnbuchung enthält eine Sitzplatzreservierung; ohne Sitzplatzreservierung wird nicht gebucht. [Q-001 · 00:01:30]

## Begründung

nicht erhoben [Q-001 · 00:01:30]

## Herkunft

Abgeleitet aus der Beschreibung des Ist-Zustands in der Prozessaufnahme; nicht vom Fachbereich als Anforderung bestätigt. [Q-001 · 00:01:30]

## Betroffene Prozesse, Systeme, Rollen

- Prozess: [[PRO-001-bahnbuchung|PRO-001]], Schritt 8; [[PRO-003-aenderung-reisezeit|PRO-003]], Schritt 3
- Systeme: [[SYS-001-bahn-de|SYS-001]]
- Rollen: [[ROL-001-assistenz|ROL-001]]

## Abnahmekriterium

nicht erhoben

## Offene Punkte

- [[OP-004-keine-sitzplatzreservierung-moeglich|OP-004]]: Vorgehen, wenn keine Sitzplatzreservierung verfügbar ist

## Zusammenhang

- Bei einer Uhrzeitänderung wird die Sitzplatzreservierung neu gebucht, das Flexpreis-Ticket bleibt; siehe [[ANF-012-uhrzeitaenderung-nur-sitzplatz-neu|ANF-012]]. [Q-003 · 00:00:28]

## Quellen

- [[Q-001-bahn-01-prozessueberblick|Q-001]]
- [[Q-003-bahn-03-aenderungen-und-sonderfaelle|Q-003]]
