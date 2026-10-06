---
id: PRO-003
typ: prozess
titel: Änderung der Reisezeit
status: skizze
quellen: [Q-003]
aktualisiert: 2026-10-06
---

# PRO-003 · Änderung der Reisezeit

## Zweck

Ändert sich nur die Uhrzeit einer gebuchten Reise, wird die Sitzplatzreservierung neu gebucht; das Flexpreis-Ticket bleibt unverändert. [Q-003 · 00:00:28]

## Auslöser

nicht erhoben. ⚠️ erschlossen: vermutlich eine Mitteilung der reisenden Person, analog zur Stornierung [Q-003 · 00:00:10]; die Quelle sagt dazu nichts.

## Turnus

nicht erhoben

## Rollen

- [[ROL-001-assistenz|Assistenz]]: bucht die Sitzplatzreservierung neu. [Q-003 · 00:00:28]
- [[ROL-002-reisende-person|Reisende Person]]: ⚠️ erschlossen als Auslöser der Änderung; nicht belegt.

## Systeme

- ⚠️ erschlossen: Die Neubuchung der Sitzplatzreservierung erfolgt auf [[SYS-001-bahn-de|bahn.de]], weil dort gebucht wird; die Quelle nennt das System nicht. [Q-001 · 00:00:56]

## Ablauf

1. Die Uhrzeit der Reise ändert sich. [Q-003 · 00:00:28]
2. Beim Flexpreis muss am Ticket nichts geändert werden, weil es für jeden Zug an dem Tag gilt. [Q-003 · 00:00:28]
3. Die Assistenz bucht nur die Sitzplatzreservierung neu. [Q-003 · 00:00:28]

## Entscheidungen im Ablauf

- Ändert sich nur die Uhrzeit (gleicher Tag)? Wenn ja: Ticket bleibt, Sitzplatz neu. Sonst: nicht erhoben. [Q-003 · 00:00:28]

## Varianten und Sonderfälle

- Änderung des Reisedatums oder der Strecke: nicht erhoben.
- Uhrzeitänderung beim Sparpreis: nicht erhoben.
- Kosten der neuen Sitzplatzreservierung und Umgang mit der alten Reservierung: nicht erhoben.

## Schmerzpunkte

nicht erhoben

## Abgeleitete Anforderungen

- [[ANF-012-uhrzeitaenderung-nur-sitzplatz-neu|ANF-012]] Bei Uhrzeitänderung nur die Sitzplatzreservierung neu buchen
- [[ANF-003-sitzplatzreservierung-immer|ANF-003]] Jede Buchung mit Sitzplatzreservierung

## Offene Punkte

- [[OP-010-aenderung-ueber-uhrzeit-hinaus|OP-010]] Änderung über die Uhrzeit hinaus, Sparpreis und Auslöser

## Zusammenhang

- Vorgelagert: [[PRO-001-bahnbuchung|PRO-001]] Bahnbuchung
- Verwandt: [[PRO-002-stornierung-bahnreise|PRO-002]] Stornierung einer Bahnreise

## Quellen

- [[Q-003-bahn-03-aenderungen-und-sonderfaelle|Q-003]]
