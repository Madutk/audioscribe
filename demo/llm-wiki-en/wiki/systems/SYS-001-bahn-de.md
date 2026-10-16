---
id: SYS-001
typ: system
titel: bahn.de (business customer account)
status: beschrieben
quellen: [Q-001, Q-002, Q-003]
aktualisiert: 2026-10-06
---

# SYS-001 · bahn.de (business customer account)

## Exact name

bahn.de, used in the browser. [Q-001 · 00:00:56]

## Purpose in the domain

Booking train trips for team members. [Q-001 · 00:00:56]

Payment with the corporate credit card stored in the business customer account. [Q-002 · 00:00:41]

Entering the BahnCard number so that the discount is applied. [Q-002 · 00:01:12]

## Who uses it

- [[ROL-001-assistant|Assistant]], logged in with a business customer account. [Q-001 · 00:00:56]
- [[ROL-005-deputy-admin-office|Deputy of the Assistant]], also has access to the business customer account. [Q-003 · 00:01:12]

## Processes

- [[PRO-001-train-booking|PRO-001]] Train booking, steps 4 to 11 and 13
- [[PRO-002-cancel-train-trip|PRO-002]] Cancellation (⚠️ inferred: system used for cancellation not documented)
- [[PRO-003-change-travel-time|PRO-003]] Change of travel time (⚠️ inferred: system used for rebooking the seat not documented)

## Interfaces and media breaks

- Input: details from the travel request that arrives by email in the team mailbox. [Q-001 · 00:00:18] [Q-001 · 00:00:34]
- Input: BahnCard number, transferred manually from the [[SYS-003-bahncard-excel-list|Excel list]]. [Q-002 · 00:01:12]
- Output: ticket as a PDF download, then sent by email. [Q-001 · 00:01:42]
- Output: invoice as a PDF download, then filed on the [[SYS-004-team-drive|team drive]]. [Q-002 · 00:01:30]
- ⚠️ inferred: There is no described system connection between the team mailbox, bahn.de and sending the PDF; data is transferred manually. Reason: the source describes the steps as separate actions by the Assistant.

## Known limitations

- If a BahnCard has expired, the discount no longer works at booking; for the Assistant this is usually the first sign that it has expired. [Q-003 · 00:01:27]

## Related requirements

- [[ANF-002-second-class-first-over-four-hours|ANF-002]], [[ANF-003-always-seat-reservation|ANF-003]], [[ANF-004-ticket-as-pdf-by-email|ANF-004]]
- [[ANF-005-flex-fare-as-default|ANF-005]], [[ANF-006-saver-fare-only-fixed-date|ANF-006]], [[ANF-008-bahncard-number-at-booking|ANF-008]], [[ANF-009-invoice-on-team-drive|ANF-009]]
- [[ANF-011-cancellation-on-email|ANF-011]], [[ANF-012-time-change-rebook-seat-only|ANF-012]], [[ANF-015-deputy-access-business-account|ANF-015]]

## Open items

- [[OP-011-deputy-scope-and-handover|OP-011]]

## Sources

- [[Q-001-bahn-01-process-overview|Q-001]]
- [[Q-002-bahn-02-booking-and-payment|Q-002]]
- [[Q-003-bahn-03-changes-and-special-cases|Q-003]]
