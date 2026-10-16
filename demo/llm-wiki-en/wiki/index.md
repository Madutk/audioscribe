# Index

Highest assigned numbers: Q-003 · PRO-003 · ANF-015 · SYS-004 · ROL-006 · ENT-000 · OP-013 · WID-000 · AN-000

## Cross-cutting

- [[overview]]: Situation overview of the domain
- [[glossary]]: Terms and misrecognitions

## Sources

- [[Q-001-bahn-01-process-overview|Q-001]] Process recording 1 – Train booking process overview · incorporated · Recording from 2026-09-08 with the Assistant on how a train booking works, from the travel request to sending the ticket.
- [[Q-002-bahn-02-booking-and-payment|Q-002]] Process recording 2 – Fare, payment and filing · incorporated · Recording from 2026-09-15 with the Assistant on fare choice, corporate credit card, approval from 250 euros, BahnCard list, invoice filing and Accounting.
- [[Q-003-bahn-03-changes-and-special-cases|Q-003]] Process recording 3 – Changes, cancellations and special cases · incorporated · Recording from 2026-09-22 with the Assistant on cancellation, time changes, delay refunds, international trips, deputy coverage and the undefined maintenance of the BahnCard list.

## Processes

- [[PRO-001-train-booking|PRO-001]] Train booking for team members · recorded · Travel request by email, check, booking and payment on bahn.de, ticket by email, invoice filing, monthly handover to Accounting.
- [[PRO-002-cancel-train-trip|PRO-002]] Cancellation of a train trip · sketch · Traveler reports the cancellation by email, the Assistant cancels; free of charge with the Flex fare until one day before the trip.
- [[PRO-003-change-travel-time|PRO-003]] Change of travel time · sketch · When the time changes, the Flex fare ticket stays; only the seat reservation is rebooked.

## Requirements

- [[ANF-001-required-details-travel-request|ANF-001]] Required details of the travel request · draft · Travel date, origin, destination, latest arrival and BahnCard status must be included, otherwise follow-up question.
- [[ANF-002-second-class-first-over-four-hours|ANF-002]] Second class, first class only for trips longer than four hours · draft · Class rule for train bookings.
- [[ANF-003-always-seat-reservation|ANF-003]] Every booking with a seat reservation · draft · Nothing is booked without a seat reservation.
- [[ANF-004-ticket-as-pdf-by-email|ANF-004]] Ticket as a PDF by email to the traveler · draft · Delivery of the ticket after booking.
- [[ANF-005-flex-fare-as-default|ANF-005]] Flex fare as the default fare · draft · Default fare because dates often shift.
- [[ANF-006-saver-fare-only-fixed-date|ANF-006]] Saver fare only for a fixed date and more than fourteen days in advance · draft · Exception to the Flex fare.
- [[ANF-007-approval-from-250-euros|ANF-007]] Approval by the team lead from 250 euros per booking · draft · Prior approval by email; below that, direct booking.
- [[ANF-008-bahncard-number-at-booking|ANF-008]] Enter the BahnCard number when booking · draft · Number from the Excel list so the discount is applied.
- [[ANF-009-invoice-on-team-drive|ANF-009]] File the invoice as a PDF on the team drive · draft · Travel folder, below that by year and month.
- [[ANF-010-invoices-monthly-to-accounting|ANF-010]] Invoices to Accounting in a monthly batch · draft · Handover always at the end of the month.
- [[ANF-011-cancellation-on-email|ANF-011]] Cancellation upon email from the traveler · draft · If the trip is called off, the Assistant cancels after notification by email.
- [[ANF-012-time-change-rebook-seat-only|ANF-012]] On a change of departure time, rebook only the seat reservation · draft · The Flex fare ticket stays because it is valid for any train that day.
- [[ANF-013-delay-refund-by-traveler|ANF-013]] Delay refunds handled by the traveler · draft · Scope: the Assistant is not involved.
- [[ANF-014-international-trips-via-travel-agency|ANF-014]] International trips via the travel agency, not via the Assistant · draft · Scope: the Assistant does not book international trips.
- [[ANF-015-deputy-access-business-account|ANF-015]] Deputy for the Assistant with access to the business customer account · draft · A person from the admin office covers for the Assistant.

