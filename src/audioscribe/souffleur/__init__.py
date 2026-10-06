"""Souffleur: Live-Abgleich des Transkripts mit einem LLM-Wiki (PRD §20).

Leitplanken, die dieses Paket einhält (Anforderungen Abschnitt 4):

- Das Wiki wird **nur gelesen** (``wiki.py`` öffnet Dateien ausschließlich zum Lesen).
- Der **Wortlaut des Transkripts bleibt unverändert**: Dieses Paket schreibt nie in
  ``transkript.md``, ``transcript.json`` oder ``transkript.annotiert.md``, sondern nur in
  die Begleitdateien aus ``SOUFFLEUR_DATEIEN``. Die Ablage ins Wiki (``raw/``) übernimmt
  ``projekt/wiki_ablage.py`` - dieses Paket liefert dafür nur die Inhalte (``uebergabe.py``).
- **Belegtes und KI-Erzeugtes bleiben getrennt**: Fundstellen tragen Datei, Überschrift
  und Zeile; alles, was die KI formuliert, steht in Feldern mit ``ki_``-Präfix oder ist als
  ``ki_erzeugt`` gekennzeichnet.
- **Kein Hinweis ohne Grundlage**: Ein Widerspruch ohne wörtliches Wiki-Zitat wird
  verworfen; eine Frage ohne Fundstelle meldet ausdrücklich ``ohne_befund``.
- Der Wiki-Pfad wird an genau einer Stelle gelesen: ``konfig.lade_konfig``.
"""

from __future__ import annotations

# Die einzigen Dateien, die der Souffleur im Sitzungsordner anlegt (Begleitdateien, Sidecar).
SOUFFLEUR_DATEIEN: tuple[str, ...] = (
    "souffleur.json",
    "souffleur-protokoll.md",
    "souffleur-diagnose.jsonl",
    "souffleur-essenz.jsonl",
)
