# Audioscribe Souffleur: Anforderungen für die Umsetzung

Auftragsdokument für einen Entwickler-Agenten.
Stand: 06.10.2026 · Quelle der Features: Audioscribe Feature-Backlog (IDs A1 bis C1, K1)

## 1. Wie dieses Dokument zu lesen ist

Dieses Dokument beschreibt **Anforderungen, keine Spezifikation**. Es legt fest, was der Souffleur leisten muss und welche Regeln nicht verletzt werden dürfen. Architektur, Datenformate, Bibliotheken und Oberflächengestaltung entscheidest du selbst, passend zum bestehenden Code.

Dabei gilt:

- **Abschnitt 4 (Leitplanken) ist verbindlich.** Davon wird nicht abgewichen.
- **Abschnitt 6 (Anforderungen)** beschreibt das gewünschte Verhalten mit Abnahmekriterien. Der Weg dorthin ist frei.
- **Abschnitt 9 (offene Entscheidungen)** enthält Punkte, die noch nicht geklärt sind. Triff dort keine stillen Annahmen: mach einen begründeten Vorschlag und lass ihn bestätigen.
- Stellen, die mit **Annahme** markiert sind, hat der Auftraggeber nicht ausdrücklich bestätigt. Prüfe sie am Code und melde Abweichungen.

## 2. Ausgangslage

Audioscribe ist ein Werkzeug, das aus Bildschirmaufnahmen und gesprochenem Wort Prozessdokumentation erzeugt. Es gibt bereits einen Live-Betrieb: Während der Arbeit entstehen Screenshots und ein laufendes Transkript mit Zeitstempeln.

Neu hinzu kommt ein **LLM-Wiki nach dem Karpathy-Muster**: eine Wissensbasis, in die Transkripte als unveränderliche Quellen einfließen und die von einem eigenen Prozess (Lint) gepflegt wird. Wiki und Lint werden nicht von uns gebaut und nicht von uns betrieben.

## 3. Ziel

Der **Souffleur** ist eine Live-Funktion von Audioscribe. Er hört beim Meeting über das Live-Transkript mit, gleicht das Gesagte mit dem Wiki ab und gibt dem Moderator Hinweise: Stimmt das mit dem bekannten Wissen überein, gibt es Widersprüche, entstehen offene Punkte, wurde eine Frage gestellt, zu der das Wiki schon etwas weiß.

Einsatz in Meetings aller Art: Workshop, Prozess- oder Anforderungsaufnahme, Diskussion.

## 4. Leitplanken (verbindlich)

1. **Nur der Moderator** sieht und bedient den Souffleur. Er spricht nie selbst in den Raum und zeigt nichts für andere Teilnehmer an.
2. **Das Wiki wird nur gelesen.** Der Souffleur schreibt, ändert und löscht dort nichts.
3. **Quellen sind unveränderlich.** Bestehende Transkripte und Informationen werden nie verändert. Neues wird nur hinzugefügt.
4. **Das Gesagte bleibt unverfälscht.** Markierungen des Souffleurs dürfen den Wortlaut des Transkripts nicht verändern. Der reine Transkripttext muss jederzeit ohne Markierungen wiederherstellbar sein.
5. **Lint ist nicht unser Bereich.** Wir liefern Transkript und Markierungen ab. Was daraus im Wiki wird, entscheidet der Lint-Prozess.
6. **Belegtes und KI-Erzeugtes bleiben getrennt.** Jeder Hinweis aus dem Wiki trägt eine Fundstelle. Alles, was die KI selbst formuliert (Zusammenfassung, Einschätzung), ist als KI-erzeugt erkennbar und wird nicht als Quelle abgelegt.
7. **Kein Hinweis ohne Grundlage.** Findet der Souffleur im Wiki nichts, sagt er das ausdrücklich. Er füllt Lücken nicht mit eigenem Wissen.

## 5. Umfang

**In dieser Ausbaustufe:** K1, A1, A2, A3, A4, B1, B2, C1 (siehe Abschnitt 6).

**Ausdrücklich nicht in dieser Stufe:**

