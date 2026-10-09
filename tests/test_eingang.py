"""Aufnahmen ohne Projekt ("Sofort aufnehmen"): Eingangsordner, Zuordnen, Routen."""

import errno
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from audioscribe.projekt import eingang
from audioscribe.projekt.modell import ProjektFehler
from audioscribe.ui import state
from conftest import _sitzung_in


@pytest.fixture
def eingang_dir(tmp_path):
    return tmp_path / "Ohne Projekt"


@pytest.fixture
def aufnahme(eingang_dir):
    """Beendete Sitzung im Eingangsordner."""
    return _sitzung_in(SimpleNamespace(sitzungen_dir=eingang_dir))


def _status(ordner, **werte):
    (ordner / "sitzung.json").write_text(json.dumps({"sitzung_id": "x", **werte}), encoding="utf-8")


# --- Modell -----------------------------------------------------------------------------------


def test_eingang_dir_folgt_der_einstellung(tmp_path):
    assert eingang.eingang_dir({}) == eingang.standard_dir()
    assert eingang.eingang_dir({"eingang_dir": str(tmp_path)}) == tmp_path


def test_liste_zeigt_nur_beendete_aufnahmen(aufnahme, eingang_dir):
    for name, status in (("live-a", "laeuft"), ("live-b", "verworfen")):
        (eingang_dir / name).mkdir()
        _status(eingang_dir / name, status=status)
    (eingang_dir / "replay").mkdir()
    _status(eingang_dir / "replay", status="beendet", replay=True)
    liste = eingang.liste(eingang_dir)
    assert [s["name"] for s in liste] == [aufnahme.name]
    assert liste[0]["titel"] == "Workshop Reisebuchung"
    assert eingang.liste(eingang_dir / "fehlt") == []


def test_verschieben_in_den_sitzungsordner(aufnahme, projekt):
    alt = aufnahme.resolve()
    ziel = eingang.verschiebe(aufnahme, projekt)
    assert ziel == projekt.sitzungen_dir / aufnahme.name
    assert not aufnahme.exists() and (ziel / "frames" / "0001_00-00-03.jpg").is_file()
    quelle = json.loads((ziel / "transcript.json").read_text(encoding="utf-8"))["source_path"]
    assert not quelle.startswith(str(alt)) and quelle.startswith(str(ziel.resolve()))


def test_verschieben_weicht_namensgleichen_sitzungen_aus(aufnahme, projekt):
    (projekt.sitzungen_dir / aufnahme.name).mkdir(parents=True)
    ziel = eingang.verschiebe(aufnahme, projekt)
    assert ziel.name == f"{aufnahme.name}-2"


@pytest.mark.parametrize("status", ["laeuft", "unterbrochen"])
def test_unfertige_sitzung_bleibt_liegen(aufnahme, projekt, status):
    _status(aufnahme, status=status)
    with pytest.raises(RuntimeError):
        eingang.verschiebe(aufnahme, projekt)
    assert aufnahme.is_dir()


def test_kein_sitzungsordner(tmp_path, projekt):
    (tmp_path / "irgendwas").mkdir()
    with pytest.raises(ProjektFehler):
        eingang.verschiebe(tmp_path / "irgendwas", projekt)


def test_ueber_laufwerke_kopiert_und_raeumt_bei_fehler_auf(aufnahme, projekt, monkeypatch):
    def kein_rename(a, b):
        raise OSError(errno.EXDEV, "anderes Laufwerk")

    monkeypatch.setattr(eingang.os, "rename", kein_rename)
    echt = shutil.copytree

    def halb(src, dst):
        monkeypatch.setattr(eingang.shutil, "copytree", echt)  # shutil ruft sich selbst rekursiv auf
        echt(src, dst)
        raise OSError("Platte voll")

    monkeypatch.setattr(eingang.shutil, "copytree", halb)
    with pytest.raises(OSError):
        eingang.verschiebe(aufnahme, projekt)
    assert aufnahme.is_dir() and not (projekt.sitzungen_dir / aufnahme.name).exists()

    ziel = eingang.verschiebe(aufnahme, projekt)
    assert not aufnahme.exists() and (ziel / "transkript.md").is_file()


