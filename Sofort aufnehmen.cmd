@echo off
rem Doppelklick: AudioScribe starten und sofort aufnehmen (ohne Projekt, mit den zuletzt
rem benutzten Geraeten). Laeuft AudioScribe schon, startet nur die Aufnahme.
rem Fuer den Desktop: Rechtsklick > "Senden an" > "Desktop (Verknuepfung erstellen)".
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" -Aufnahme %*
