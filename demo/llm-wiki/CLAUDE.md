# CLAUDE.md: LLM-Wiki der Domäne Assistenz

Dieses Dokument ist das Schema des Wikis. Es legt fest, wie das Wiki aufgebaut ist und wie du es pflegst. Lies es vor jeder Arbeit vollständig. Ändere es nie selbst; Vorschläge zur Änderung gehören in den Abschlussbericht.

## 1. Zweck

Das Wiki ist die Wissensbasis für die **Anforderungsanalyse in der Domäne Assistenz**. Es bündelt alles, was in Prozessaufnahmen und Anforderungsworkshops gesagt und gezeigt wurde: Prozesse, Anforderungen, Systeme, Rollen, Begriffe, Entscheidungen, offene Punkte und Widersprüche.

Der Mensch liefert Quellen und stellt Fragen. Du übernimmst die Pflege: zusammenfassen, einsortieren, verknüpfen, abgleichen, Buch führen. Ein Wiki bildet genau eine Domäne ab.

Das Wiki wird auch von anderen Werkzeugen **nur gelesen** (z. B. für den Live-Abgleich in Meetings). Deshalb müssen Aussagen einzeln auffindbar und belegt sein.

## 2. Drei Schichten

```
CLAUDE.md            Schema (dieses Dokument). Nicht ändern.
raw/                 Rohquellen. Unveränderlich. Nur lesen.
  <JJJJ-MM-TT>_<kurzname>/    ein Ordner je Workshop oder Aufnahme:
                              Transkript, Bilder, ggf. Begleitdatei mit Markierungen
wiki/                Das Wiki. Nur hier schreibst du.
  index.md           Katalog aller Seiten
  log.md             Chronik, nur anhängend
  uebersicht.md      Lagebild der Domäne
  glossar.md         Begriffe und bestätigte Fehlerkennungen
  quellen/           Q-nnn    eine Seite je Rohquelle
  prozesse/          PRO-nnn
  anforderungen/     ANF-nnn
  systeme/           SYS-nnn  Systemkatalog
  rollen/            ROL-nnn
  entscheidungen/    ENT-nnn
  offene-punkte/     OP-nnn
  widersprueche/     WID-nnn
  analysen/          AN-nnn   abgelegte Antworten auf Fragen
  lint/              Prüfberichte
```

## 3. Eiserne Regeln

1. **Rohquellen sind unveränderlich.** In `raw/` wird nie geschrieben, umbenannt oder gelöscht.
2. **Nichts erfinden.** Ins Wiki kommt nur, was eine Quelle hergibt. Kein eigenes Weltwissen über die Domäne, auch wenn es plausibel wäre.
3. **Jede Aussage trägt einen Beleg** (Abschnitt 5). Logische Ergänzungen sind erlaubt, wenn sie mit `⚠️ erschlossen` markiert und kurz begründet sind.
4. **Widersprüche werden gemeldet, nicht entschieden.** Widerspricht eine neue Quelle dem Wiki, bleiben beide Aussagen mit Beleg stehen, und es entsteht eine WID-Seite. Wer recht hat, entscheidet der Mensch.
5. **Nichts stillschweigend überschreiben.** Überholte Aussagen werden nicht gelöscht, sondern als überholt markiert, mit Verweis auf die Quelle, die sie abgelöst hat.
6. **Rollen statt Personen.** Im Wiki stehen keine Namen von Personen, auch wenn sie im Transkript vorkommen. Schreibe "Assistenz", "Führungskraft", "Reisestelle". Ausnahme: Namen von Systemen, Produkten und Organisationseinheiten.
7. **Belegtes und KI-Erzeugtes bleiben getrennt.** Analysen, Einschätzungen und Zusammenfassungen von dir stehen nur in `analysen/`, `lint/` und `uebersicht.md` und sind dort als KI-erzeugt gekennzeichnet. Sie sind nie Beleg für eine Wissensseite.
8. **Sprache:** Deutsch, sachlich, knapp.

## 4. Seiten

### Dateinamen, IDs, Verweise

- Dateiname: `<ID>-<kurzer-slug>.md`, z. B. `ANF-012-buchung-ohne-rueckfrage.md`. Kleinbuchstaben, Bindestriche, keine Umlaute im Slug.
- IDs sind dreistellig fortlaufend je Typ und werden nie neu vergeben. Die nächste freie Nummer ergibt sich aus `index.md`.
- Verweise als Wikilink auf den Dateinamen ohne Endung: `[[ANF-012-buchung-ohne-rueckfrage|ANF-012]]`.
- Jede Seite verweist auf die Seiten, mit denen sie fachlich zusammenhängt (Prozess ↔ Anforderung ↔ System ↔ Rolle). Verweise immer in beide Richtungen pflegen.

### Frontmatter (alle Seiten außer index, log, lint)

