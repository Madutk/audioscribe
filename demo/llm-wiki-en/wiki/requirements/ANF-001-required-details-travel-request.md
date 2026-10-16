---
id: ANF-001
typ: anforderung
titel: Required details of the travel request
status: entwurf
art: funktional
prioritaet: unbekannt
quellen: [Q-001]
aktualisiert: 2026-10-06
---

# ANF-001 · Required details of the travel request

## Requirement

A travel request must contain the travel date, origin and destination, the latest arrival time and the traveler's BahnCard status; if any detail is missing, it is requested from the traveler. [Q-001 · 00:00:34]

## Rationale

The Assistant can only book once the request is complete; today she asks for missing details by email. [Q-001 · 00:00:34]

## Origin

Derived from the description of the current state in the process recording; not confirmed as a requirement by the business side. [Q-001 · 00:00:34]

## Affected processes, systems, roles

- Process: [[PRO-001-train-booking|PRO-001]], steps 1 to 3
- Systems: [[SYS-002-team-mailbox|SYS-002]]
- Roles: [[ROL-001-assistant|ROL-001]], [[ROL-002-traveler|ROL-002]]

## Acceptance criterion

not captured

## Open items

- [[OP-005-criterion-fixed-date|OP-005]]: the required details do not say whether the date is fixed
- [[OP-008-maintaining-bahncard-list|OP-008]]: relationship between the BahnCard detail and the Excel list

## Related

- [[ANF-008-bahncard-number-at-booking|ANF-008]]: use of the BahnCard at booking

## Sources

- [[Q-001-bahn-01-process-overview|Q-001]]
