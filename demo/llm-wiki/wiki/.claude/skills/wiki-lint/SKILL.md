---
name: wiki-lint
description: Prüft ein LLM-Wiki (Ordner mit CLAUDE.md, raw/, wiki/) auf Widersprüche, Unbelegtes, kaputte Verweise, Lücken und Anforderungsqualität und schreibt einen Prüfbericht mit Fragenkatalog. Nutzen bei 'lint', 'prüf das Wiki', 'Wiki-Status' oder 'Gesundheitscheck fürs Wiki'.
---

# Wiki-Lint

Prüft den Zustand eines LLM-Wikis. Das Wiki ist ein Ordner mit `CLAUDE.md` (Schema), `raw/` (Rohquellen) und `wiki/` (Seiten).

## Vorbereitung

1. Bestimme den Wurzelordner des Wikis: der Ordner mit `CLAUDE.md` und `wiki/`. Nennt der Nutzer keinen Pfad, nimm das aktuelle Arbeitsverzeichnis. Ist dort kein Wiki, frag nach dem Pfad.
2. Lies `CLAUDE.md` vollständig. Sie ist verbindlich und geht diesem Skill vor, wenn beide voneinander abweichen.

## Drei Stufen

Wähle die Stufe nach dem, was der Nutzer verlangt:

- **Status** ("Status", "was ist neu", "kurzer Check"): nur die Strukturprüfung unten, Ergebnis im Chat, nichts schreiben.
- **Lint** (Standard): Strukturprüfung plus inhaltliche Prüfung, Bericht nach `wiki/lint/lint-<JJJJ-MM-TT>.md`, Eintrag in `wiki/log.md`. Sonst nichts ändern.
- **Lint mit Korrektur** (nur auf ausdrücklichen Auftrag, z. B. "und behebe", "fix"): zusätzlich beheben, was unter Korrektur steht.

## Strukturprüfung

Prüfe mechanisch über alle Seiten unter `wiki/` außer `wiki/lint/`. Liegt im Wurzelordner `wiki.py`, kannst du stattdessen `python3 wiki.py status` ausführen und das Ergebnis übernehmen.

- Kaputte Verweise: `[[ziel]]`, zu dem es keine Datei `ziel.md` gibt.
- Waisen: Seiten ohne eingehenden Verweis von einer anderen Inhaltsseite (Index und Log zählen nicht).
- Seiten, die in `wiki/index.md` fehlen, und Indexeinträge ohne Seite.
- Fehlendes oder fehlerhaftes Frontmatter, doppelt vergebene IDs, Dateiname passt nicht zur ID.
- Fehlende Rückverweise.
- Rohquellen unter `raw/` ohne Quellenseite mit passendem `rohquelle:`-Eintrag.

## Inhaltliche Prüfung

Lies dafür alle Seiten, nicht nur den Index. Prüfe die Punkte aus dem Arbeitsablauf LINT in `CLAUDE.md`:

- Widersprüche zwischen Seiten, die noch keine Widerspruchsseite haben.
- Überholte Aussagen, die nicht als überholt markiert sind.
- Aussagen ohne Beleg. Prüfe zusätzlich eine Stichprobe von Belegen gegen die Rohquelle: Steht das dort wirklich, am genannten Zeitstempel? Nenne im Bericht, wie viele Belege du geprüft hast.
- Mehrfach genannte Systeme, Rollen, Begriffe oder Prozesse ohne eigene Seite.
- Anforderungen: Duplikate, Konflikte untereinander, vage Formulierungen ohne offenen Punkt, Status `bestätigt` ohne ausdrückliche Bestätigung, fehlender Prozessbezug. Prozesse ohne Anforderungen.
- Lücken: Prozesse mit `nicht erhoben` bei Auslöser, Turnus, Rollen oder Systemen.
- Personennamen im Wiki.

## Bericht

Gliedere nach Schwere: zuerst, was die Aussagekraft des Wikis gefährdet (Widersprüche, Unbelegtes, falsche Belege), dann Struktur, dann Lücken. Jeder Befund nennt die Seite und die Stelle. Schließe mit einem Fragenkatalog für den nächsten Workshop, geordnet nach der Rolle, die antworten kann. Der Bericht ist als KI-erzeugt gekennzeichnet.

Gib im Chat eine Kurzfassung: Zahl der Befunde je Gruppe, die drei wichtigsten, Pfad zum Bericht.

## Korrektur

Nur mit ausdrücklichem Auftrag, und nur das:

- Strukturfehler beheben: Verweise, Rückverweise, Index, Frontmatter.
- Fehlende Widerspruchs- und Offene-Punkte-Seiten anlegen.

Nie: inhaltliche Widersprüche entscheiden, Aussagen löschen, Status auf `bestätigt` setzen, in `raw/` oder an `CLAUDE.md` schreiben. Liste im Bericht auf, was du geändert hast.
