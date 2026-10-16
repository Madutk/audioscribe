---
id: PRO-002
typ: prozess
titel: Cancellation of a train trip
status: skizze
quellen: [Q-003]
aktualisiert: 2026-10-06
---

# PRO-002 · Cancellation of a train trip

## Purpose

A booked train trip that is called off is canceled by the Assistant. [Q-003 · 00:00:10]

## Trigger

An email from the traveler to the Assistant saying that the trip is called off. [Q-003 · 00:00:10]

## Frequency

not captured

## Roles

- [[ROL-002-traveler|Traveler]]: reports the cancellation by email. [Q-003 · 00:00:10]
- [[ROL-001-assistant|Assistant]]: cancels. [Q-003 · 00:00:10]

## Systems

- Email for the notification; whether via the [[SYS-002-team-mailbox|team mailbox]]: not captured. [Q-003 · 00:00:10]
- ⚠️ inferred: The cancellation is done on [[SYS-001-bahn-de|bahn.de]] in the business customer account, because that is where bookings are made; the source does not name the system used for cancellation. [Q-001 · 00:00:56]

## Steps

1. The traveler emails the Assistant that the trip is called off. [Q-003 · 00:00:10]
2. The Assistant cancels the booking. [Q-003 · 00:00:10]
3. With the Flex fare, cancellation is free of charge up to one day before the trip. [Q-003 · 00:00:10]

## Decisions in the process

- Flex fare and at least one day before the trip? If yes: free cancellation. Otherwise: not captured. [Q-003 · 00:00:10]

## Variants and special cases

- Cancellation with the Saver fare: not captured.
- Cancellation less than one day before the trip: not captured.
- Handling of the already filed invoice and of the refund: not captured.

## Pain points

not captured

## Derived requirements

- [[ANF-011-cancellation-on-email|ANF-011]] Cancellation upon the traveler's email

## Open items

- [[OP-009-cancellation-special-cases|OP-009]] Cancellation: Saver fare, short notice, refund and filing

## Context

- Upstream: [[PRO-001-train-booking|PRO-001]] Train booking
- Related: [[PRO-003-change-travel-time|PRO-003]] Change of travel time

## Sources

- [[Q-003-bahn-03-changes-and-special-cases|Q-003]]
