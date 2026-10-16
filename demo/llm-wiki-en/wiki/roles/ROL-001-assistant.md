---
id: ROL-001
typ: rolle
titel: Assistant
status: aufgenommen
quellen: [Q-001, Q-002, Q-003]
aktualisiert: 2026-10-06
---

# ROL-001 · Assistant

## Tasks in the domain

- Books the train trips for the team. [Q-001] [Q-002]
- Receives travel requests from the team mailbox and checks them for completeness. [Q-001 · 00:00:18] [Q-001 · 00:00:34]
- Asks for missing details by email. [Q-001 · 00:00:34]
- Books on bahn.de with the business customer account. [Q-001 · 00:00:56]
- Chooses the fare (Flex fare as the default, Saver fare as the exception). [Q-002 · 00:00:12] [Q-002 · 00:00:24]
- From 250 euros per booking, obtains the team lead's approval by email in advance. [Q-002 · 00:00:53]
- Keeps an Excel list of all BahnCards in the team and enters the number when booking. [Q-002 · 00:01:12]
- Pays with the corporate credit card stored in the business customer account. [Q-002 · 00:00:41]
- Downloads the ticket as a PDF and sends it to the traveler. [Q-001 · 00:01:42]
- Downloads the invoice as a PDF and files it on the team drive. [Q-002 · 00:01:30]
- Hands the invoices over to Accounting in a batch once a month. [Q-002 · 00:01:48]
- Cancels a booking when the traveler reports by email that the trip is called off. [Q-003 · 00:00:10]
- Rebooks the seat reservation when the departure time changes. [Q-003 · 00:00:28]

## Processes involved

- [[PRO-001-train-booking|PRO-001]] Train booking
- [[PRO-002-cancel-train-trip|PRO-002]] Cancelling a train trip
- [[PRO-003-change-travel-time|PRO-003]] Changing the travel time

## Systems used

- [[SYS-001-bahn-de|SYS-001]] bahn.de
- [[SYS-002-team-mailbox|SYS-002]] Team mailbox
- [[SYS-003-bahncard-excel-list|SYS-003]] BahnCard Excel list
- [[SYS-004-team-drive|SYS-004]] Team drive

## Authority and limits

- Decides the class by a fixed rule (second class, first class only for trips longer than four hours). [Q-001 · 00:01:14]
- Books only with a seat reservation. [Q-001 · 00:01:30]
- Books anything under 250 euros directly; from 250 euros only with the team lead's approval. [Q-002 · 00:00:53]
- Decides between Flex fare and Saver fare by a fixed rule. [Q-002 · 00:00:12] [Q-002 · 00:00:24]
- Is not responsible for delay refunds; the traveler handles those personally. [Q-003 · 00:00:47]
- Does not book international trips; these go through the travel agency. [Q-003 · 00:01:00]

## Deputy

- Is covered by a person from the admin office who also has access to the business customer account; see [[ROL-005-deputy-admin-office|ROL-005]]. [Q-003 · 00:01:12]

## Related requirements

- [[ANF-001-required-details-travel-request|ANF-001]], [[ANF-002-second-class-first-over-four-hours|ANF-002]], [[ANF-003-always-seat-reservation|ANF-003]], [[ANF-004-ticket-as-pdf-by-email|ANF-004]]
- [[ANF-005-flex-fare-as-default|ANF-005]], [[ANF-006-saver-fare-only-fixed-date|ANF-006]], [[ANF-007-approval-from-250-euros|ANF-007]], [[ANF-008-bahncard-number-at-booking|ANF-008]], [[ANF-009-invoice-on-team-drive|ANF-009]], [[ANF-010-invoices-monthly-to-accounting|ANF-010]]
- [[ANF-011-cancellation-on-email|ANF-011]], [[ANF-012-time-change-rebook-seat-only|ANF-012]], [[ANF-013-delay-refund-by-traveler|ANF-013]], [[ANF-014-international-trips-via-travel-agency|ANF-014]], [[ANF-015-deputy-access-business-account|ANF-015]]

## Open items

- [[OP-009-cancellation-special-cases|OP-009]], [[OP-010-changes-beyond-time|OP-010]], [[OP-011-deputy-scope-and-handover|OP-011]], [[OP-012-scope-international-trips|OP-012]]

## Sources

- [[Q-001-bahn-01-process-overview|Q-001]]
- [[Q-002-bahn-02-booking-and-payment|Q-002]]
- [[Q-003-bahn-03-changes-and-special-cases|Q-003]]
