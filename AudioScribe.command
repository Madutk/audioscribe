#!/bin/bash
# Doppelklick im Finder oeffnet Terminal.app und startet AudioScribe (macOS).
# Die Berechtigungen fuer Mikrofon und Bildschirmaufnahme gehoeren dann Terminal.app.
cd "$(dirname "$0")" && exec ./start.sh "$@"