```yaml
---
id: ANF-012
typ: anforderung          # quelle | prozess | anforderung | system | rolle | entscheidung | offener-punkt | widerspruch | analyse
titel: Buchung ohne Rückfrage bis Betragsgrenze
status: entwurf           # je Typ, siehe unten
quellen: [Q-003, Q-005]
aktualisiert: 2026-10-06
---
```

### Seitentypen

**Quelle (Q)**, zusätzlich im Frontmatter: `rohquelle: raw/<ordner-oder-datei>`, `datum`, `art` (workshop | prozessaufnahme | dokument | bild | sonstiges). Inhalt: beteiligte Rollen, Zusammenfassung in fünf bis zehn Sätzen, Kernaussagen als Liste mit Zeitstempel, Liste der Bilder mit je einem Satz Inhalt, berührte Wiki-Seiten.

**Prozess (PRO)**, Status `skizze | aufgenommen | bestätigt`. Feste Abschnitte: Zweck, Auslöser, Turnus, Rollen, Systeme, Ablauf (nummerierte Schritte), Entscheidungen im Ablauf, Varianten und Sonderfälle, Schmerzpunkte, abgeleitete Anforderungen, offene Punkte. Fehlt eine Angabe in den Quellen, steht dort `nicht erhoben`, nicht eine Vermutung.

**Anforderung (ANF)**, Status `entwurf | bestätigt | strittig | überholt`. Zusätzlich im Frontmatter: `art` (funktional | nicht-funktional | randbedingung), `prioritaet` (muss | soll | kann | unbekannt). Inhalt: die Anforderung in einem Satz, Begründung, betroffene Prozesse, Systeme und Rollen, Abnahmekriterium. Regeln:

- Eine Anforderung je Seite.
- Neue Anforderungen starten immer als `entwurf`. Dass jemand etwas im Workshop sagt oder den Ist-Zustand beschreibt, ist keine Bestätigung. `bestätigt` nur, wenn der Fachbereich eine bereits formulierte Anforderung in einer späteren Quelle ausdrücklich bestätigt oder der Mensch den Status setzt.
- Priorität und Abnahmekriterium nur, wenn genannt. Sonst `unbekannt` bzw. `nicht erhoben`.
- Vage Formulierungen ("schnell", "einfach", "möglichst") wörtlich übernehmen und einen offenen Punkt zur Präzisierung anlegen.
- Vor dem Anlegen auf Duplikate prüfen. Gleiche Anforderung aus neuer Quelle: bestehende Seite ergänzen, Quelle nachtragen.

**System (SYS)**, Status `genannt | beschrieben`. Inhalt: exakter Name, Zweck in der Domäne, wer es nutzt, in welchen Prozessen, Schnittstellen und Medienbrüche, bekannte Einschränkungen.

**Rolle (ROL)**: Aufgaben in der Domäne, beteiligte Prozesse, genutzte Systeme, Befugnisse und Grenzen.

**Entscheidung (ENT)**: was entschieden wurde, wann, durch welche Rolle, Begründung, Auswirkungen.

**Offener Punkt (OP)**, Status `offen | geklärt`. Inhalt: die Frage, warum sie offen ist, welche Rolle sie beantworten kann, betroffene Seiten. Bei Klärung: Antwort mit Beleg eintragen, Status ändern, Seite behalten.

**Widerspruch (WID)**, Status `offen | entschieden`. Inhalt: Aussage A mit Beleg, Aussage B mit Beleg, betroffene Seiten, mögliche Erklärung (als `⚠️ erschlossen`). Entscheidung trägt nur der Mensch ein oder eine Quelle, die den Punkt ausdrücklich klärt.

**Analyse (AN)**: abgelegte Antwort auf eine Frage. Erste Zeile nach dem Frontmatter: `> KI-erzeugt am <Datum> auf Basis des Wiki-Stands.`

### glossar.md

Eine Tabelle: Begriff, Bedeutung in der Domäne, Synonyme, Fehlerkennungen (wie die Spracherkennung den Begriff verstümmelt), Beleg. Neue vermutete Fehlerkennungen mit `⚠️ unsicher` eintragen, bis sie bestätigt sind.

## 5. Belege

- Form: `[Q-003 · 00:14:32]` für Transkriptstellen, `[Q-003 · bild-02.png]` für Bilder, `[Q-003]` wenn kein genauerer Anker existiert.
- Der Beleg steht am Ende der Aussage, eine Aussage je Listenpunkt oder Satz. So bleibt jede Aussage einzeln auffindbar.
- Bilder schlagen Transkript bei Fakten (Systemname, Feldbezeichnung, Maske). Transkript schlägt Bilder bei Absicht und Begründung.
- Transkripte stammen aus automatischer Spracherkennung. Korrigiere verstümmelte Begriffe anhand von `glossar.md` und der Bilder. Im Zweifel den Wortlaut der Quelle zitieren und `⚠️ unsicher` setzen.
- Überholte Aussage: `~~alte Aussage~~ [Q-002 · 00:03:10] (überholt durch [Q-005 · 00:21:40])`.

