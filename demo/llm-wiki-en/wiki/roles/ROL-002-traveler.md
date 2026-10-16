---
id: ROL-002
typ: rolle
titel: Traveler
status: aufgenommen
quellen: [Q-001, Q-003]
aktualisiert: 2026-10-06
---

# ROL-002 · Traveler

Referred to in the source as "my coworkers" or "the traveler". [Q-001 · 00:00:18] [Q-001 · 00:01:42]

## Tasks in the domain

- Sends the travel request by email to the team mailbox. [Q-001 · 00:00:18]
- Provides travel date, origin and destination, latest arrival time and BahnCard status; answers follow-up questions. [Q-001 · 00:00:34]
- Receives the ticket as a PDF by email. [Q-001 · 00:01:42]
- Notifies the Assistant by email when a trip is called off. [Q-003 · 00:00:10]
- Handles refunds for delays personally. [Q-003 · 00:00:47]

## Processes involved

- [[PRO-001-train-booking|PRO-001]] Train booking
- [[PRO-002-cancel-train-trip|PRO-002]] Cancelling a train trip (trigger)
- [[PRO-003-change-travel-time|PRO-003]] Changing the travel time (⚠️ inferred as the trigger)

## Systems used

- [[SYS-002-team-mailbox|SYS-002]] Team mailbox (as sender and recipient)

## Authority and limits

- Applies for delay refunds personally, without the Assistant. [Q-003 · 00:00:47]
- Other authority: not captured.

## Related requirements

- [[ANF-001-required-details-travel-request|ANF-001]], [[ANF-004-ticket-as-pdf-by-email|ANF-004]], [[ANF-008-bahncard-number-at-booking|ANF-008]]
- [[ANF-011-cancellation-on-email|ANF-011]], [[ANF-013-delay-refund-by-traveler|ANF-013]]

## Open items

- [[OP-013-delay-refund-recipient|OP-013]]

## Sources

- [[Q-001-bahn-01-process-overview|Q-001]]
- [[Q-003-bahn-03-changes-and-special-cases|Q-003]]
