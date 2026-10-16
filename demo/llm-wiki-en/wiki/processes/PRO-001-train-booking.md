---
id: PRO-001
typ: prozess
titel: Train booking for team members
status: aufgenommen
quellen: [Q-001, Q-002, Q-003]
aktualisiert: 2026-10-06
---

# PRO-001 · Train booking for team members

## Purpose

The Assistant books train trips for colleagues on the team based on a travel request and delivers the ticket to the traveler. [Q-001 · 00:00:18] [Q-001 · 00:01:42]

## Trigger

A travel request by email to the team mailbox. [Q-001 · 00:00:18]

## Frequency

- Roughly ten bookings per week. [Q-001 · 00:01:58]
- Considerably more before trade fairs. [Q-001 · 00:01:58] (to be specified: [[OP-003-volume-before-trade-fairs|OP-003]])
- Handover of invoices to Accounting: once a month, at the end of the month. [Q-002 · 00:01:48]

## Roles

- [[ROL-001-assistant|Assistant]]: receives the request, checks it, books, pays, sends the ticket, files the invoice. [Q-001 · 00:00:34] [Q-001 · 00:01:42] [Q-002 · 00:01:30]
- [[ROL-002-traveler|Traveler]]: submits the request, receives the ticket. [Q-001 · 00:00:18] [Q-001 · 00:01:42]
- [[ROL-003-team-lead|Team lead]]: approves bookings of 250 euros or more in advance by email. [Q-002 · 00:00:53]
- [[ROL-004-accounting|Accounting]]: receives the invoices collected once a month. [Q-002 · 00:01:48]
- [[ROL-005-deputy-admin-office|Deputy of the Assistant]]: stands in for the Assistant and has access to the business customer account; which steps the deputy takes over is not captured. [Q-003 · 00:01:12]

## Systems

- [[SYS-002-team-mailbox|Team mailbox (email)]]: receipt of the request, follow-up questions, sending the ticket. [Q-001 · 00:00:18] [Q-001 · 00:00:34] [Q-001 · 00:01:42]
- [[SYS-001-bahn-de|bahn.de]] in the browser with the business customer account: booking and payment with the stored corporate credit card. [Q-001 · 00:00:56] [Q-002 · 00:00:41]
- [[SYS-003-bahncard-excel-list|BahnCard Excel list]]: looking up the BahnCard number. [Q-002 · 00:01:12]
- [[SYS-004-team-drive|Team drive]]: filing the invoices in the "Travel" folder by year and month. [Q-002 · 00:01:30]

## Steps

1. The traveler sends a travel request by email to the team mailbox. [Q-001 · 00:00:18]
2. The Assistant checks whether travel date, origin and destination, latest arrival time and BahnCard status are included. [Q-001 · 00:00:34]
3. If any detail is missing, the Assistant follows up by email. [Q-001 · 00:00:34]
4. The Assistant logs in to bahn.de in the browser with the business customer account. [Q-001 · 00:00:56]
5. The Assistant selects the connection in second class; in first class if the trip takes more than four hours. [Q-001 · 00:01:14]
6. The Assistant selects the fare: the default is the Flex fare; the Saver fare only if the date is fixed and the trip is more than fourteen days in the future. [Q-002 · 00:00:12] [Q-002 · 00:00:24]
7. If the traveler has a BahnCard, the Assistant enters the number from the Excel list so that the discount is applied. [Q-002 · 00:01:12]
8. The booking always includes a seat reservation. [Q-001 · 00:01:30]
9. If the amount is 250 euros or more, the Assistant obtains the team lead's approval by email before booking; below that, she books directly. [Q-002 · 00:00:53]
10. The Assistant pays with the corporate credit card stored in the business customer account. [Q-002 · 00:00:41]
11. The Assistant downloads the ticket as a PDF. [Q-001 · 00:01:42]
12. The Assistant sends the ticket PDF by email to the traveler. [Q-001 · 00:01:42]
13. The Assistant downloads the invoice as a PDF and files it on the team drive in the "Travel" folder, organized by year and month. [Q-002 · 00:01:30]
14. At the end of the month, the Assistant hands over the month's collected invoices to Accounting. [Q-002 · 00:01:48]

⚠️ inferred: The order of steps 5 to 10 within the booking is not documented in the sources; both recordings cover the sub-steps separately. Only that approval happens "beforehand" is documented. [Q-002 · 00:00:53]

## Decisions in the process

- Is the request complete? If not: follow-up question by email. [Q-001 · 00:00:34]
- Does the trip take longer than four hours? If yes: first class, otherwise second class. [Q-001 · 00:01:14]
- Is the date fixed and the trip more than fourteen days in the future? If yes: Saver fare possible, otherwise Flex fare. [Q-002 · 00:00:24]
- Does the traveler have a BahnCard? If yes: enter the number. [Q-001 · 00:00:34] [Q-002 · 00:01:12]
- Is the booking 250 euros or more? If yes: obtain the team lead's approval, otherwise book directly. [Q-002 · 00:00:53]

