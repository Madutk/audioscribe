"""Nachgelagerte Review-/Bild-Annotations-Schicht (PRD §13).

Konsumiert die Ausgaben der Transkriptions-Pipeline (``transcript.json``, Originalvideo)
und reichert das Transkript um markierte Standbilder an. Bewusst entkoppelt von der
Batch-Pipeline; der FastAPI-Webserver liegt in der optionalen Extra-Gruppe ``review``.
"""
