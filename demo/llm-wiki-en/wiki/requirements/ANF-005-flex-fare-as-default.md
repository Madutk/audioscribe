---
id: ANF-005
typ: anforderung
titel: Flex fare as the default fare
status: entwurf
art: randbedingung
prioritaet: unbekannt
quellen: [Q-002, Q-003]
aktualisiert: 2026-10-06
---

# ANF-005 · Flex fare as the default fare

## Requirement

Train trips are booked at the Flex fare by default. [Q-002 · 00:00:12]

## Rationale

Appointments in the team often get moved. [Q-002 · 00:00:12]

## Origin

Derived from the description of the current state in the process recording; not confirmed as a requirement by the business side. [Q-002 · 00:00:12]

## Affected processes, systems, roles

- Process: [[PRO-001-train-booking|PRO-001]], step 6
- Systems: [[SYS-001-bahn-de|SYS-001]]
- Roles: [[ROL-001-assistant|ROL-001]]

## Acceptance criterion

not captured

## Related

- Exception: [[ANF-006-saver-fare-only-fixed-date|ANF-006]]
- Properties of the Flex fare according to the source: free cancellation up to one day before the trip. [Q-003 · 00:00:10]
- The Flex fare ticket is valid on any train that day; if the departure time changes, only the seat is rebooked. [Q-003 · 00:00:28]
- Follow-on requirements: [[ANF-011-cancellation-on-email|ANF-011]], [[ANF-012-time-change-rebook-seat-only|ANF-012]]

## Sources

- [[Q-002-bahn-02-booking-and-payment|Q-002]]
- [[Q-003-bahn-03-changes-and-special-cases|Q-003]]