## Variants and special cases

- Before trade fairs, the booking volume rises considerably. [Q-001 · 00:01:58]
- Saver fare instead of Flex fare when the date is fixed and the lead time is more than fourteen days. [Q-002 · 00:00:24]
- Approval by the team lead from 250 euros per booking. [Q-002 · 00:00:53]
- ~~Handling of fare selection and payment: not captured, announced for the next recording.~~ [Q-001 · 00:02:20] (superseded by [Q-002 · 00:00:12] to [Q-002 · 00:01:48])
- ~~Changes and special cases: not captured, announced for the next recording.~~ [Q-002 · 00:01:58] (superseded by [Q-003 · 00:00:10] to [Q-003 · 00:01:27])
- If the trip is called off, the Assistant cancels upon the traveler's email; see [[PRO-002-cancel-train-trip|PRO-002]]. [Q-003 · 00:00:10]
- If only the time changes, the Flex fare ticket stays and only the seat reservation is rebooked; see [[PRO-003-change-travel-time|PRO-003]]. [Q-003 · 00:00:28]
- Delay refund: not part of the process; the traveler handles it personally. [Q-003 · 00:00:47]
- International trips: not part of the process; they go through the travel agency. [Q-003 · 00:01:00]
- Deputy: a person from the admin office with access to the business customer account. [Q-003 · 00:01:12]
- Expired BahnCard: usually only noticed when the discount no longer works at booking; maintenance of the list is not defined. [Q-003 · 00:01:27]

## Pain points

- An expired BahnCard is usually only noticed at booking, when the discount no longer works; there is no defined maintenance of the list. [Q-003 · 00:01:27]
- Further pain points: not captured.

## Key figures

- Time per booking when the request is complete: about ten minutes. [Q-001 · 00:02:12]

## Derived requirements

- [[ANF-001-required-details-travel-request|ANF-001]] Required details of the travel request
- [[ANF-002-second-class-first-over-four-hours|ANF-002]] Second class, first class for trips over four hours
- [[ANF-003-always-seat-reservation|ANF-003]] Always a seat reservation
- [[ANF-004-ticket-as-pdf-by-email|ANF-004]] Ticket as PDF by email to the traveler
- [[ANF-005-flex-fare-as-default|ANF-005]] Flex fare as the default fare
- [[ANF-006-saver-fare-only-fixed-date|ANF-006]] Saver fare only with a fixed date and more than fourteen days of lead time
- [[ANF-007-approval-from-250-euros|ANF-007]] Approval by the team lead from 250 euros
- [[ANF-008-bahncard-number-at-booking|ANF-008]] Enter the BahnCard number at booking
- [[ANF-009-invoice-on-team-drive|ANF-009]] File the invoice as PDF on the team drive
- [[ANF-010-invoices-monthly-to-accounting|ANF-010]] Invoices collected monthly to Accounting
- [[ANF-013-delay-refund-by-traveler|ANF-013]] Delay refund handled by the traveler personally (scope boundary)
- [[ANF-014-international-trips-via-travel-agency|ANF-014]] International trips via the travel agency (scope boundary)
- [[ANF-015-deputy-access-business-account|ANF-015]] Deputy with access to the business customer account

## Open items

- [[OP-001-fare-and-payment|OP-001]] Fare and payment (resolved by Q-002)
- [[OP-002-clarify-first-class-rule|OP-002]] Clarify the first-class rule
- [[OP-003-volume-before-trade-fairs|OP-003]] Volume figures before trade fairs
- [[OP-004-no-seat-reservation-available|OP-004]] Procedure when no seat reservation is available
- [[OP-005-criterion-fixed-date|OP-005]] Criterion "date is fixed"
- [[OP-006-clarify-approval-threshold|OP-006]] Clarify the 250-euro approval threshold
- [[OP-007-handover-to-accounting|OP-007]] Form of the invoice handover to Accounting
- [[OP-008-maintaining-bahncard-list|OP-008]] Maintaining the BahnCard list (partial answer from Q-003: not defined)
- [[OP-011-deputy-scope-and-handover|OP-011]] Deputy: scope, system access and handover
- [[OP-012-scope-international-trips|OP-012]] Scope of international trips

## Downstream processes

- [[PRO-002-cancel-train-trip|PRO-002]] Cancellation of a train trip
- [[PRO-003-change-travel-time|PRO-003]] Change of travel time

## Sources

- [[Q-001-bahn-01-process-overview|Q-001]]
- [[Q-002-bahn-02-booking-and-payment|Q-002]]
- [[Q-003-bahn-03-changes-and-special-cases|Q-003]]
