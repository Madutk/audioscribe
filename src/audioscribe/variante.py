"""Programmvariante: ``standard`` oder ``cloud-compliant`` (ohne Cloud-KI).

Die Variante ist bewusst eine Konstante im Code und weder über die Umgebung noch über
Einstellungsdateien oder die Kommandozeile umstellbar: Der Branch ``cloud-compliant`` ändert
nur die eine Zeile unten. Alle Stellen, die sich je Variante unterscheiden, fragen ``aktiv()``.

In ``cloud-compliant`` gilt:
- KI-Dienst ist ausschließlich die lokale KI (Ollama) - Claude (Agent SDK / Claude Code) wird
  weder gewählt noch geladen;
- die KI-Analyse (``audioscribe analyze``, ``/api/agent/*``, Reiter in der Oberfläche) entfällt;
- die Ollama-Adresse muss auf diesen Rechner zeigen.

Das Modul hängt nur von der Standardbibliothek ab - die Startskripte lesen die Zeile per grep.
"""

from __future__ import annotations

from urllib.parse import urlsplit

STANDARD = "standard"
CLOUD_COMPLIANT = "cloud-compliant"

# Der Branch cloud-compliant setzt hier ``VARIANTE = CLOUD_COMPLIANT`` (start.sh/start.ps1 suchen
# genau diese Zeile).
VARIANTE = STANDARD

DIENST_LOKAL = "ollama"
# Zulässig in cloud-compliant: die lokale KI und die regelbasierte Attrappe der Tests (ohne Netz,
# in der Oberfläche nicht angeboten).
DIENSTE_LOKAL = frozenset({DIENST_LOKAL, "attrappe"})
HINWEIS_DIENST = "In der Variante cloud-compliant ist nur die lokale KI (Ollama) zulässig."
HINWEIS_ANALYSE = "Die KI-Analyse ist in der Variante cloud-compliant nicht verfügbar."
LOKALE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def aktiv() -> bool:
    """Läuft die Variante ``cloud-compliant``?"""
    return VARIANTE == CLOUD_COMPLIANT


def dienst_zulaessig(dienst: str | None) -> bool:
    return not aktiv() or (dienst or "").strip().lower() in DIENSTE_LOKAL


def hinweis_analyse() -> str:
    """``HINWEIS_ANALYSE`` in der Sprache der Oberfläche."""
    from audioscribe.i18n import tr  # erst hier: das Modul selbst bleibt bei der Standardbibliothek

    return tr("Die KI-Analyse ist in der Variante cloud-compliant nicht verfügbar.")


def pruefe_dienst(dienst: str | None) -> str | None:
    """Hinweistext, wenn der KI-Dienst in dieser Variante nicht zulässig ist - sonst ``None``.
    Deutsch enthält er ``HINWEIS_DIENST`` wörtlich."""
    if dienst_zulaessig(dienst):
        return None
    from audioscribe.i18n import tr

    return tr(
        "KI-Dienst '{dienst}' abgelehnt. In der Variante cloud-compliant ist nur die lokale KI (Ollama) zulässig.",
        dienst=dienst,
    )


def pruefe_ollama_url(url: str) -> str | None:
    """Hinweistext, wenn die Ollama-Adresse nicht auf diesen Rechner zeigt (nur in
    ``cloud-compliant`` geprüft) - sonst ``None``."""
    if not aktiv():
        return None
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        host = ""
    if host in LOKALE_HOSTS:
        return None
    from audioscribe.i18n import tr

    return tr(
        "Ollama-Adresse {url} nicht zulässig - in der Variante cloud-compliant nur localhost, 127.0.0.1 oder ::1.",
        url=url,
    )
