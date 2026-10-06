---
id: ANF-001
typ: anforderung
titel: Pflichtangaben der Reiseanfrage
status: entwurf
art: funktional
prioritaet: unbekannt
quellen: [Q-001]
aktualisiert: 2026-10-06
---

# ANF-001 · Pflichtangaben der Reiseanfrage

## Anforderung

Eine Reiseanfrage muss Reisedatum, Start und Ziel, die späteste Ankunftszeit und den BahnCard-Status der reisenden Person enthalten; fehlt eine Angabe, wird sie bei der reisenden Person nachgefragt. [Q-001 · 00:00:34]

## Begründung

Erst mit vollständiger Anfrage kann die Assistenz buchen; heute fragt sie fehlende Angaben per E-Mail nach. [Q-001 · 00:00:34]

## Herkunft

Abgeleitet aus der Beschreibung des Ist-Zustands in der Prozessaufnahme; nicht vom Fachbereich als Anforderung bestätigt. [Q-001 · 00:00:34]

## Betroffene Prozesse, Systeme, Rollen

- Prozess: [[PRO-001-bahnbuchung|PRO-001]], Schritte 1 bis 3
- Systeme: [[SYS-002-teampostfach|SYS-002]]
- Rollen: [[ROL-001-assistenz|ROL-001]], [[ROL-002-reisende-person|ROL-002]]

## Abnahmekriterium

nicht erhoben

## Offene Punkte

- [[OP-005-kriterium-fester-termin|OP-005]]: Angabe zur Festigkeit des Termins fehlt in den Pflichtangaben
- [[OP-008-pflege-bahncard-liste|OP-008]]: Verhältnis der BahnCard-Angabe zur Excel-Liste

## Zusammenhang

- [[ANF-008-bahncard-nummer-bei-buchung|ANF-008]]: Verwendung der BahnCard bei der Buchung

## Quellen

- [[Q-001-bahn-01-prozessueberblick|Q-001]]
