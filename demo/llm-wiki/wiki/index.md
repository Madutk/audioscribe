# Index

Höchste vergebene Nummern: Q-003 · PRO-003 · ANF-015 · SYS-004 · ROL-006 · ENT-000 · OP-013 · WID-000 · AN-000

## Übergreifend

- [[uebersicht]]: Lagebild der Domäne
- [[glossar]]: Begriffe und Fehlerkennungen

## Quellen

- [[Q-001-bahn-01-prozessueberblick|Q-001]] Prozessaufnahme 1 – Prozessüberblick Bahnbuchung · eingearbeitet · Aufnahme vom 2026-09-08 mit der Assistenz zum Ablauf einer Bahnbuchung von der Reiseanfrage bis zum Ticketversand.
- [[Q-002-bahn-02-buchung-und-bezahlung|Q-002]] Prozessaufnahme 2 – Tarif, Bezahlung und Ablage · eingearbeitet · Aufnahme vom 2026-09-15 mit der Assistenz zu Tarifwahl, Firmenkreditkarte, Freigabe ab 250 Euro, BahnCard-Liste, Rechnungsablage und Buchhaltung.
- [[Q-003-bahn-03-aenderungen-und-sonderfaelle|Q-003]] Prozessaufnahme 3 – Änderungen, Storno und Sonderfälle · eingearbeitet · Aufnahme vom 2026-09-22 mit der Assistenz zu Stornierung, Uhrzeitänderung, Verspätungserstattung, Auslandsreisen, Vertretung und ungeregelter Pflege der BahnCard-Liste.

## Prozesse

- [[PRO-001-bahnbuchung|PRO-001]] Bahnbuchung für Teammitglieder · aufgenommen · Reiseanfrage per E-Mail, Prüfung, Buchung und Bezahlung auf bahn.de, Ticket per E-Mail, Rechnungsablage, monatliche Übergabe an die Buchhaltung.
- [[PRO-002-stornierung-bahnreise|PRO-002]] Stornierung einer Bahnreise · skizze · Reisende Person meldet Ausfall per E-Mail, Assistenz storniert; beim Flexpreis kostenlos bis einen Tag vor der Reise.
- [[PRO-003-aenderung-reisezeit|PRO-003]] Änderung der Reisezeit · skizze · Bei Uhrzeitänderung bleibt das Flexpreis-Ticket, nur die Sitzplatzreservierung wird neu gebucht.

## Anforderungen

- [[ANF-001-pflichtangaben-reiseanfrage|ANF-001]] Pflichtangaben der Reiseanfrage · entwurf · Reisedatum, Start, Ziel, späteste Ankunft und BahnCard-Status müssen enthalten sein, sonst Rückfrage.
- [[ANF-002-zweite-klasse-erste-ab-vier-stunden|ANF-002]] Zweite Klasse, erste Klasse ab mehr als vier Stunden Fahrtdauer · entwurf · Klassenregel für Bahnbuchungen.
- [[ANF-003-sitzplatzreservierung-immer|ANF-003]] Jede Buchung mit Sitzplatzreservierung · entwurf · Ohne Sitzplatzreservierung wird nicht gebucht.
- [[ANF-004-ticket-als-pdf-per-e-mail|ANF-004]] Ticket als PDF per E-Mail an die reisende Person · entwurf · Zustellung des Tickets nach der Buchung.
- [[ANF-005-flexpreis-als-standardtarif|ANF-005]] Flexpreis als Standardtarif · entwurf · Standardtarif, weil sich Termine oft verschieben.
- [[ANF-006-sparpreis-nur-bei-festem-termin|ANF-006]] Sparpreis nur bei festem Termin und mehr als vierzehn Tagen Vorlauf · entwurf · Ausnahme vom Flexpreis.
- [[ANF-007-freigabe-ab-250-euro|ANF-007]] Freigabe durch die Teamleitung ab 250 Euro pro Buchung · entwurf · Vorherige Freigabe per E-Mail, darunter direkte Buchung.
- [[ANF-008-bahncard-nummer-bei-buchung|ANF-008]] BahnCard-Nummer bei der Buchung eintragen · entwurf · Nummer aus der Excel-Liste, damit der Rabatt abgezogen wird.
- [[ANF-009-rechnung-auf-teamlaufwerk|ANF-009]] Rechnung als PDF auf dem Teamlaufwerk ablegen · entwurf · Ordner Reisen, darunter nach Jahr und Monat.
- [[ANF-010-rechnungen-monatlich-an-buchhaltung|ANF-010]] Rechnungen monatlich gesammelt an die Buchhaltung · entwurf · Übergabe immer am Monatsende.
- [[ANF-011-stornierung-auf-e-mail|ANF-011]] Stornierung auf E-Mail der reisenden Person · entwurf · Bei Ausfall der Reise storniert die Assistenz nach E-Mail-Meldung.
- [[ANF-012-uhrzeitaenderung-nur-sitzplatz-neu|ANF-012]] Bei Uhrzeitänderung nur die Sitzplatzreservierung neu buchen · entwurf · Flexpreis-Ticket bleibt, weil es für jeden Zug am Tag gilt.
- [[ANF-013-erstattung-bei-verspaetung-durch-reisende-person|ANF-013]] Erstattung bei Verspätung durch die reisende Person selbst · entwurf · Abgrenzung: Assistenz nicht beteiligt.
- [[ANF-014-auslandsreisen-ueber-reisebuero|ANF-014]] Auslandsreisen über das Reisebüro · entwurf · Abgrenzung: Assistenz bucht keine Auslandsreisen.
- [[ANF-015-vertretung-zugang-geschaeftskundenkonto|ANF-015]] Vertretung mit Zugang zum Geschäftskundenkonto · entwurf · Person aus dem Sekretariat vertritt die Assistenz.

