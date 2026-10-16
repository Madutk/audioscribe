---
id: ANF-008
typ: anforderung
titel: Enter the BahnCard number when booking
status: entwurf
art: funktional
prioritaet: unbekannt
quellen: [Q-002, Q-003]
aktualisiert: 2026-10-06
---

# ANF-008 · Enter the BahnCard number when booking

## Requirement

When booking, the traveler's BahnCard number is entered so that the discount is applied. [Q-002 · 00:01:12]

## Rationale

The BahnCard discount is only applied if the number is entered at booking. [Q-002 · 00:01:12]

## Origin

Derived from the description of the current state in the process recording; not confirmed as a requirement by the business side. [Q-002 · 00:01:12]

## Affected processes, systems, roles

- Process: [[PRO-001-train-booking|PRO-001]], step 7
- Systems: [[SYS-001-bahn-de|SYS-001]], [[SYS-003-bahncard-excel-list|SYS-003]] (source of the number)
- Roles: [[ROL-001-assistant|ROL-001]], [[ROL-002-traveler|ROL-002]]

## Acceptance criterion

not captured

## Open items

- [[OP-008-maintaining-bahncard-list|OP-008]]: maintenance of the list and its relationship to the required detail in the travel request; according to Q-003, maintenance when a card expires is not defined

## Related

- [[ANF-001-required-details-travel-request|ANF-001]]: BahnCard status is a required detail of the travel request
- If the BahnCard has expired, the discount no longer works at booking; the Assistant usually only notices the expiry then. [Q-003 · 00:01:27]

## Sources

- [[Q-002-bahn-02-booking-and-payment|Q-002]]
- [[Q-003-bahn-03-changes-and-special-cases|Q-003]]
