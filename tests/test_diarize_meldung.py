"""Meldungen bei fehlgeschlagenem Laden des Diarisierungsmodells - ohne pyannote."""

from audioscribe.pipeline.diarize import _ladefehler_meldung


def test_unpruefbar_behauptet_keinen_gueltigen_token():
    """Offline/Proxy: nicht zum erneuten Akzeptieren der Bedingungen schicken."""
    text = _ladefehler_meldung("UNPRUEFBAR", "Token nicht pruefbar (ConnectionError)")
    assert "nicht erreichbar" in text
    assert "ConnectionError" in text
    assert "gueltig" not in text
    assert "akzeptiert" not in text


def test_gueltiger_token_verweist_auf_die_bedingungen():
    text = _ladefehler_meldung("OK", "Token gueltig", "\n(Ursache: X)")
    assert "Modell-Bedingungen" in text
    assert "segmentation-3.0" in text
    assert text.endswith("(Ursache: X)")


def test_ungueltiger_token_verweist_auf_neuen_token():
    text = _ladefehler_meldung("UNGUELTIG", "Token abgelehnt (401)")
    assert "Token abgelehnt (401)" in text
    assert "Neuen Token erstellen" in text