## Systems

- [[SYS-001-bahn-de|SYS-001]] bahn.de (business customer account) · described · Booking portal in the browser, login with the business customer account, corporate credit card on file, ticket and invoice as PDF downloads.
- [[SYS-002-team-mailbox|SYS-002]] Team mailbox (email) · named · Receives travel requests, follow-up questions and ticket delivery; email system not named.
- [[SYS-003-bahncard-excel-list|SYS-003]] BahnCard Excel list · named · List of all BahnCards on the team, kept by the Assistant.
- [[SYS-004-team-drive|SYS-004]] Team drive ("Travel" folder) · named · Storage of invoice PDFs by year and month.

## Roles

- [[ROL-001-assistant|ROL-001]] Assistant · recorded · Receives travel requests, checks, books and pays on bahn.de, sends the ticket, files invoices and hands them over monthly.
- [[ROL-002-traveler|ROL-002]] Traveler · recorded · Submits the travel request by email and receives the ticket.
- [[ROL-003-team-lead|ROL-003]] Team lead · recorded · Approves bookings from 250 euros in advance by email.
- [[ROL-004-accounting|ROL-004]] Accounting · recorded · Receives the invoices collected monthly at the end of the month.
- [[ROL-005-deputy-admin-office|ROL-005]] Deputy for the Assistant (admin office) · recorded · Covers for the Assistant, has access to the business customer account; scope not captured.
- [[ROL-006-travel-agency|ROL-006]] Travel agency · named · International trips go through the travel agency; whether internal or external is not captured.

## Decisions

## Open items

- [[OP-001-fare-and-payment|OP-001]] Fare and payment for train bookings · resolved · Answered by Q-002: Flex fare, Saver fare exception, corporate credit card, approval from 250 euros, BahnCard list, invoice filing.
- [[OP-002-clarify-first-class-rule|OP-002]] Clarify the first-class rule · open · Basis of the four-hour limit, origin of the rule, approval.
- [[OP-003-volume-before-trade-fairs|OP-003]] Volume figures before trade fairs · open · "A lot more" bookings before trade fairs is not quantified.
- [[OP-004-no-seat-reservation-available|OP-004]] Procedure when no seat reservation is available · open · What happens if no reservation is possible.
- [[OP-005-criterion-fixed-date|OP-005]] Criterion "date is fixed" for the Saver fare · open · Who decides, and how the Assistant can tell.
- [[OP-006-clarify-approval-threshold|OP-006]] Clarify the 250-euro approval threshold · open · Basis, documentation, waiting time, rejection.
- [[OP-007-handover-to-accounting|OP-007]] Form of the invoice handover to Accounting · open · Handover channel and relationship between ticket PDF and invoice PDF.
- [[OP-008-maintaining-bahncard-list|OP-008]] Maintaining the BahnCard list · open · Not defined according to Q-003; future responsibility and relationship to the required detail in the travel request are open.
- [[OP-009-cancellation-special-cases|OP-009]] Cancellation: Saver fare, short notice, refund and filing · open · Only the Flex fare case is described.
- [[OP-010-changes-beyond-time|OP-010]] Changes beyond the time, Saver fare and trigger · open · Date and route changes, Saver fare, cost of rebooking the reservation.
- [[OP-011-deputy-scope-and-handover|OP-011]] Deputy: scope, system access and handover · open · Only access to the business customer account is documented.
- [[OP-012-scope-international-trips|OP-012]] Scope of international trips and forwarding to the travel agency · open · Identification, forwarding, internal or external.
- [[OP-013-delay-refund-recipient|OP-013]] Delay refund: recipient and feedback · open · The traveler applies, the corporate credit card paid.

## Contradictions

## Analyses
