---
id: ANF-006
typ: anforderung
titel: Saver fare only for a fixed date and more than fourteen days in advance
status: entwurf
art: randbedingung
prioritaet: unbekannt
quellen: [Q-002]
aktualisiert: 2026-10-06
---

# ANF-006 · Saver fare only for a fixed date and more than fourteen days in advance

## Requirement

The Saver fare is only booked when the date is fixed and the trip is more than fourteen days in the future. [Q-002 · 00:00:24]

## Rationale

⚠️ inferred: the converse of the rationale for the Flex fare (appointments often get moved); the source does not give a separate rationale for the exception. [Q-002 · 00:00:12]

## Origin

Derived from the description of the current state in the process recording; not confirmed as a requirement by the business side. [Q-002 · 00:00:24]

## Affected processes, systems, roles

- Process: [[PRO-001-train-booking|PRO-001]], step 6
- Systems: [[SYS-001-bahn-de|SYS-001]]
- Roles: [[ROL-001-assistant|ROL-001]]

## Acceptance criterion

not captured

## Open items

- [[OP-005-criterion-fixed-date|OP-005]]: Who decides that a date is "fixed"?
- [[OP-009-cancellation-special-cases|OP-009]]: cancellation and changes for the Saver fare not captured

## Related

- Standard case: [[ANF-005-flex-fare-as-default|ANF-005]]

## Sources

- [[Q-002-bahn-02-booking-and-payment|Q-002]]
