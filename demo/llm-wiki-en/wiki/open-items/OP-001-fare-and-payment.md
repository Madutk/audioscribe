---
id: OP-001
typ: offener-punkt
titel: Fare and payment for train bookings
status: geklärt
quellen: [Q-001, Q-002]
aktualisiert: 2026-10-06
---

# OP-001 · Fare and payment for train bookings

## Question

Which fare is chosen (Flex fare, Saver fare, use of the BahnCard), and how is payment made (business customer account, invoice, billing)?

## Why it is open

The Moderator explicitly postponed fare and payment to the next recording. [Q-001 · 00:02:20] The BahnCard status is a required detail of the request, but how it is used at booking is not described. [Q-001 · 00:00:34]

## Who can answer

[[ROL-001-assistant|Assistant]]

## Affected pages

- [[PRO-001-train-booking|PRO-001]]
- [[SYS-001-bahn-de|SYS-001]]
- [[ANF-001-required-details-travel-request|ANF-001]]

## Answer

Resolved by the second process recording:

- Fare: the default is the Flex fare, because dates often shift. [Q-002 · 00:00:12] Saver fare only with a fixed date and more than fourteen days of lead time. [Q-002 · 00:00:24] See [[ANF-005-flex-fare-as-default|ANF-005]], [[ANF-006-saver-fare-only-fixed-date|ANF-006]].
- BahnCard: the number is entered from an Excel list at booking so that the discount is applied. [Q-002 · 00:01:12] See [[ANF-008-bahncard-number-at-booking|ANF-008]].
- Payment: with the corporate credit card stored in the business customer account. [Q-002 · 00:00:41] From 250 euros per booking with prior approval by the team lead. [Q-002 · 00:00:53] See [[ANF-007-approval-from-250-euros|ANF-007]].
- Billing: invoice as PDF on the team drive, collected monthly and sent to Accounting. [Q-002 · 00:01:30] [Q-002 · 00:01:48] See [[ANF-009-invoice-on-team-drive|ANF-009]], [[ANF-010-invoices-monthly-to-accounting|ANF-010]].

Follow-up questions: [[OP-005-criterion-fixed-date|OP-005]], [[OP-006-clarify-approval-threshold|OP-006]], [[OP-007-handover-to-accounting|OP-007]], [[OP-008-maintaining-bahncard-list|OP-008]].
