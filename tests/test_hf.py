"""Hugging-Face-Token: ungueltiger Token darf nicht als 'Bedingungen fehlen' erscheinen."""

import pytest

from audioscribe import hf


class _Antwort:
    def __init__(self, status_code):
        self.status_code = status_code


class _HttpFehler(Exception):
    def __init__(self, text, status_code=None):
        super().__init__(text)
        self.response = _Antwort(status_code) if status_code else None


def test_ungueltiger_token_an_http_401_erkannt():
    assert hf.ist_ungueltiger_token(_HttpFehler("irgendwas", status_code=401))


def test_ungueltiger_token_an_meldung_erkannt():
    # huggingface_hub haengt nicht immer eine Response an - der Text traegt die Aussage.
    assert hf.ist_ungueltiger_token(Exception("Invalid user token. The token from HF_TOKEN ..."))


def test_netzwerkfehler_ist_kein_ungueltiger_token():
    assert not hf.ist_ungueltiger_token(_HttpFehler("Connection timed out", status_code=504))
    assert not hf.ist_ungueltiger_token(OSError("Name oder Dienst nicht bekannt"))


def test_token_status_fehlt():
    assert hf.token_status(None)[0] == "FEHLT"
    assert hf.token_status("   ")[0] == "FEHLT"


@pytest.mark.parametrize(
    ("fehler", "erwartet"),
    [
        (_HttpFehler("Invalid user token.", status_code=401), "UNGUELTIG"),
        (_HttpFehler("Gateway Timeout", status_code=504), "UNPRUEFBAR"),
    ],
)
def test_token_status_klassifiziert_fehler(monkeypatch, fehler, erwartet):
    import huggingface_hub

    class _Api:
        def __init__(self, token=None):
            pass

        def whoami(self):
            raise fehler

    monkeypatch.setattr(huggingface_hub, "HfApi", _Api)
    status, detail = hf.token_status("hf_egal")
    assert status == erwartet
    assert detail


def test_token_status_ok(monkeypatch):
    import huggingface_hub

    class _Api:
        def __init__(self, token=None):
            pass

        def whoami(self):
            return {"name": "marek"}

    monkeypatch.setattr(huggingface_hub, "HfApi", _Api)
    status, detail = hf.token_status("hf_egal")
    assert status == "OK"
    assert "marek" in detail
