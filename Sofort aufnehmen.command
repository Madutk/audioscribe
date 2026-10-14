#!/bin/bash
# Doppelklick im Finder: AudioScribe starten und sofort aufnehmen (ohne Projekt, mit den
# zuletzt benutzten Geraeten). Laeuft AudioScribe schon, startet nur die Aufnahme.
# Fuer den Schreibtisch: Rechtsklick > "Alias erzeugen" und den Alias dorthin ziehen.
cd "$(dirname "$0")" && exec ./start.sh --aufnahme "$@"
