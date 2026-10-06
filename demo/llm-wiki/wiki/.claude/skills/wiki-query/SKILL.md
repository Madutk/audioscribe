---
name: wiki-query
description: Beantwortet Fragen ausschließlich aus einem LLM-Wiki (Ordner mit CLAUDE.md, raw/, wiki/) mit Fundstellen und Hinweis auf Widersprüche. Nutzen bei 'frag das Wiki', 'was steht im Wiki zu ...', 'query' oder Fragen zu Anforderungen, Prozessen und Systemen der Wiki-Domäne.
---

# Wiki-Query

Beantwortet eine Frage aus dem Bestand eines LLM-Wikis. Das Wiki ist ein Ordner mit `CLAUDE.md` (Schema), `raw/` (Rohquellen) und `wiki/` (Seiten).

## Vorbereitung

1. Bestimme den Wurzelordner des Wikis: der Ordner mit `CLAUDE.md` und `wiki/`. Nennt der Nutzer keinen Pfad, nimm das aktuelle Arbeitsverzeichnis. Ist dort kein Wiki, frag nach dem Pfad.
2. Lies `CLAUDE.md`. Sie ist verbindlich und geht diesem Skill vor, wenn beide voneinander abweichen.

## Ablauf

Führe den Arbeitsablauf QUERY aus `CLAUDE.md` aus:

1. Lies `wiki/index.md` und wähle die passenden Seiten. Lies sie vollständig. Suche zusätzlich per Volltext nach den Kernbegriffen der Frage und ihren Synonymen aus `wiki/glossar.md`.
2. Rohquellen in `raw/` liest du nur, um einen Beleg zu prüfen, den eine Wiki-Seite nennt. Sie sind kein Ersatz für fehlendes Wiki-Wissen.
3. Antworte nur aus dem Wiki. Jede Aussage trägt ihre Fundstelle: Seite und Beleg, z. B. `ANF-012 [Q-003 · 00:14:32]`.
4. Steht im Wiki nichts zur Frage oder zu einem Teil davon, sag genau das. Fülle die Lücke nicht mit eigenem Wissen. Nenne die Rolle, die antworten könnte.
5. Weise auf offene Widersprüche und offene Punkte hin, die die Antwort berühren. Bei einem offenen Widerspruch nennst du beide Aussagen und legst dich nicht fest.
6. Unterscheide in der Antwort den Status: `bestätigt`, `entwurf`, `strittig`, `überholt`, `⚠️ erschlossen`.

## Schreiben

- Standard: Du schreibst nichts. Die Antwort steht nur im Chat.
- Nur wenn der Nutzer ausdrücklich verlangt, die Antwort abzulegen: Lege eine Analyse-Seite in `wiki/analysen/` an (nächste freie AN-Nummer, Kennzeichnung als KI-erzeugt laut `CLAUDE.md`), trage sie in `wiki/index.md` ein und ergänze `wiki/log.md`. Andere Seiten änderst du dabei nicht.
- Fällt dir beim Lesen ein Fehler im Wiki auf, ändere ihn nicht. Nenne ihn am Ende der Antwort und empfiehl einen Lint-Lauf.
