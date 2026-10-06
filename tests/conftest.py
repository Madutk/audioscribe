"""Gemeinsame Fixtures: Tests lesen und schreiben nie die Einstellungen des Rechners.

Ohne diese Abschirmung landete der Einstellungsstand der Tests im Konfigurationsordner des
Nutzers, und eine alte ``~/.cache/audioscribe/ui-state.json`` wurde in frische Test-Staende
uebernommen (``ui/state._uebernehme_alte_datei``) - Tests hingen damit vom Rechner ab.
"""

import dataclasses
import json

import pytest


@pytest.fixture(autouse=True)
def _eigene_einstellungen(tmp_path_factory, monkeypatch):
    from audioscribe.config import settings
    from audioscribe.ui import state

    basis = tmp_path_factory.mktemp("einstellungen")
    monkeypatch.setattr(
        state, "settings", dataclasses.replace(settings, cache_dir=basis / "cache", config_dir=basis / "config")
    )


@pytest.fixture
def wiki(tmp_path):
    """Ein kleines LLM-Wiki im Karpathy-Muster: ``wiki/`` mit Seiten, ``raw/`` leer."""
    wurzel = tmp_path / "bahn-wiki"
    (wurzel / "wiki").mkdir(parents=True)
    (wurzel / "raw").mkdir()
    (wurzel / "wiki" / "index.md").write_text("# Bahnbuchung\n\n- [[freigaben]]\n", encoding="utf-8")
    (wurzel / "wiki" / "freigaben.md").write_text(
        "# Freigaben\n\n## Grenzen\n\nBuchungen ab 250 Euro gibt die Teamleitung frei.\n", encoding="utf-8"
    )
    return wurzel


@pytest.fixture
def projekt(wiki, tmp_path):
    """Angelegtes Projekt zum Wiki; Sitzungen liegen neben dem Wiki."""
    from audioscribe.projekt import modell

    return modell.lege_an(
        name="Bahnbuchung", wurzel=wiki, sitzungen_dir=tmp_path / "sitzungen", assets_dir=wiki / "raw" / "assets"
    )


@pytest.fixture
def sitzung(projekt):
    """Beendete Sitzung mit Transkript, zwei Standbildern und einer Souffleur-Markierung."""
    from audioscribe.live.store import write_transcript
    from audioscribe.models import Segment
    from audioscribe.review.marks import Mark, save_marks
    from audioscribe.souffleur import markierung

    ordner = projekt.sitzungen_dir / "live-2026-10-06_11-21-57"
    (ordner / "frames").mkdir(parents=True)
    for name in ("0001_00-00-03.jpg", "0002_00-00-12.jpg"):
        (ordner / "frames" / name).write_bytes(b"\xff\xd8bild-" + name.encode())
    save_marks(
        ordner,
        [
            Mark(t=3.0, png="frames/0001_00-00-03.jpg", id=1, kind="auto"),
            Mark(t=12.0, png="frames/0002_00-00-12.jpg", id=2, kind="auto"),
        ],
    )
    write_transcript(
        ordner,
        [
            Segment(0.0, 5.0, "Wir buchen immer zweite Klasse.", "Ich"),
            Segment(10.0, 15.0, "Ab welchem Betrag braucht es eine Freigabe?", "Sprecher 1"),
        ],
        duration_s=20, language="de", model="t", mode="live",
    )
    m = markierung.Markierung(
        id=1, art="frage", segment_id=2, t_start=10.0, t_end=15.0, sprecher="Sprecher 1",
        aussage="Ab welchem Betrag braucht es eine Freigabe?",
        fundstellen=[markierung.Fundstelle("wiki/freigaben.md", "Grenzen", 3, "Buchungen ab 250 Euro …")],
        wiki_zitat="Buchungen ab 250 Euro gibt die Teamleitung frei.",
    )
    markierung.schreibe(ordner, markierung.SouffleurStand(sitzung=ordner.name, markierungen=[m]))
    (ordner / "sitzung.json").write_text(
        json.dumps({"sitzung_id": "abc123", "status": "beendet", "titel": "Workshop Reisebuchung"}), encoding="utf-8"
    )
    return ordner
