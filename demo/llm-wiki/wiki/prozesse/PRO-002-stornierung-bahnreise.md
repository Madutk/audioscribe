---
id: PRO-002
typ: prozess
titel: Stornierung einer Bahnreise
status: skizze
quellen: [Q-003]
aktualisiert: 2026-10-06
---

# PRO-002 · Stornierung einer Bahnreise

## Zweck

Eine gebuchte Bahnreise, die ausfällt, wird von der Assistenz storniert. [Q-003 · 00:00:10]

## Auslöser

Eine E-Mail der reisenden Person an die Assistenz, dass die Reise ausfällt. [Q-003 · 00:00:10]

## Turnus

nicht erhoben

## Rollen

- [[ROL-002-reisende-person|Reisende Person]]: meldet den Ausfall per E-Mail. [Q-003 · 00:00:10]
- [[ROL-001-assistenz|Assistenz]]: storniert. [Q-003 · 00:00:10]

## Systeme

- E-Mail für die Meldung; ob über das [[SYS-002-teampostfach|Teampostfach]]: nicht erhoben. [Q-003 · 00:00:10]
- ⚠️ erschlossen: Die Stornierung erfolgt auf [[SYS-001-bahn-de|bahn.de]] im Geschäftskundenkonto, weil dort gebucht wird; die Quelle nennt das System der Stornierung nicht. [Q-001 · 00:00:56]

## Ablauf

1. Die reisende Person schreibt der Assistenz eine E-Mail, dass die Reise ausfällt. [Q-003 · 00:00:10]
2. Die Assistenz storniert die Buchung. [Q-003 · 00:00:10]
3. Beim Flexpreis ist die Stornierung bis einen Tag vor der Reise kostenlos. [Q-003 · 00:00:10]

## Entscheidungen im Ablauf

- Flexpreis und mindestens ein Tag vor der Reise? Wenn ja: kostenlose Stornierung. Sonst: nicht erhoben. [Q-003 · 00:00:10]

## Varianten und Sonderfälle

- Stornierung beim Sparpreis: nicht erhoben.
- Stornierung weniger als einen Tag vor der Reise: nicht erhoben.
- Umgang mit der bereits abgelegten Rechnung und der Erstattung: nicht erhoben.

## Schmerzpunkte

nicht erhoben

## Abgeleitete Anforderungen

- [[ANF-011-stornierung-auf-e-mail|ANF-011]] Stornierung auf E-Mail der reisenden Person

## Offene Punkte

- [[OP-009-stornierung-sonderfaelle|OP-009]] Stornierung: Sparpreis, Kurzfrist, Erstattung und Ablage

## Zusammenhang

- Vorgelagert: [[PRO-001-bahnbuchung|PRO-001]] Bahnbuchung
- Verwandt: [[PRO-003-aenderung-reisezeit|PRO-003]] Änderung der Reisezeit

## Quellen

- [[Q-003-bahn-03-aenderungen-und-sonderfaelle|Q-003]]
