---
name: wiki-ingest
description: Arbeitet neue Rohquellen (Workshop-Transkripte, Bilder) aus raw/ in ein LLM-Wiki nach Karpathy-Muster ein. Nutzen bei 'ingest', 'arbeite die Quelle ein', 'neues Transkript ins Wiki' oder wenn ein Wiki neu angelegt werden soll.
---

# Wiki-Ingest

Arbeitet Rohquellen in ein LLM-Wiki ein. Das Wiki ist ein Ordner mit `CLAUDE.md` (Schema), `raw/` (Rohquellen) und `wiki/` (Seiten).

## Vorbereitung

1. Bestimme den Wurzelordner des Wikis: der Ordner, in dem `CLAUDE.md` und `raw/` liegen. Nennt der Nutzer keinen Pfad, nimm das aktuelle Arbeitsverzeichnis. Ist dort kein Wiki, frag nach dem Pfad.
2. Lies `CLAUDE.md` vollständig. Sie ist verbindlich und geht diesem Skill vor, wenn beide voneinander abweichen. Fehlt sie, brich ab und sag das.
3. Fehlt `wiki/` oder ist es leer, lege die Struktur an, die `CLAUDE.md` in Abschnitt 2 beschreibt, samt `index.md`, `log.md`, `uebersicht.md` und `glossar.md` als leere Startseiten. Sag dem Nutzer, dass du das Wiki neu angelegt hast.

## Welche Quellen

- Nennt der Nutzer eine Rohquelle, arbeite genau diese ein.
- Sonst ermittle die neuen Quellen: jeder Eintrag direkt unter `raw/` (Ordner oder Datei), zu dem es in `wiki/quellen/` keine Seite mit `rohquelle: raw/<name>` im Frontmatter gibt.
- Gibt es keine neue Quelle, sag das und hör auf.
- Mehrere neue Quellen arbeitest du nacheinander ein, in der Reihenfolge der Namen, jede vollständig, bevor die nächste beginnt. Eine Quelle ist ein Ordner als Ganzes, nicht jede Datei einzeln.

## Ablauf je Quelle

Führe den Arbeitsablauf INGEST aus `CLAUDE.md` aus. Achte dabei besonders auf:

- Lies alle Dateien der Quelle, Bilder eingeschlossen.
- Lies vor dem Schreiben `wiki/index.md`, `wiki/glossar.md` und die Seiten, die berührt sein können. Prüfe auf Duplikate, bevor du eine Seite neu anlegst.
- Trage im Frontmatter der Quellenseite `rohquelle: raw/<name>` exakt so ein. Daran wird erkannt, dass die Quelle eingearbeitet ist.
- Jede Aussage trägt einen Beleg mit Quelle und Zeitstempel.
- Widerspricht die Quelle dem Bestand: beide Aussagen stehen lassen, Widerspruchsseite anlegen, betroffene Anforderungen auf `strittig` setzen. Entscheide nie selbst, wer recht hat.
- Neue Anforderungen starten als `entwurf`.
- Keine Personennamen, nur Rollen.
- Pflege zum Schluss Querverweise in beide Richtungen, Glossar, Index, Übersicht und Log.

## Grenzen

- Schreibe ausschließlich unter `wiki/`. In `raw/` und an `CLAUDE.md` änderst du nichts, auch nicht zum Aufräumen oder Umbenennen.
- Erfinde nichts. Was die Quelle nicht hergibt, steht als `nicht erhoben` im Wiki oder wird ein offener Punkt.

## Abschluss

Prüfe je Quelle, dass die Quellenseite existiert und im Index steht. Gib dann den Abschlussbericht aus `CLAUDE.md`: neue Seiten, geänderte Seiten, neue Widersprüche, neue offene Punkte, Rückfragen für den nächsten Workshop.
