---
id: PRO-003
typ: prozess
titel: Change of travel time
status: skizze
quellen: [Q-003]
aktualisiert: 2026-10-06
---

# PRO-003 · Change of travel time

## Purpose

If only the time of a booked trip changes, the seat reservation is rebooked; the Flex fare ticket stays unchanged. [Q-003 · 00:00:28]

## Trigger

not captured. ⚠️ inferred: presumably a message from the traveler, analogous to cancellation [Q-003 · 00:00:10]; the source says nothing about it.

## Frequency

not captured

## Roles

- [[ROL-001-assistant|Assistant]]: rebooks the seat reservation. [Q-003 · 00:00:28]
- [[ROL-002-traveler|Traveler]]: ⚠️ inferred as the trigger of the change; not documented.

## Systems

- ⚠️ inferred: The seat reservation is rebooked on [[SYS-001-bahn-de|bahn.de]], because that is where bookings are made; the source does not name the system. [Q-001 · 00:00:56]

## Steps

1. The time of the trip changes. [Q-003 · 00:00:28]
2. With the Flex fare, nothing needs to be changed on the ticket, because it is valid for any train on that day. [Q-003 · 00:00:28]
3. The Assistant only rebooks the seat reservation. [Q-003 · 00:00:28]

## Decisions in the process

- Does only the time change (same day)? If yes: the ticket stays, new seat. Otherwise: not captured. [Q-003 · 00:00:28]

## Variants and special cases

- Change of travel date or route: not captured.
- Time change with the Saver fare: not captured.
- Cost of the new seat reservation and handling of the old reservation: not captured.

## Pain points

not captured

## Derived requirements

- [[ANF-012-time-change-rebook-seat-only|ANF-012]] On a time change, rebook only the seat reservation
- [[ANF-003-always-seat-reservation|ANF-003]] Every booking with a seat reservation

## Open items

- [[OP-010-changes-beyond-time|OP-010]] Changes beyond the time, Saver fare and trigger

## Context

- Upstream: [[PRO-001-train-booking|PRO-001]] Train booking
- Related: [[PRO-002-cancel-train-trip|PRO-002]] Cancellation of a train trip

## Sources

- [[Q-003-bahn-03-changes-and-special-cases|Q-003]]