- B3 Lösungsknopf (KI entwickelt eigene Lösungsvorschläge). Ist für die nächste Stufe vorgesehen. Die Umsetzung soll ihn später ermöglichen, aber jetzt nicht enthalten.
- Jede Form von Wiki-Pflege, Konfliktauflösung oder Lint.
- Anzeige für andere Teilnehmer als den Moderator.
- Mehrere Wikis gleichzeitig. In dieser Stufe wird einem Projekt genau ein Wiki zugeordnet.
- Die Einträge aus dem Ideenspeicher des Backlogs (Abschnitt D dort).

## 6. Anforderungen

### K. Einstellungen

**K1 Wiki-Verknüpfung**
Das Wiki wird über die Einstellungen mit dem Projekt verknüpft. Die Pfadangabe zum Wiki ist Teil der Einstellungen.

- In den Einstellungen gibt es eine Pfadangabe für das Wiki. Sie ist die einzige Stelle, an der festgelegt wird, gegen welches Wiki der Souffleur abgleicht. Der Pfad steht nicht fest im Code.
- Einem Projekt ist genau ein Wiki zugeordnet. Die Zuordnung bleibt gespeichert und muss nicht bei jedem Meeting neu gesetzt werden.
- Der Pfad lässt sich ändern. Die Änderung gilt ab dem nächsten Meeting, ein laufendes Meeting wird dadurch nicht gestört.
- Beim Setzen wird geprüft, ob der Pfad erreichbar und lesbar ist und ob dort ein Wiki liegt. Das Ergebnis wird dem Moderator verständlich angezeigt.
- Ist kein Wiki verknüpft oder der Pfad nicht erreichbar, bleibt Audioscribe voll nutzbar. Die Wiki-abhängigen Funktionen (A1 bis A4, B2) zeigen ihren Zustand an, statt abzubrechen. Funktionen ohne Wiki-Bezug (B1, C1) laufen weiter.
- Die Verknüpfung gibt nur Lesezugriff (Leitplanke 2).
- Der Moderator sieht während des Meetings, mit welchem Wiki abgeglichen wird.
- **Annahme:** "Projekt" meint die Einheit, unter der Audioscribe Aufnahmen und Einstellungen zusammenfasst. Prüfe am Code, was dem entspricht, und melde, falls es eine solche Einheit noch nicht gibt.
- Abnahme: Pfad auf das Test-Wiki setzen, Meeting abspielen, Abgleich läuft. Pfad auf einen nicht vorhandenen Ordner setzen: verständliche Meldung, kein Absturz, Transkription läuft weiter.

### A. Wiki-Abgleich im Live-Transkript

**A1 Stimmigkeits-Check**
Der Souffleur gleicht laufend ab, ob das Gesagte zum Wissen im Wiki passt.

- Der Abgleich läuft während des Meetings mit, ohne dass der Moderator ihn je Aussage anstoßen muss.
- Geprüft werden inhaltliche Aussagen. Smalltalk, Füllwörter und Organisatorisches lösen keinen Hinweis aus.
- Aussagen, die zum Wiki passen, erzeugen keine Störung für den Moderator.

**A2 Widerspruch markieren**
Widerspricht eine Aussage dem Wiki, wird das im Live-Transkript markiert.

- Die Markierung zeigt auf die betroffene Stelle im Wiki und macht kenntlich, dass dort Änderungsbedarf bestehen kann.
- Der Moderator sieht beide Seiten: was gesagt wurde und was im Wiki steht.
- Der Souffleur entscheidet nicht, wer recht hat. Er meldet die Abweichung.
- Abnahme: In einem Testlauf mit bewusst eingebauten Widersprüchen werden diese gefunden und der richtigen Wiki-Stelle zugeordnet. Übereinstimmende Aussagen werden nicht als Widerspruch gemeldet.

**A3 Offene Punkte markieren**
Wirft das Gesagte neue offene Punkte auf, wird das markiert.

