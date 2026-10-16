---
id: ANF-011
typ: anforderung
titel: Cancellation upon email from the traveler
status: entwurf
art: funktional
prioritaet: unbekannt
quellen: [Q-003]
aktualisiert: 2026-10-06
---

# ANF-011 · Cancellation upon email from the traveler

## Requirement

If a trip is called off, the traveler reports it by email and the Assistant cancels the booking. [Q-003 · 00:00:10]

## Rationale

not captured. Context: with the Flex fare, cancellation is free up to one day before the trip. [Q-003 · 00:00:10]

## Origin

Derived from the description of the current state in the process recording; not confirmed as a requirement by the business side. [Q-003 · 00:00:10]

## Affected processes, systems, roles

- Process: [[PRO-002-cancel-train-trip|PRO-002]], steps 1 and 2
- Systems: email (whether [[SYS-002-team-mailbox|SYS-002]]: not captured); [[SYS-001-bahn-de|SYS-001]] (⚠️ inferred as the system used for cancelling)
- Roles: [[ROL-001-assistant|ROL-001]], [[ROL-002-traveler|ROL-002]]

## Acceptance criterion

not captured

## Open items

- [[OP-009-cancellation-special-cases|OP-009]]: Saver fare, short-notice cancellation, refund and filing

## Related

- [[ANF-005-flex-fare-as-default|ANF-005]]: the Flex fare allows free cancellation up to one day before

## Sources

- [[Q-003-bahn-03-changes-and-special-cases|Q-003]]
