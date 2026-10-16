---
id: SYS-003
typ: system
titel: BahnCard Excel list
status: genannt
quellen: [Q-002, Q-003]
aktualisiert: 2026-10-06
---

# SYS-003 · BahnCard Excel list

## Exact name

Referred to in the source as an "Excel list of all BahnCards on the team"; file name and storage location not captured. [Q-002 · 00:01:12]

## Purpose in the domain

Reference for the team members' BahnCard numbers, which are entered at booking. [Q-002 · 00:01:12]

## Who uses it

[[ROL-001-assistant|Assistant]], who keeps the list. [Q-002 · 00:01:12]

## Processes

- [[PRO-001-train-booking|PRO-001]] Train booking, step 7

## Interfaces and media breaks

- The number is transferred manually from the list into [[SYS-001-bahn-de|bahn.de]]. [Q-002 · 00:01:12]

## Known limitations

- Who maintains the list when a BahnCard expires is not defined. [Q-003 · 00:01:27]
- An expired card is usually only noticed when the discount no longer works at booking. [Q-003 · 00:01:27]

## Related requirements

- [[ANF-008-bahncard-number-at-booking|ANF-008]]

## Open items

- [[OP-008-maintaining-bahncard-list|OP-008]]

## Sources

- [[Q-002-bahn-02-booking-and-payment|Q-002]]
- [[Q-003-bahn-03-changes-and-special-cases|Q-003]]
