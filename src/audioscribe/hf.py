"""Hugging-Face-Zugang pruefen: Token gueltig? Modell-Bedingungen akzeptiert?

Zwei voellig verschiedene Ursachen fuehren beim Diarisierungsmodell zum selben Symptom
("Could not download 'pyannote/speaker-diarization-3.1' pipeline"): ein **ungueltiger
Token** oder **nicht akzeptierte Modell-Bedingungen**. Hugging Face behandelt einen
abgelehnten Token wie einen anonymen Zugriff, weshalb gesperrte Repos dann ebenfalls als
"gated" zurueckkommen - wer beides verwechselt, klickt auf der Modellseite endlos "Agree",
waehrend in Wahrheit der Token widerrufen ist.

Alle Pruefungen hier laufen ohne Download.
"""

from __future__ import annotations

from typing import Literal

from audioscribe.i18n import tr

TokenStatus = Literal["OK", "FEHLT", "UNGUELTIG", "UNPRUEFBAR"]

TOKENS_URL = "https://huggingface.co/settings/tokens"


def ist_ungueltiger_token(exc: BaseException) -> bool:
    """Erkennt die Absage von Hugging Face wegen eines nicht akzeptierten Tokens (HTTP 401)."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status == 401:
        return True
    text = str(exc).lower()
    return "invalid user token" in text or "invalid token" in text


def token_status(token: str | None) -> tuple[TokenStatus, str]:
    """Prueft den Token gegen ``whoami`` und liefert ``(Status, Detail)``.

    ``UNPRUEFBAR`` heisst: kein Netz oder ``huggingface_hub`` fehlt - das darf nie als
    Fehler des Nutzers dargestellt werden.
    """
    if not token or not token.strip():
        return "FEHLT", tr("HF_TOKEN fehlt (siehe .env.example)")

    try:
        from huggingface_hub import HfApi
    except Exception as exc:  # noqa: BLE001
        return "UNPRUEFBAR", tr("huggingface_hub nicht nutzbar ({fehler})", fehler=type(exc).__name__)

    try:
        konto = HfApi(token=token).whoami()
    except Exception as exc:  # noqa: BLE001
        if ist_ungueltiger_token(exc):
            return (
                "UNGUELTIG",
                tr(
                    "HF_TOKEN wird abgelehnt (widerrufen, abgelaufen oder unvollstaendig kopiert) "
                    "-> neuen Token erstellen: {url}",
                    url=TOKENS_URL,
                ),
            )
        return "UNPRUEFBAR", tr("Token nicht pruefbar ({fehler})", fehler=type(exc).__name__)

    name = konto.get("name") if isinstance(konto, dict) else None
    return "OK", tr("gueltig (Konto: {name})", name=name or "?")