- Beispiele: Etwas wird als ungeklärt benannt, eine Zuständigkeit bleibt offen, es wird über etwas gesprochen, das im Wiki fehlt.
- Offene Punkte sind am Ende des Meetings als Liste abrufbar.

**A4 Übergabe ans Wiki**
Nach dem Meeting wird das Transkript samt Markierungen als neue Quelle für das Wiki bereitgestellt.

- Die Übergabe ist rein anhängend. Nichts Bestehendes wird überschrieben.
- Markierungen und Transkript gehören erkennbar zusammen, jede Markierung ist einer Stelle im Transkript zugeordnet (Zeitbezug).
- Das Übergabeformat ist noch nicht abgestimmt, siehe Abschnitt 9. Baue es so, dass es sich ohne Umbau des Rests anpassen lässt.
- Wohin die Übergabe abgelegt wird, ist offen (Abschnitt 9). Der Wiki-Pfad aus K1 ist ein Lesepfad und darf dafür nicht stillschweigend als Schreibziel verwendet werden.

### B. Fragen im Raum

**B1 Fragen-Erkennung**
In den Raum gestellte Fragen werden im Live-Transkript markiert.

- Echte Fragen werden erkannt, auch wenn sie nicht als sauberer Fragesatz formuliert sind.
- Rhetorische Fragen und Floskeln ("oder?", "nicht wahr?") sollen möglichst keine Markierung auslösen.

**B2 Antwortvorschlag aus dem Wiki**
Zu einer erkannten Frage zeigt der Souffleur dem Moderator, was im Wiki dazu bereits vorliegt.

- Jeder Antwortvorschlag nennt seine Fundstelle im Wiki.
- Liegt nichts vor, wird genau das angezeigt, und die Frage zählt als offener Punkt (A3).
- Der Vorschlag gibt Wiki-Wissen wieder. Er wird nicht mit eigenem Wissen der KI ergänzt.

### C. Zusammenfassung auf Knopfdruck

**C1 Essenz der letzten Minuten**
Der Moderator kann per Knopf die Essenz der letzten 2 oder 5 Minuten abrufen.

- Die Zusammenfassung bezieht sich genau auf das gewählte Zeitfenster.
- Sie ist kurz genug, um sie im laufenden Meeting mit einem Blick zu erfassen.
- Sie ist als KI-erzeugt gekennzeichnet und wird nicht Teil der Quelle fürs Wiki (Leitplanke 6).

## 7. Übergreifende Anforderungen

- **Markierungsarten:** Mindestens Widerspruch, offener Punkt und Frage müssen unterscheidbar sein. Die Arten sollen erweiterbar sein, ohne bestehende Markierungen umzubauen.
- **Nachvollziehbarkeit:** Zu jeder Markierung ist erkennbar, auf welche Stelle im Transkript und auf welche Stelle im Wiki sie sich bezieht.
- **Wenig Störung:** Der Moderator leitet ein Meeting. Hinweise müssen knapp sein und dürfen ihn nicht überfluten. Lieber wenige belastbare Hinweise als viele unsichere.
- **Geschwindigkeit:** Ein Hinweis nützt nur, solange das Thema noch im Raum ist. Miss die Verzögerung von der Aussage bis zum Hinweis und weise sie aus. Einen festen Grenzwert gibt es noch nicht (Abschnitt 9).
- **Robust gegen Transkriptfehler:** Das Transkript stammt aus automatischer Spracherkennung. Verstümmelte Fachbegriffe dürfen nicht reihenweise falsche Widersprüche auslösen. Es existiert ein Glossar bestätigter Fehlerkennungen, nutze es, wenn es erreichbar ist.
- **Datenschutz:** Rollen statt Personen. Der Souffleur legt keine zusätzlichen personenbezogenen Daten an. Audio- und Videorohdaten werden durch ihn nicht dauerhaft gespeichert.
- **KI-Dienst austauschbar:** Welches Sprachmodell verwendet wird, ist nicht entschieden und unterliegt einer Security-Freigabe. Das Modell muss per Konfiguration wechselbar sein. In Oberfläche und Ausgaben heißt es neutral "KI", ohne Produktnamen.
- **Ohne Wiki lauffähig:** Ist kein Wiki verknüpft, das Wiki nicht erreichbar oder leer, läuft Audioscribe normal weiter. Der Souffleur meldet den Zustand, statt abzubrechen (siehe K1).
- **Erweiterbar für Stufe 2:** Der spätere Lösungsknopf (B3) soll sich ergänzen lassen, ohne den Abgleich umzubauen.

