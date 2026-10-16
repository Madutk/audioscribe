---
id: ANF-003
typ: anforderung
titel: Every booking with a seat reservation
status: entwurf
art: randbedingung
prioritaet: unbekannt
quellen: [Q-001, Q-003]
aktualisiert: 2026-10-06
---

# ANF-003 · Every booking with a seat reservation

## Requirement

Every train booking includes a seat reservation; nothing is booked without a seat reservation. [Q-001 · 00:01:30]

## Rationale

not captured [Q-001 · 00:01:30]

## Origin

Derived from the description of the current state in the process recording; not confirmed as a requirement by the business side. [Q-001 · 00:01:30]

## Affected processes, systems, roles

- Process: [[PRO-001-train-booking|PRO-001]], step 8; [[PRO-003-change-travel-time|PRO-003]], step 3
- Systems: [[SYS-001-bahn-de|SYS-001]]
- Roles: [[ROL-001-assistant|ROL-001]]

## Acceptance criterion

not captured

## Open items

- [[OP-004-no-seat-reservation-available|OP-004]]: what to do when no seat reservation is available

## Related

- When the departure time changes, the seat reservation is rebooked and the Flex fare ticket stays; see [[ANF-012-time-change-rebook-seat-only|ANF-012]]. [Q-003 · 00:00:28]

## Sources

- [[Q-001-bahn-01-process-overview|Q-001]]
- [[Q-003-bahn-03-changes-and-special-cases|Q-003]]
