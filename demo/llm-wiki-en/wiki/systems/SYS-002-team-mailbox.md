---
id: SYS-002
typ: system
titel: Team mailbox (email)
status: genannt
quellen: [Q-001, Q-003]
aktualisiert: 2026-10-06
---

# SYS-002 · Team mailbox (email)

## Exact name

Referred to in the source only as the "team mailbox"; the email system itself is not named. [Q-001 · 00:00:18]

## Purpose in the domain

- Inbound channel for colleagues' travel requests. [Q-001 · 00:00:18]
- Channel for follow-up questions on incomplete requests. [Q-001 · 00:00:34]
- Channel for sending the ticket PDF to the traveler. [Q-001 · 00:01:42]

## Who uses it

- [[ROL-001-assistant|Assistant]] (reads the mailbox, follows up, sends tickets). [Q-001 · 00:00:34] [Q-001 · 00:01:42]
- [[ROL-002-traveler|Traveler]] (sends requests, receives tickets). [Q-001 · 00:00:18] [Q-001 · 00:01:42]

## Processes

- [[PRO-001-train-booking|PRO-001]] Train booking, steps 1, 3 and 12

## Interfaces and media breaks

- No system interface to [[SYS-001-bahn-de|bahn.de]] described. not captured
- Whether the approval email to the team lead goes through the team mailbox: not captured (see [[ANF-007-approval-from-250-euros|ANF-007]]). [Q-002 · 00:00:53]
- Whether the traveler's cancellation notice arrives in the team mailbox: not captured (see [[PRO-002-cancel-train-trip|PRO-002]]). [Q-003 · 00:00:10]
- Whether the deputy has access to the team mailbox: not captured (see [[OP-011-deputy-scope-and-handover|OP-011]]). [Q-003 · 00:01:12]

## Known limitations

not captured

## Related requirements

- [[ANF-001-required-details-travel-request|ANF-001]], [[ANF-004-ticket-as-pdf-by-email|ANF-004]], [[ANF-011-cancellation-on-email|ANF-011]]

## Sources

- [[Q-001-bahn-01-process-overview|Q-001]]
- [[Q-003-bahn-03-changes-and-special-cases|Q-003]]