# --- Routen -----------------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch, eingang_dir):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from audioscribe.ui import server

    monkeypatch.setattr(state, "state_path", lambda cache_dir=None: tmp_path / "einstellungen.json")
    monkeypatch.setattr(
        "audioscribe.live.kommando.inventory",
        lambda: {"mics": [], "loopbacks": [], "monitors": [], "windows": [], "problems": []},
    )
    c = TestClient(server.create_app())
    assert c.post("/api/state", json={"eingang_dir": str(eingang_dir)}).status_code == 200
    return c


def test_kontext_kennt_aufnahmen_ohne_projekt(client, aufnahme, eingang_dir):
    k = client.post("/api/kontext", json={"modus": "aufnahme"}).json()
    assert k["modus"] == "aufnahme" and k["projekt"] is None
    assert k["eingang_dir"] == str(eingang_dir)
    assert [s["dir"] for s in k["eingang"]] == [str(aufnahme)]


def test_live_start_ohne_projekt_schreibt_in_den_eingang(client, eingang_dir, monkeypatch):
    from audioscribe.ui import runner as runner_modul

    gestartet = {}
    monkeypatch.setattr(runner_modul.LiveRunner, "start", lambda self, opts, **kw: gestartet.update(opts=opts))
    client.post("/api/kontext", json={"modus": "aufnahme"})
    r = client.post("/api/live/start", json={"output_dir": "/woanders", "monitor": 1})
    assert r.status_code == 200, r.text
    assert gestartet["opts"].output_dir == eingang_dir and eingang_dir.is_dir()
    assert client.get("/api/defaults").json()["output_dir"] == str(eingang_dir)


def test_unterbrochene_aufnahme_ohne_projekt(client, aufnahme):
    _status(aufnahme, status="unterbrochen")
    k = client.get("/api/kontext").json()
    assert [(s["dir"], s["projekt"]) for s in k["unterbrochen"]] == [(str(aufnahme), "")]
    # Abschliessen und Fortsetzen gehen nur im Modus "Sofort aufnehmen".
    assert client.post("/api/live/verwerfen", json={"sitzung": str(aufnahme)}).status_code == 409
    client.post("/api/kontext", json={"modus": "aufnahme"})
    assert client.post("/api/live/verwerfen", json={"sitzung": str(aufnahme)}).status_code == 200


def test_zuordnen_verschiebt_und_oeffnet_das_projekt(client, aufnahme, projekt):
    client.post("/api/kontext", json={"modus": "aufnahme"})
    r = client.post("/api/eingang/zuordnen", json={"sitzung": str(aufnahme), "projekt": str(projekt.wurzel)})
    assert r.status_code == 200, r.text
    k = r.json()
    assert k["modus"] == "projekt" and k["projekt"]["wurzel"] == str(projekt.wurzel)
    assert Path(k["ziel"]) == projekt.sitzungen_dir / aufnahme.name and not aufnahme.exists()
    assert k["eingang"] == [] and k["zuletzt"][0]["pfad"] == str(projekt.wurzel)
    # Danach ist die Sitzung eine des Projekts: ins Wiki speichern geht.
    assert client.post("/api/wiki/speichern", json={"sitzung": k["ziel"]}).status_code == 200


def test_zuordnen_nur_aus_dem_eingang(client, sitzung, projekt):
    r = client.post("/api/eingang/zuordnen", json={"sitzung": str(sitzung), "projekt": str(projekt.wurzel)})
    assert r.status_code == 400 and sitzung.is_dir()


def test_zuordnen_nicht_waehrend_die_sitzung_laeuft(client, aufnahme, projekt, monkeypatch):
    from audioscribe.ui import runner as runner_modul

    monkeypatch.setattr(runner_modul.LiveRunner, "laeuft", lambda self: True)
    monkeypatch.setattr(runner_modul.LiveRunner, "session_dir", lambda self: aufnahme)
    r = client.post("/api/eingang/zuordnen", json={"sitzung": str(aufnahme), "projekt": str(projekt.wurzel)})
    assert r.status_code == 409 and aufnahme.is_dir()


def test_zuordnen_in_unbekanntes_projekt(client, aufnahme, tmp_path):
    (tmp_path / "leer").mkdir()
    r = client.post("/api/eingang/zuordnen", json={"sitzung": str(aufnahme), "projekt": str(tmp_path / "leer")})
    assert r.status_code == 400 and aufnahme.is_dir()


def test_eingang_dir_zuruecksetzen(client, eingang_dir):
    client.post("/api/state", json={"eingang_dir": ""})
    assert client.get("/api/kontext").json()["eingang_dir"] == str(eingang.standard_dir())