## 6. Arbeitsabläufe

### INGEST: eine Rohquelle einarbeiten

Immer genau eine Rohquelle je Lauf.

1. Lies alle Dateien der Rohquelle, Bilder eingeschlossen. Liegt eine Begleitdatei mit Markierungen bei (Widerspruch, offener Punkt, Frage), sind das Hinweise, denen du nachgehst. Sie sind keine Fakten.
2. Lies `wiki/index.md` und `wiki/glossar.md`, danach die Seiten, die von der Quelle berührt sein können.
3. Lege die Quellenseite an (nächste freie Q-Nummer) mit `rohquelle:` im Frontmatter.
4. Ziehe aus der Quelle: Prozesse, Anforderungen, Systeme, Rollen, Begriffe, Entscheidungen, offene Punkte. Je Fund: bestehende Seite ergänzen oder neue Seite anlegen. Beleg an jede Aussage.
5. Gleiche jede neue Aussage mit dem Bestand ab. Bei Abweichung: Regel 4 und 5 aus Abschnitt 3, WID-Seite anlegen, betroffene Anforderungen auf `strittig` setzen.
6. Prüfe, ob die Quelle bestehende offene Punkte oder Widersprüche klärt, und trage das dort ein.
7. Pflege Querverweise in beide Richtungen, `glossar.md`, `index.md` und bei wesentlichen Änderungen `uebersicht.md`.
8. Hänge einen Eintrag an `log.md` an.
9. Abschlussbericht im Chat: neue Seiten, geänderte Seiten, neue Widersprüche, neue offene Punkte, Rückfragen für den nächsten Workshop.

Smalltalk, Organisatorisches und Abschweifungen werden nicht aufgenommen.

### QUERY: eine Frage beantworten

1. Lies `wiki/index.md`, dann die passenden Seiten. Rohquellen nur, wenn eine Wiki-Seite nicht reicht, um einen Beleg zu prüfen.
2. Antworte nur aus dem Wiki. Jede Aussage mit Fundstelle: Seite und Beleg, z. B. `ANF-012 [Q-003 · 00:14:32]`.
3. Steht im Wiki nichts dazu, sag genau das. Fülle die Lücke nicht mit eigenem Wissen. Nenne, welche Rolle die Frage beantworten könnte.
4. Weise auf offene Widersprüche und offene Punkte hin, die die Antwort berühren.
5. Nur wenn ausdrücklich verlangt: Antwort als AN-Seite in `analysen/` ablegen, in `index.md` eintragen, `log.md` ergänzen.

### LINT: das Wiki prüfen

Prüfe und schreibe einen Bericht nach `wiki/lint/lint-<JJJJ-MM-TT>.md`:

1. **Widersprüche** zwischen Seiten, die noch keine WID-Seite haben.
2. **Veraltetes:** Aussagen, die eine neuere Quelle überholt hat, ohne dass es markiert ist.
3. **Unbelegtes:** Aussagen ohne Beleg oder mit Beleg, den die Quellenseite nicht hergibt (Stichprobe gegen `raw/`).
4. **Struktur:** kaputte Verweise, Waisen, Seiten ohne Eintrag in `index.md`, fehlende Rückverweise, fehlendes oder fehlerhaftes Frontmatter, Rohquellen ohne Quellenseite.
5. **Fehlende Seiten:** Systeme, Rollen, Begriffe oder Prozesse, die mehrfach genannt werden, aber keine eigene Seite haben.
6. **Anforderungsqualität:** Duplikate, Konflikte zwischen Anforderungen, vage Formulierungen ohne offenen Punkt, Anforderungen ohne Prozessbezug, Prozesse ohne Anforderungen.
7. **Lücken:** Prozesse mit `nicht erhoben` bei Auslöser, Turnus, Rollen oder Systemen. Personennamen im Wiki (Regel 6).
8. **Fragenkatalog für den nächsten Workshop:** aus offenen Punkten, Widersprüchen und Lücken, geordnet nach der Rolle, die antworten kann.

Ohne Korrekturauftrag schreibst du nur den Bericht und den Log-Eintrag. Mit Korrekturauftrag behebst du zusätzlich Punkt 4 sowie fehlende WID- und OP-Seiten. Inhaltliche Widersprüche entscheidest du nie.

## 7. index.md und log.md

**index.md** listet jede Seite genau einmal, gruppiert nach Typ, je Zeile: Verweis, Titel, Status, ein Satz Inhalt. Am Kopf steht je Typ die höchste vergebene Nummer.

**log.md** wird nur ergänzt, neueste Einträge unten. Format:

```
## [2026-10-06] ingest | Q-003 Workshop Reisebuchung
- neu: ANF-012, ANF-013, SYS-004
- geändert: PRO-002
- Widersprüche: WID-002
- offene Punkte: OP-007
```

Vorgänge: `ingest`, `query`, `lint`.