## Systeme

- [[SYS-001-bahn-de|SYS-001]] bahn.de (Geschäftskundenkonto) · beschrieben · Buchungsportal im Browser, Anmeldung mit Geschäftskundenkonto, Firmenkreditkarte hinterlegt, Ticket und Rechnung als PDF-Download.
- [[SYS-002-teampostfach|SYS-002]] Teampostfach (E-Mail) · genannt · Eingang der Reiseanfragen, Rückfragen und Ticketversand; E-Mail-System nicht benannt.
- [[SYS-003-excel-liste-bahncards|SYS-003]] Excel-Liste der BahnCards · genannt · Von der Assistenz geführte Liste aller BahnCards im Team.
- [[SYS-004-teamlaufwerk|SYS-004]] Teamlaufwerk (Ordner Reisen) · genannt · Ablage der Rechnungs-PDFs nach Jahr und Monat.

## Rollen

- [[ROL-001-assistenz|ROL-001]] Assistenz · aufgenommen · Nimmt Reiseanfragen entgegen, prüft, bucht und bezahlt auf bahn.de, versendet das Ticket, legt Rechnungen ab und übergibt sie monatlich.
- [[ROL-002-reisende-person|ROL-002]] Reisende Person · aufgenommen · Stellt die Reiseanfrage per E-Mail und erhält das Ticket.
- [[ROL-003-teamleitung|ROL-003]] Teamleitung · aufgenommen · Gibt Buchungen ab 250 Euro vorab per E-Mail frei.
- [[ROL-004-buchhaltung|ROL-004]] Buchhaltung · aufgenommen · Erhält die Rechnungen monatlich gesammelt am Monatsende.
- [[ROL-005-vertretung-sekretariat|ROL-005]] Vertretung der Assistenz (Sekretariat) · aufgenommen · Vertritt die Assistenz, hat Zugang zum Geschäftskundenkonto; Umfang nicht erhoben.
- [[ROL-006-reisebuero|ROL-006]] Reisebüro · genannt · Über das Reisebüro laufen die Auslandsreisen; intern oder extern nicht erhoben.

## Entscheidungen

## Offene Punkte

- [[OP-001-tarif-und-bezahlung|OP-001]] Tarif und Bezahlung bei der Bahnbuchung · geklärt · Durch Q-002 beantwortet: Flexpreis, Sparpreis-Ausnahme, Firmenkreditkarte, Freigabe ab 250 Euro, BahnCard-Liste, Rechnungsablage.
- [[OP-002-regel-erste-klasse-praezisieren|OP-002]] Regel für erste Klasse präzisieren · offen · Bezugsgröße der Vier-Stunden-Grenze, Herkunft der Regel, Freigabe.
- [[OP-003-mengengeruest-vor-messen|OP-003]] Mengengerüst vor Messen · offen · "Deutlich mehr" Buchungen vor Messen ist nicht quantifiziert.
- [[OP-004-keine-sitzplatzreservierung-moeglich|OP-004]] Vorgehen ohne verfügbare Sitzplatzreservierung · offen · Was passiert, wenn keine Reservierung möglich ist.
- [[OP-005-kriterium-fester-termin|OP-005]] Kriterium "Termin steht fest" für den Sparpreis · offen · Wer entscheidet das und woran erkennt es die Assistenz.
- [[OP-006-freigabegrenze-praezisieren|OP-006]] Freigabegrenze 250 Euro präzisieren · offen · Bezugsgröße, Dokumentation, Wartezeit, Ablehnung.
- [[OP-007-uebergabe-an-buchhaltung|OP-007]] Form der Rechnungsübergabe an die Buchhaltung · offen · Übergabeweg und Verhältnis von Ticket-PDF und Rechnungs-PDF.
- [[OP-008-pflege-bahncard-liste|OP-008]] Pflege der BahnCard-Liste · offen · Laut Q-003 nicht geregelt; künftige Zuständigkeit und Verhältnis zur Pflichtangabe in der Reiseanfrage offen.
- [[OP-009-stornierung-sonderfaelle|OP-009]] Stornierung: Sparpreis, Kurzfrist, Erstattung und Ablage · offen · Nur der Flexpreis-Fall ist beschrieben.
- [[OP-010-aenderung-ueber-uhrzeit-hinaus|OP-010]] Änderung über die Uhrzeit hinaus, Sparpreis und Auslöser · offen · Datums- und Streckenänderung, Sparpreis, Kosten der Neureservierung.
- [[OP-011-vertretung-umfang-und-uebergabe|OP-011]] Vertretung: Umfang, Systemzugänge und Übergabe · offen · Nur der Zugang zum Geschäftskundenkonto ist belegt.
- [[OP-012-abgrenzung-auslandsreisen|OP-012]] Abgrenzung Auslandsreisen und Weiterleitung an das Reisebüro · offen · Erkennung, Weiterleitung, intern oder extern.
- [[OP-013-erstattung-verspaetung-empfaenger|OP-013]] Erstattung bei Verspätung: Empfänger und Rückmeldung · offen · Reisende Person beantragt, Firmenkreditkarte hat bezahlt.

## Widersprüche

## Analysen
