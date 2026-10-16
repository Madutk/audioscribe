# Overview of the Assistant domain

> AI-generated situation overview based on the state of the wiki as of 2026-10-06.

## Status

Three sources have been incorporated: the train booking process overview from 2026-09-08 ([[Q-001-bahn-01-process-overview|Q-001]]), the deep dive on fare, payment and filing from 2026-09-15 ([[Q-002-bahn-02-booking-and-payment|Q-002]]) and the recording on changes, cancellations and special cases from 2026-09-22 ([[Q-003-bahn-03-changes-and-special-cases|Q-003]]). The wiki knows three processes, fifteen draft requirements, four systems, six roles and thirteen open items, one of them resolved. There are no contradictions or decisions.

## Processes

- [[PRO-001-train-booking|PRO-001]] Train booking for team members, 14 steps: travel request by email to the team mailbox, completeness check, booking on bahn.de with the business customer account (class, fare, BahnCard, seat, approval if needed), payment with the corporate credit card, ticket by email, invoice to the team drive, monthly handover to Accounting. About ten bookings a week, about ten minutes each.
- [[PRO-002-cancel-train-trip|PRO-002]] Cancelling a train trip (sketch): email from the traveler, the Assistant cancels; free of charge with the Flex fare until one day before. Saver fare and short-notice cases not captured.
- [[PRO-003-change-travel-time|PRO-003]] Changing the travel time (sketch): the Flex fare ticket stays, only the seat reservation is rebooked. Trigger and other kinds of change not captured.

## Fixed rules (as draft requirements)

- Required details of the travel request ([[ANF-001-required-details-travel-request|ANF-001]])
- Second class, first class only for trips over four hours ([[ANF-002-second-class-first-over-four-hours|ANF-002]])
- Always a seat reservation ([[ANF-003-always-seat-reservation|ANF-003]])
- Ticket as PDF by email ([[ANF-004-ticket-as-pdf-by-email|ANF-004]])
- Flex fare as the default, Saver fare only with a fixed date and more than fourteen days ahead ([[ANF-005-flex-fare-as-default|ANF-005]], [[ANF-006-saver-fare-only-fixed-date|ANF-006]])
- Approval by the team lead from 250 euros per booking ([[ANF-007-approval-from-250-euros|ANF-007]])
- Enter the BahnCard number when booking ([[ANF-008-bahncard-number-at-booking|ANF-008]])
- Invoice to the team drive, monthly to Accounting ([[ANF-009-invoice-on-team-drive|ANF-009]], [[ANF-010-invoices-monthly-to-accounting|ANF-010]])
- Cancellation upon email, on a time change only the seat is rebooked ([[ANF-011-cancellation-on-email|ANF-011]], [[ANF-012-time-change-rebook-seat-only|ANF-012]])
- Scope boundaries: travelers handle delay refunds, international trips go through the travel agency ([[ANF-013-delay-refund-by-traveler|ANF-013]], [[ANF-014-international-trips-via-travel-agency|ANF-014]])
- Deputy with access to the business customer account ([[ANF-015-deputy-access-business-account|ANF-015]])

All fifteen are derived from the description of the current state and have not yet been confirmed as requirements by the business side.

## Roles

[[ROL-001-assistant|Assistant]] (runs the process), [[ROL-002-traveler|Traveler]] (request, ticket), [[ROL-003-team-lead|Team lead]] (approval from 250 euros), [[ROL-004-accounting|Accounting]] (invoices monthly), [[ROL-005-deputy-admin-office|Deputy for the Assistant]] (admin office, access to the business customer account), [[ROL-006-travel-agency|Travel agency]] (international trips, only named).

## System landscape

- [[SYS-002-team-mailbox|Team mailbox]] (email) → manual → [[SYS-001-bahn-de|bahn.de]] ← manual ← [[SYS-003-bahncard-excel-list|BahnCard Excel list]]; PDF downloads from bahn.de → email (ticket) and [[SYS-004-team-drive|team drive]] (invoice) → Accounting. No system interface is described; all transitions are manual transfers (⚠️ inferred).

## Biggest gaps

- Pain points have barely been captured; the only documented pain point is BahnCards expiring unnoticed, because maintaining the list is not defined ([[OP-008-maintaining-bahncard-list|OP-008]]).
- The rules on class, seat, Saver fare and approval are unclear in their basis and exceptions ([[OP-002-clarify-first-class-rule|OP-002]], [[OP-004-no-seat-reservation-available|OP-004]], [[OP-005-criterion-fixed-date|OP-005]], [[OP-006-clarify-approval-threshold|OP-006]]).
- The handover channel to Accounting and the relationship between ticket and invoice are open ([[OP-007-handover-to-accounting|OP-007]]).
- The BahnCard status in the request and the Assistant's BahnCard list may be redundant ([[OP-008-maintaining-bahncard-list|OP-008]]).
- Cancellation and changes are only described for the normal Flex fare case; Saver fare, short notice, date changes, refund flow and correcting the filing are missing ([[OP-009-cancellation-special-cases|OP-009]], [[OP-010-changes-beyond-time|OP-010]], [[OP-013-delay-refund-recipient|OP-013]]).
- The deputy is only documented through access to the business customer account; scope and other system access are open ([[OP-011-deputy-scope-and-handover|OP-011]]).
- The boundary to international trips and the travel agency is fuzzy ([[OP-012-scope-international-trips|OP-012]]).