## 8. Vorgehen und Abnahme

**Vorgehen**

1. Sieh dir zuerst den bestehenden Code an: Wie entsteht das Live-Transkript, wo liegen die Zeitstempel, wie sieht die Oberfläche des Moderators aus, wie sind die Einstellungen heute aufgebaut.
2. Lege einen kurzen Umsetzungsplan vor, mit deinen Vorschlägen zu den offenen Entscheidungen aus Abschnitt 9. Warte auf Bestätigung, bevor du baust.
3. Setze in kleinen Schritten um. Vorschlag für die Reihenfolge: C1 (kommt ohne Wiki aus), dann B1, dann K1 (Wiki verknüpfen), dann A1 bis A3 mit B2, zuletzt A4.

**Testbarkeit**

- Der Souffleur muss sich **ohne Live-Audio** testen lassen: Ein gespeichertes Transkript wird mit seinen Zeitstempeln abgespielt, als käme es live.
- Lege ein kleines Test-Wiki und ein Test-Transkript an, in dem Widersprüche, offene Punkte, echte und rhetorische Fragen bewusst enthalten sind.
- Das Test-Wiki wird über die Einstellung aus K1 verknüpft, nicht über einen Sonderweg im Testcode.

**Fertig ist die Stufe, wenn**

- alle acht Features gegen das Testmaterial das beschriebene Verhalten zeigen,
- keine Leitplanke aus Abschnitt 4 verletzt wird (insbesondere: kein Schreibzugriff aufs Wiki, Transkripttext unverändert),
- das Wiki allein über die Einstellungen verknüpft und gewechselt werden kann,
- die Verzögerung je Hinweis gemessen und dokumentiert ist,
- kurz beschrieben ist, wie man den Souffleur startet, konfiguriert und testet.

## 9. Offene Entscheidungen

Nicht selbst festlegen. Vorschlag machen und bestätigen lassen.

1. **Form des Wikis:** Wo es liegt, legt die Pfadangabe in den Einstellungen fest (K1). Offen bleibt, in welcher Form es dort liegt und wie gelesen wird. **Annahme:** eine Sammlung von Textdateien im Karpathy-Stil. Nicht bestätigt.
2. **Ablage der Markierungen:** Im Transkript selbst oder in einer Begleitdatei daneben? Leitplanke 4 muss in beiden Fällen gelten.
3. **Übergabeformat und Übergabeort für A4:** Muss mit dem Verantwortlichen für Wiki und Lint abgestimmt werden, damit der Lint die Markierungen verarbeiten kann. Dazu gehört, wohin die neue Quelle gelegt wird.
4. **Rückkanal:** Erfahren wir, was der Lint aus einer Markierung gemacht hat? Derzeit nicht vorgesehen.
5. **Zielhardware und Grenzwert für die Verzögerung:** Die Live-Transkription ist je nach Rechner sehr unterschiedlich schnell (von rund 1 Sekunde bis rund 40 Sekunden). Der Zielrechner steht noch nicht fest.
6. **KI-Dienst:** Welches Modell darf verwendet werden? Abhängig von der Security-Abstimmung. Seit 2026-10 steht als Kandidat ein lokales Modell über Ollama bereit (KI-Dienst „ollama“, per Konfiguration und je Projekt wählbar): nichts verlässt den Rechner, keine Anmeldung bei einem Anbieter nötig.
7. **Ablage der Zusammenfassungen:** Werden abgerufene Zusammenfassungen aufbewahrt, und wenn ja, wo, getrennt vom Rohtranskript?
8. **Wiki-Stand:** Gegen welchen Stand wird abgeglichen, wenn sich das Wiki während eines Meetings ändert?
