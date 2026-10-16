---
id: ANF-012
typ: anforderung
titel: On a change of departure time, rebook only the seat reservation
status: entwurf
art: funktional
prioritaet: unbekannt
quellen: [Q-003]
aktualisiert: 2026-10-06
---

# ANF-012 · On a change of departure time, rebook only the seat reservation

## Requirement

If only the departure time of a Flex fare booking changes, the ticket stays as it is and only the seat reservation is rebooked. [Q-003 · 00:00:28]

## Rationale

The Flex fare ticket is valid on any train that day. [Q-003 · 00:00:28]

## Origin

Derived from the description of the current state in the process recording; not confirmed as a requirement by the business side. [Q-003 · 00:00:28]

## Affected processes, systems, roles

- Process: [[PRO-003-change-travel-time|PRO-003]], steps 2 and 3
- Systems: [[SYS-001-bahn-de|SYS-001]] (⚠️ inferred as the system used for rebooking)
- Roles: [[ROL-001-assistant|ROL-001]]

## Acceptance criterion

not captured

## Open items

- [[OP-010-changes-beyond-time|OP-010]]: change of date or route, Saver fare, trigger, costs

## Related

- [[ANF-003-always-seat-reservation|ANF-003]]: the seat reservation requirement also applies after a change
- [[ANF-005-flex-fare-as-default|ANF-005]]: the precondition is the Flex fare

## Sources

- [[Q-003-bahn-03-changes-and-special-cases|Q-003]]
