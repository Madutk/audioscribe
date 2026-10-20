"""LLM-Wiki-Ordner einer beendeten Sitzung (live/llm_wiki.py)."""

import json
import re
from pathlib import Path
from urllib.parse import unquote

import pytest

from audioscribe.live import journal, llm_wiki


def test_transkript_und_bilder_unter_dem_titel(sitzung):
    datei = llm_wiki.erzeuge(sitzung)
    ordner = sitzung / "LLM-Wiki"
    assert datei == ordner / "Workshop Reisebuchung.md"
    assert sorted(p.name for p in (ordner / "Workshop Reisebuchung").iterdir()) == ["0001_00-00-03.jpg", "0002_00-00-12.jpg"]
    links = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", datei.read_text(encoding="utf-8"))
    assert len(links) == 2 and all((ordner / unquote(link)).is_file() for link in links)
    assert "Wir buchen immer zweite Klasse." in datei.read_text(encoding="utf-8")


def test_ohne_bilder_byte_gleiche_kopie(sitzung):
    (sitzung / "marks.json").unlink()
    datei = llm_wiki.erzeuge(sitzung)
    assert datei.read_bytes() == (sitzung / "transkript.md").read_bytes()
    assert [p.name for p in datei.parent.iterdir()] == [datei.name]


def test_neuer_titel_ersetzt_die_alten_namen(sitzung):
    llm_wiki.erzeuge(sitzung)
    journal.schreibe_status(sitzung, titel="Review Freigaben")
    datei = llm_wiki.erzeuge(sitzung)
    assert sorted(p.name for p in datei.parent.iterdir()) == ["Review Freigaben", "Review Freigaben.md"]
    assert not any(p.name.startswith(".LLM-Wiki") for p in sitzung.iterdir())


@pytest.mark.parametrize(
    ("titel", "name"),
    [("a/b: c?", "a-b- c-"), ("  ..Geheim  ", "Geheim"), ("", "live-2026-10-06_11-21-57"), ("Über Ärger", "Über Ärger")],
)
def test_dateiname(titel, name):
    assert llm_wiki.dateiname(titel, Path("live-2026-10-06_11-21-57")) == name


def test_fehler_unterwegs_laesst_den_alten_stand_stehen(sitzung, monkeypatch):
    alt = llm_wiki.erzeuge(sitzung)
    journal.schreibe_status(sitzung, titel="Neu")

    def kaputt(*a, **k):
        raise OSError("Platte voll")

    monkeypatch.setattr(llm_wiki.shutil, "copy2", kaputt)
    with pytest.raises(OSError):
        llm_wiki.erzeuge(sitzung)
    assert alt.is_file() and not (sitzung / ".LLM-Wiki.neu").exists()


def test_ohne_transkript_kein_ordner(tmp_path):
    with pytest.raises(FileNotFoundError):
        llm_wiki.erzeuge(tmp_path)
    assert not (tmp_path / "LLM-Wiki").exists()


def test_ohne_titel_der_sitzungsname(sitzung):
    status = json.loads((sitzung / "sitzung.json").read_text(encoding="utf-8"))
    (sitzung / "sitzung.json").write_text(json.dumps({**status, "titel": ""}), encoding="utf-8")
    assert llm_wiki.erzeuge(sitzung).name == f"{sitzung.name}.md"
