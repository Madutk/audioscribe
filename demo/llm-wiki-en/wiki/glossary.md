# Glossary

| Term | Meaning in the domain | Synonyms | Misrecognitions | Source |
|---|---|---|---|---|
| Travel request | Email from a team member to the team mailbox that triggers a train booking; contains travel date, origin and destination, latest arrival time and BahnCard status | Request | – | [Q-001 · 00:00:18] [Q-001 · 00:00:34] |
| Team mailbox | Shared email mailbox of the team where travel requests arrive; see [[SYS-002-team-mailbox]] | – | – | [Q-001 · 00:00:18] |
| Business customer account | Account on bahn.de that the Assistant logs in with to book; see [[SYS-001-bahn-de]] | – | – | [Q-001 · 00:00:56] |
| BahnCard | Discount card of the traveler; whether one exists is a required detail of the travel request; the number is entered when booking so the discount is applied | – | – | [Q-001 · 00:00:34] [Q-002 · 00:01:12] |
| Seat reservation | Reservation of a seat that is always booked along with every booking; on a time change, only the seat reservation is rebooked | Seat, reservation | – | [Q-001 · 00:01:30] [Q-003 · 00:00:28] |
| Latest arrival | Time by which the traveler must be at the destination at the latest; required detail of the travel request | Arrival time | – | [Q-001 · 00:00:34] |
| First class / second class | Travel class; second class as a rule, first class only for trips over four hours | – | – | [Q-001 · 00:01:14] |
| Flex fare | Deutsche Bahn "Flexpreis"; default fare for train bookings, chosen because dates often shift; valid for any train that day; cancellation free of charge until one day before the trip | Flexpreis, flexible fare | – | [Q-002 · 00:00:12] [Q-003 · 00:00:10] [Q-003 · 00:00:28] |
| Saver fare | Deutsche Bahn "Sparpreis"; exception fare, only with a fixed date and more than fourteen days ahead | Sparpreis | Safer fare | [Q-002 · 00:00:24] |
| Corporate credit card | Means of payment for train bookings, stored in the business customer account | Company credit card | – | [Q-002 · 00:00:41] |
| Approval | Prior consent of the team lead by email, required from 250 euros per booking | Authorization | – | [Q-002 · 00:00:53] |
| BahnCard list | The Assistant's Excel list of all BahnCards on the team; maintenance when a card expires is not defined; see [[SYS-003-bahncard-excel-list]] | Excel list | – | [Q-002 · 00:01:12] [Q-003 · 00:01:27] |
| Team drive | The team's network drive; invoices are filed in the Travel folder by year and month; see [[SYS-004-team-drive]] | – | – | [Q-002 · 00:01:30] |
| Invoice | PDF record of a booking, filed on the team drive and handed over to Accounting monthly; relationship to the ticket PDF not captured | – | – | [Q-002 · 00:01:30] [Q-002 · 00:01:48] |
| Cancellation | Undoing a booking by the Assistant when the traveler reports by email that the trip is called off; see [[PRO-002-cancel-train-trip]] | Cancel | – | [Q-003 · 00:00:10] |
| Delay refund | Reimbursement because of a train delay; the traveler applies for it themselves, without the Assistant | Compensation | – | [Q-003 · 00:00:47] |
| International trip | Trip that the Assistant does not book; it goes through the travel agency; scope not captured | – | – | [Q-003 · 00:01:00] |
| Travel agency | Office through which international trips are handled; whether internal or external is not captured; see [[ROL-006-travel-agency]] | – | – | [Q-003 · 00:01:00] |
| Deputy | Person from the admin office who covers for the Assistant and has access to the business customer account; see [[ROL-005-deputy-admin-office]] | – | – | [Q-003 · 00:01:12] |
| Admin office | Organizational unit the Assistant's deputy comes from | – | – | [Q-003 · 00:01:12] |

## Confirmed misrecognitions

Terms that speech recognition regularly gets wrong, with the correct form.

| Misrecognition | Correct |
|---|---|
| Safer fare | Saver fare |
