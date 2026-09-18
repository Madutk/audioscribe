"""KI-Analyse (PRD §16): reine Logik - ohne Agent SDK, ohne Netz, ohne Claude."""

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from audioscribe.agent import guard
from audioscribe.agent import prozessbild as pb
from audioscribe.agent.fortschritt import STATUS_PREFIX, Fortschritt, parse_status_line
from audioscribe.agent.manifest import (
    Manifest,
    load_manifest,
    manifest_path,
    save_manifest,
)
from audioscribe.agent.material import Auftrag, copy_material, find_transcript, slugify
from audioscribe.agent.prompt import build_task_prompt, system_append
from audioscribe.agent.runner import tool_summary
from audioscribe.agent.skills import (
    discover_skills,
    install_skills,
    parse_frontmatter,
    select_skills,
)
from audioscribe.ui import state
from audioscribe.ui.jobs import AnalyseOptions, build_analyze_argv, scan_results
from audioscribe.ui.runner import AnalyseRunner


def _skill(root: Path, folder: str, name: str | None = None, desc: str = "Tut etwas.") -> Path:
    d = root / folder
    d.mkdir(parents=True)
    head = f"name: {name}\n" if name else ""
    (d / "SKILL.md").write_text(f"---\n{head}description: {desc}\n---\n\n# {folder}\n", encoding="utf-8")
    return d


def _quelle(tmp_path: Path, *, annotiert: bool = False, frames: int = 0) -> Path:
    q = tmp_path / "output" / "aufnahme"
    q.mkdir(parents=True)
    (q / "transkript.md").write_text("# Transkript\n", encoding="utf-8")
    (q / "transcript.json").write_text("{}", encoding="utf-8")
    if annotiert:
        (q / "transkript.annotiert.md").write_text("# Annotiert\n", encoding="utf-8")
    if frames:
        (q / "frames").mkdir()
        for i in range(frames):
            (q / "frames" / f"{i + 1:04d}_00-00-0{i}.jpg").write_bytes(b"jpg")
    return q


# --- Skills ---


def test_frontmatter_einzeilig_und_mit_anfuehrungszeichen():
    meta = parse_frontmatter('---\nname: "mein-skill"\ndescription: Kurz: mit Doppelpunkt\n---\nText')
    assert meta == {"name": "mein-skill", "description": "Kurz: mit Doppelpunkt"}


def test_frontmatter_block_skalar():
    text = "---\nname: x\ndescription: >\n  erste Zeile\n  zweite Zeile\nlicense: MIT\n---\n"
    assert parse_frontmatter(text)["description"] == "erste Zeile zweite Zeile"


def test_frontmatter_fehlt_oder_offen():
    assert parse_frontmatter("# Kein Frontmatter") == {}
    assert parse_frontmatter("---\nname: x\n") == {}


def test_discover_findet_verschachtelte_skills(tmp_path):
    _skill(tmp_path, "direkt")
    _skill(tmp_path / "synced" / "konto-id", "tief", desc="aus claude.ai")
    _skill(tmp_path, "ohne-name-ordner", name=None)
    (tmp_path / "leer").mkdir()
    names = [s.name for s in discover_skills(tmp_path)]
    assert names == ["direkt", "ohne-name-ordner", "tief"]


def test_discover_nimmt_frontmatter_namen_und_sucht_nicht_in_skills_hinein(tmp_path):
    d = _skill(tmp_path, "ordner", name="anderer-name")
    _skill(d, "assets")  # SKILL.md innerhalb eines Skills zaehlt nicht
    assert [s.name for s in discover_skills(tmp_path)] == ["anderer-name"]


def test_discover_fehlender_ordner(tmp_path):
    assert discover_skills(tmp_path / "gibtsnicht") == []


def test_select_skills_reihenfolge_und_unbekannte(tmp_path):
    _skill(tmp_path, "a")
    _skill(tmp_path, "b")
    alle = discover_skills(tmp_path)
    assert [s.name for s in select_skills(alle, ["b", "a", "b"])] == ["b", "a"]
    with pytest.raises(KeyError, match="nope"):
        select_skills(alle, ["a", "nope"])


def test_install_skills_kopiert_und_ersetzt(tmp_path):
    src = _skill(tmp_path / "quelle", "ordner", name="skill-x")
    (src / "scripts").mkdir()
    (src / "scripts" / "run.py").write_text("print(1)", encoding="utf-8")
    ws = tmp_path / "ws"
    (ws / ".claude" / "skills" / "skill-x").mkdir(parents=True)
    (ws / ".claude" / "skills" / "skill-x" / "alt.txt").write_text("alt", encoding="utf-8")

    install_skills(discover_skills(tmp_path / "quelle"), ws)

    ziel = ws / ".claude" / "skills" / "skill-x"  # Ordner heisst wie der Skill-Name
    assert (ziel / "SKILL.md").is_file()
    assert (ziel / "scripts" / "run.py").is_file()
    assert not (ziel / "alt.txt").exists()


# --- Material ---


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Rechnungsprüfung Kreditoren", "rechnungspruefung-kreditoren"),
        ("  Straße / Größe: 2.0  ", "strasse-groesse-2-0"),
        ("Café ÉTÉ", "cafe-ete"),
        ("???", "analyse"),
    ],
)
def test_slugify(name, slug):
    assert slugify(name) == slug


def test_find_transcript_bevorzugt_annotiert(tmp_path):
    q = _quelle(tmp_path, annotiert=True)
    assert find_transcript(q).name == "transkript.annotiert.md"


def test_find_transcript_fehlt(tmp_path):
    with pytest.raises(FileNotFoundError, match="--frames"):
        find_transcript(tmp_path)


def test_copy_material_kopiert_transkript_frames_und_kontext(tmp_path):
    q = _quelle(tmp_path, annotiert=True, frames=3)
    glossar = tmp_path / "glossar.md"
    glossar.write_text("SAP = System", encoding="utf-8")
    folien = tmp_path / "folien.pdf"
    folien.write_bytes(b"%PDF")
    auftrag = Auftrag(
        name="Test", quelle=q, ausgabe=tmp_path / "ana", kontext_dateien=(glossar, folien)
    )

    m = copy_material(auftrag)

    ws = tmp_path / "ana" / "test"
    assert m.transkript == "material/transkript.annotiert.md"
    assert (ws / "material" / "transkript.annotiert.md").is_file()
    assert (ws / "material" / "transkript.md").is_file()
    assert "material/transcript.json" in m.dateien
    assert m.frames == 3 and len(list((ws / "material" / "frames").iterdir())) == 3
    assert m.kontext_inline == (("kontext/glossar.md", "SAP = System"),)
    assert m.kontext_dateien == ("kontext/folien.pdf",)
    # Die Quelle bleibt unangetastet (NFR-12).
    assert sorted(p.name for p in q.iterdir()) == [
        "frames", "transcript.json", "transkript.annotiert.md", "transkript.md"
    ]


def test_copy_material_fehlende_kontextdatei(tmp_path):
    auftrag = Auftrag(
        name="x", quelle=_quelle(tmp_path), ausgabe=tmp_path / "a",
        kontext_dateien=(tmp_path / "fehlt.md",),
    )
    with pytest.raises(FileNotFoundError, match="fehlt.md"):
        copy_material(auftrag)


# --- Prompt ---


def test_task_prompt_enthaelt_material_kontext_und_skills(tmp_path):
    q = _quelle(tmp_path, annotiert=True, frames=2)
    ctx = tmp_path / "ctx.txt"
    ctx.write_text("Zielgruppe: Buchhaltung", encoding="utf-8")
    auftrag = Auftrag(
        name="Rechnungsfreigabe", quelle=q, ausgabe=tmp_path / "a",
        kontext_text="Bitte knapp.", kontext_dateien=(ctx,),
    )
    _skill(tmp_path / "sk", "prozessrekonstruktion", desc="Rekonstruiert Prozesse.")
    text = build_task_prompt(auftrag, copy_material(auftrag), discover_skills(tmp_path / "sk"))

    assert "# Analyseauftrag: Rechnungsfreigabe" in text
    assert "`material/transkript.annotiert.md`" in text
    assert "2 Dateien unter `material/frames/`" in text
    assert "Bitte knapp." in text and "Zielgruppe: Buchhaltung" in text
    assert "**prozessrekonstruktion**: Rekonstruiert Prozesse." in text
    assert "INDEX.md" in text


def test_task_prompt_ohne_bilder_und_ohne_skills(tmp_path):
    auftrag = Auftrag(name="x", quelle=_quelle(tmp_path), ausgabe=tmp_path / "a")
    text = build_task_prompt(auftrag, copy_material(auftrag), [])
    assert "Standbilder: keine" in text
    assert "Skills" not in text and "Kontext" not in text


def test_system_append_liegt_im_paket_und_nennt_python():
    text = system_append(python="/venv/bin/python")
    assert "INDEX.md" in text and "TodoWrite" in text
    # Nummerierung im Prozessbild, damit es sich mit der Schrittliste abgleichen laesst.
    assert 'S3["S3: ' in text and 'E1{"E1: ' in text
    assert '`"/venv/bin/python"`' in text and "{python}" not in text
    assert sys.executable in system_append()


# --- Fortschritt ---


def _fs(tmp_path: Path, frames: int = 4) -> Fortschritt:
    ws = tmp_path / "ws"
    (ws / "material" / "frames").mkdir(parents=True)
    return Fortschritt(ws, frames_total=frames)


def test_fortschritt_plan_aus_todowrite(tmp_path):
    fs = _fs(tmp_path)
    todos = [
        {"content": "Normalisieren", "status": "completed", "activeForm": "Normalisiere"},
        {"content": "Rekonstruieren", "status": "in_progress", "activeForm": "Rekonstruiere Prozess"},
        {"content": "QS", "status": "pending"},
        {"content": " ", "status": "pending"},  # leer -> verworfen
        "kaputt",
    ]
    assert fs.tool_use("t1", "TodoWrite", {"todos": todos})
    assert not fs.tool_use("t2", "TodoWrite", {"todos": todos})  # unveraendert
    snap = fs.snapshot()
    assert (snap["done"], snap["total"], snap["current"]) == (1, 3, "Rekonstruiere Prozess")
    assert fs.plan_line() == "[Plan] 1/3 Schritte erledigt – jetzt: Rekonstruiere Prozess"


def test_fortschritt_plan_aus_taskcreate_und_taskupdate(tmp_path):
    fs = _fs(tmp_path)
    fs.tool_use("c1", "TaskCreate", {"subject": "Bilder ansehen", "description": "…"})
    fs.tool_use("c2", "TaskCreate", {"subject": "Doku schreiben", "activeForm": "Schreibe Doku"})
    fs.tool_use("c3", "TaskCreate", {"subject": "Verworfen"})
    assert fs.snapshot()["total"] == 0  # ID kommt erst mit dem Ergebnis
    assert fs.tool_result("c1", False, "Task #1 created successfully: Bilder ansehen")
    assert fs.tool_result("c2", False, [{"type": "text", "text": "Task #2 created successfully"}])
    assert not fs.tool_result("c3", True, "Fehler")
    for i, upd in enumerate([
        {"taskId": "1", "status": "completed"},
        {"taskId": "2", "status": "in_progress"},
        {"taskId": "9", "status": "completed"},  # unbekannt
    ]):
        fs.tool_use(f"u{i}", "TaskUpdate", upd)
        fs.tool_result(f"u{i}", False, "Updated task status")
    snap = fs.snapshot()
    assert [t["status"] for t in snap["todos"]] == ["completed", "in_progress"]
    assert (snap["done"], snap["total"], snap["current"]) == (1, 2, "Schreibe Doku")
    fs.tool_use("d", "TaskUpdate", {"taskId": "1", "status": "deleted"})
    assert fs.tool_result("d", False, "Updated task #1 deleted")
    assert [t["content"] for t in fs.snapshot()["todos"]] == ["Doku schreiben"]


def test_fortschritt_ohne_plan(tmp_path):
    fs = _fs(tmp_path)
    assert fs.plan_line() is None
    assert fs.snapshot()["total"] == 0


def test_fortschritt_skill_und_bilder(tmp_path):
    fs = _fs(tmp_path)
    ws = fs.workspace
    assert fs.tool_use("s", "Skill", {"skill": "prozessrekonstruktion"})
    assert not fs.tool_use("s2", "Skill", {"skill": "prozessrekonstruktion"})
    # Bild zaehlt erst nach erfolgreichem Ergebnis, doppelt nur einmal.
    assert not fs.tool_use("r1", "Read", {"file_path": str(ws / "material/frames/0001_a.jpg")})
    assert fs.tool_result("r1", is_error=False)
    fs.tool_use("r2", "Read", {"file_path": "material/frames/0001_a.jpg"})
    assert not fs.tool_result("r2", is_error=False)
    fs.tool_use("r3", "Read", {"file_path": "material/frames/0002_b.jpg"})
    assert not fs.tool_result("r3", is_error=True)
    fs.tool_use("r4", "Read", {"file_path": "material/transkript.md"})  # kein Bild
    assert not fs.tool_result("r4", is_error=False)
    snap = fs.snapshot()
    assert snap["skill"] == "prozessrekonstruktion"
    assert (snap["frames_seen"], snap["frames_total"]) == (1, 4)


def test_fortschritt_dokumente(tmp_path):
    fs = _fs(tmp_path)
    for i, (name, path) in enumerate([
        ("Write", "prozess.md"),
        ("Edit", "prozess.md"),                   # schon gezaehlt
        ("Write", "unter/arbeitsanweisung.md"),
        ("Write", "material/x.normalisiert.md"),  # Zwischenstand, kein Dokument
        ("Write", ".claude/skills/a/SKILL.md"),
        ("Write", "analyse.json"),
        ("Write", str(tmp_path / "draussen.md")),
    ]):
        fs.tool_use(f"w{i}", name, {"file_path": path})
        fs.tool_result(f"w{i}", is_error=False)
    fs.tool_use("wx", "Write", {"file_path": "abgelehnt.md"})
    fs.tool_result("wx", is_error=True)
    assert fs.snapshot()["docs"] == ["prozess.md", "unter/arbeitsanweisung.md"]


def test_status_zeile_rundlauf(tmp_path):
    fs = _fs(tmp_path)
    fs.tool_use("s", "Skill", {"skill": "ä-skill"})
    line = fs.status_line()
    assert line.startswith(STATUS_PREFIX)
    assert parse_status_line(line)["skill"] == "ä-skill"
    assert parse_status_line("[Agent] hallo") is None
    assert parse_status_line(STATUS_PREFIX + "{kaputt") is None
    assert parse_status_line(STATUS_PREFIX + "[1]") is None


# --- Schreibschutz ---


def test_guard_schreiben_nur_im_arbeitsordner(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    ok = guard.check_tool("Write", {"file_path": str(ws / "doku.md")}, ws)
    rel = guard.check_tool("Edit", {"file_path": "unter/doku.md"}, ws)
    raus = guard.check_tool("Write", {"file_path": str(tmp_path / "x.md")}, ws)
    ausbruch = guard.check_tool("Write", {"file_path": "../x.md"}, ws)
    skills = guard.check_tool("Edit", {"file_path": ".claude/skills/a/SKILL.md"}, ws)
    leer = guard.check_tool("Write", {}, ws)
    assert ok.erlaubt and rel.erlaubt
    assert not raus.erlaubt and "Ergebnisordner" in raus.grund
    assert not ausbruch.erlaubt
    assert not skills.erlaubt
    assert not leer.erlaubt


@pytest.mark.skipif(sys.platform == "win32", reason="Symlinks brauchen unter Windows Rechte")
def test_guard_symlink_nach_draussen(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (tmp_path / "draussen").mkdir()
    (ws / "link").symlink_to(tmp_path / "draussen")
    assert not guard.check_tool("Write", {"file_path": str(ws / "link" / "x.md")}, ws).erlaubt


def test_guard_lesen_und_sonstige_werkzeuge(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    extra = tmp_path / "extra"
    assert guard.check_tool("Read", {"file_path": "material/a.md"}, ws).erlaubt
    assert guard.check_tool("Glob", {"pattern": "*.md"}, ws).erlaubt
    assert not guard.check_tool("Read", {"file_path": "/etc/passwd"}, ws).erlaubt
    assert guard.check_tool("Grep", {"path": str(extra)}, ws, read_roots=[extra]).erlaubt
    assert guard.check_tool("Skill", {"skill": "x"}, ws).erlaubt
    assert guard.check_tool("Bash", {"command": "python x.py"}, ws).erlaubt
    assert not guard.check_tool("Bash", {"command": "ls"}, ws, bash=False).erlaubt
    assert not guard.check_tool("WebFetch", {"url": "https://x"}, ws).erlaubt


def test_tool_summary():
    assert tool_summary("Write", {"file_path": "/a/b.md", "content": "x"}) == "Write: /a/b.md"
    assert tool_summary("Bash", {"command": "python  s.py\n--x"}) == "Bash: python s.py --x"
    assert tool_summary("TodoWrite", {"todos": []}) == "TodoWrite"


# --- Manifest ---


def test_manifest_rundlauf_und_kaputte_datei(tmp_path):
    m = Manifest(name="x", quelle="/q", skills=["a"], session_id="s1", sitzungen=["s1"])
    save_manifest(tmp_path, m)
    assert load_manifest(tmp_path) == m
    manifest_path(tmp_path).write_text("{kaputt", encoding="utf-8")
    assert load_manifest(tmp_path) is None
    assert load_manifest(tmp_path / "fehlt") is None


def test_manifest_ignoriert_unbekannte_felder(tmp_path):
    manifest_path(tmp_path).write_text('{"name": "x", "quelle": "/q", "neu": 1}', encoding="utf-8")
    assert load_manifest(tmp_path).name == "x"


# --- CLI ---


def test_cli_analyze_list_skills(tmp_path, capsys, monkeypatch):
    from audioscribe.cli import main

    _skill(tmp_path, "mein-skill", desc="Hilft.")
    assert main(["analyze", "--list-skills", "--skills-dir", str(tmp_path)]) == 0
    assert "mein-skill" in capsys.readouterr().out


def test_cli_analyze_ohne_transkript(tmp_path, capsys, monkeypatch):
    from audioscribe.cli import main

    monkeypatch.setattr("sys.stdin", open(__file__))  # kein TTY -> keine Rueckfragen
    code = main(["analyze", str(tmp_path), "--name", "x", "--out", str(tmp_path / "o")])
    assert code == 1
    assert "Kein Transkript" in capsys.readouterr().out


def test_cli_analyze_unbekannter_skill(tmp_path, capsys, monkeypatch):
    from audioscribe.cli import main

    monkeypatch.setattr("sys.stdin", open(__file__))
    q = _quelle(tmp_path)
    code = main([
        "analyze", str(q), "--name", "x", "--out", str(tmp_path / "o"),
        "--skills-dir", str(tmp_path / "keine"), "--skill", "nope",
    ])
    assert code == 2
    assert "nicht gefunden: nope" in capsys.readouterr().out


def test_cli_analyze_resume_ohne_sitzung(tmp_path, capsys, monkeypatch):
    from audioscribe.cli import main

    monkeypatch.setattr("sys.stdin", open(__file__))
    code = main(["analyze", str(_quelle(tmp_path)), "--name", "x", "--out", str(tmp_path), "--resume"])
    assert code == 1
    assert "Keine fortsetzbare Sitzung" in capsys.readouterr().out


# --- Oberflaeche: Aufruf, Quellen, Zustand, Runner ---


def test_build_analyze_argv_alle_optionen(tmp_path):
    opts = AnalyseOptions(
        source=tmp_path / "q",
        name="-Test",
        output_dir=tmp_path / "o",
        context_text="--kein-flag",
        context_files=(tmp_path / "k.md",),
        skills=("a", "b"),
        skills_dir=tmp_path / "s",
        model="claude-sonnet-5",
        bash=False,
    )
    argv = build_analyze_argv(opts, prefix=["as"])
    assert argv[:3] == ["as", "analyze", str(tmp_path / "q")]
    assert "--name=-Test" in argv and "--context-text=--kein-flag" in argv
    assert f"--context={tmp_path / 'k.md'}" in argv
    assert ["--skill=a", "--skill=b"] == [a for a in argv if a.startswith("--skill=")]
    assert "--model=claude-sonnet-5" in argv and "--no-bash" in argv
    assert "--no-skills" not in argv


def test_build_analyze_argv_leere_auswahl_und_parser(tmp_path, monkeypatch):
    from audioscribe import cli
    from audioscribe.agent import kommando

    opts = AnalyseOptions(source=tmp_path, name="-x", output_dir=tmp_path, context_text="--y")
    argv = build_analyze_argv(opts, prefix=[])
    assert "--no-skills" in argv and "--no-bash" not in argv
    # Der echte Parser liest die '='-Form korrekt, auch mit fuehrendem Minus.
    seen = {}
    monkeypatch.setattr(kommando, "analyze", lambda args, resolve: seen.update(vars(args)) or 0)
    assert cli.main(argv) == 0
    assert seen["name"] == "-x" and seen["context_text"] == "--y" and seen["no_skills"]


def test_scan_results_juengste_zuerst(tmp_path):
    for name, frames in (("alt", 0), ("neu", 2)):
        d = tmp_path / name
        (d / "frames").mkdir(parents=True)
        for i in range(frames):
            (d / "frames" / f"{i}.jpg").write_bytes(b"")
        (d / "transkript.md").write_text("x", encoding="utf-8")
        time.sleep(0.02)
    (tmp_path / "neu" / "transkript.annotiert.md").write_text("x", encoding="utf-8")
    (tmp_path / "ohne").mkdir()
    res = scan_results(tmp_path)
    assert [r["name"] for r in res] == ["neu", "alt"]
    assert res[0]["frames"] == 2 and res[0]["annotated"] and not res[1]["annotated"]
    with pytest.raises(NotADirectoryError):
        scan_results(tmp_path / "fehlt")


def test_state_merkt_analyse_optionen(tmp_path):
    state.save_state(
        {"agent_skills": ["a", " ", 3], "agent_bash": 0, "agent_model": " opus ", "fremd": 1},
        cache_dir=tmp_path,
    )
    saved = state.load_state(tmp_path)
    assert saved == {"agent_skills": ["a"], "agent_bash": False, "agent_model": "opus"}
    state.save_state({"agent_skills": []}, cache_dir=tmp_path)
    assert state.load_state(tmp_path)["agent_skills"] == []


def _wait(runner: AnalyseRunner, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = runner.snapshot()
        if not snap["running"]:
            return snap
        time.sleep(0.05)
    raise AssertionError("Analyse-Runner wurde nicht fertig")


def test_analyse_runner_log_manifest_und_doppelstart(tmp_path):
    opts = AnalyseOptions(source=tmp_path, name="Mein Test", output_dir=tmp_path / "o")
    ws = tmp_path / "o" / "mein-test"
    save_manifest(ws, Manifest(name="x", quelle="q", status="fertig", kosten_usd=0.5, session_id="s"))
    (ws / "INDEX.md").write_text("x", encoding="utf-8")
    status = '[Agent-Status] {"todos": [], "done": 1, "total": 3}'
    script = (
        "import time; print('[Agent] hallo', flush=True); "
        f"print({status!r}, flush=True); time.sleep(0.3)"
    )
    runner = AnalyseRunner()
    assert runner.start(opts, argv_builder=lambda o: [sys.executable, "-c", script]) == ws
    with pytest.raises(RuntimeError):
        runner.start(opts, argv_builder=lambda o: [sys.executable, "-c", ""])
    snap = _wait(runner)
    assert snap["returncode"] == 0
    assert "[Agent] hallo" in snap["lines"]
    assert snap["result"]["status"] == "fertig"
    assert "kosten_usd" not in snap["result"]  # Abo: nur Gegenwert, nicht anzeigen
    # Status-Zeilen landen im Fortschritt, nicht im Protokoll.
    assert snap["progress"] == {"todos": [], "done": 1, "total": 3}
    assert not any(line.startswith("[Agent-Status]") for line in snap["lines"])
    assert snap["result"]["index"] == str(ws / "INDEX.md")
    assert runner.snapshot(snap["offset"])["lines"] == []


def test_analyse_runner_abbruch(tmp_path):
    opts = AnalyseOptions(source=tmp_path, name="x", output_dir=tmp_path)
    runner = AnalyseRunner()
    runner.start(
        opts,
        argv_builder=lambda o: [sys.executable, "-c", "import time; print('los', flush=True); time.sleep(30)"],
    )
    deadline = time.monotonic() + 10
    while "los" not in runner.snapshot()["lines"] and time.monotonic() < deadline:
        time.sleep(0.05)
    runner.cancel()
    snap = _wait(runner)
    assert snap["cancelled"] and snap["returncode"] != 0
    assert snap["result"] is None


# --- Oberflaeche: HTTP-Endpunkte (nur mit fastapi + httpx) ---


@pytest.fixture
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from audioscribe.config import settings
    from audioscribe.ui import server

    _skill(tmp_path / "skills", "prozessrekonstruktion")
    fake = replace(
        settings,
        cache_dir=tmp_path / "cache",
        agent_skills_dir=tmp_path / "skills",
        agent_skills=("prozessrekonstruktion", "fehlt"),
        agent_output_dir=tmp_path / "analysen",
        output_dir=tmp_path / "output",
    )
    monkeypatch.setattr(server, "settings", fake)
    monkeypatch.setattr(state, "settings", fake)
    return TestClient(server.create_app())


def test_api_agent_defaults_und_sources(client, tmp_path):
    d = client.get("/api/agent/defaults").json()
    assert [s["name"] for s in d["skills"]] == ["prozessrekonstruktion"]
    assert d["skills"][0]["selected"] and d["model"] == "claude-opus-5"
    _quelle(tmp_path, frames=1)
    r = client.get("/api/agent/sources", params={"output_dir": str(tmp_path / "output")}).json()
    assert [s["name"] for s in r["sources"]] == ["aufnahme"]


def test_api_agent_start_prueft_eingaben(client, tmp_path):
    q = _quelle(tmp_path)
    base = {"source": str(q), "name": "x", "output_dir": str(tmp_path / "analysen")}
    assert client.post("/api/agent/start", json={**base, "name": " "}).status_code == 400
    assert client.post("/api/agent/start", json={**base, "model": "--evil"}).status_code == 400
    assert client.post("/api/agent/start", json={**base, "skills": ["nope"]}).status_code == 400
    assert client.post("/api/agent/start", json={**base, "source": str(tmp_path)}).status_code == 400
    r = client.post("/api/agent/start", json={**base, "context_files": [str(tmp_path / "fehlt")]})
    assert r.status_code == 400 and "Kontextdatei" in r.json()["detail"]


# --- Prozessbild (FR-35) ---

_MERMAID = 'flowchart TD\n    S1["S1: Start"]\n    S2["S2: Ende"]\n    S1 --> S2'


def test_extract_mermaid_mehrere_bloecke():
    md = (
        "Text\n```mermaid\nflowchart TD\n  A --> B\n```\n\n```python\nprint(1)\n```\n"
        "```mermaid \n```\n```mermaid\nflowchart LR\n  C --> D\n```\n"
    )
    assert pb.extract_mermaid(md) == ["flowchart TD\n  A --> B", "flowchart LR\n  C --> D"]


def test_ensure_source_mmd_hat_vorrang_und_reihenfolge(tmp_path):
    for name in ("prozessbild-10.mmd", "prozessbild-2.mmd", "prozessbild.mmd"):
        (tmp_path / name).write_text(_MERMAID, encoding="utf-8")
    (tmp_path / "doku.md").write_text(f"```mermaid\n{_MERMAID}\n```\n", encoding="utf-8")
    names = [p.name for p in pb.ensure_source(tmp_path, ["doku.md"])]
    assert names == ["prozessbild.mmd", "prozessbild-2.mmd", "prozessbild-10.mmd"]


def test_ensure_source_rueckfall_prozessdoku_zuerst(tmp_path):
    (tmp_path / "a-index.md").write_text("```mermaid\nflowchart TD\n  X --> Y\n```\n", encoding="utf-8")
    (tmp_path / "prozessdokumentation.md").write_text(
        f"# Doku\n```mermaid\n{_MERMAID}\n```\n", encoding="utf-8"
    )
    quellen = pb.ensure_source(tmp_path, ["a-index.md", "prozessdokumentation.md", "fehlt.md"])
    assert [q.name for q in quellen] == ["prozessbild.mmd"]
    assert (tmp_path / "prozessbild.mmd").read_text(encoding="utf-8").strip() == _MERMAID


def test_ensure_source_ohne_diagramm(tmp_path):
    (tmp_path / "doku.md").write_text("kein Diagramm", encoding="utf-8")
    assert pb.ensure_source(tmp_path, ["doku.md"]) == []
    log: list[str] = []
    assert pb.erzeuge_prozessbilder(tmp_path, ["doku.md"], log=log.append) == []
    assert "Kein Mermaid-Diagramm" in log[0]


def test_erzeuge_ohne_browser_meldet_nur(tmp_path, monkeypatch):
    (tmp_path / "prozessbild.mmd").write_text(_MERMAID, encoding="utf-8")
    monkeypatch.setattr(pb, "find_browser", lambda: None)
    log: list[str] = []
    assert pb.erzeuge_prozessbilder(tmp_path, log=log.append) == []
    assert "AUDIOSCRIBE_BROWSER" in log[0]


def test_find_browser_reihenfolge():
    edge_wsl = Path("/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
    chrome_win = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    kw = {"which": lambda n: None}
    assert pb.find_browser(env={"AUDIOSCRIBE_BROWSER": "/x/edge"}, **kw) == Path("/x/edge")
    assert pb.find_browser(env={}, platform="linux", wsl=True, exists=lambda p: p == edge_wsl, **kw) == edge_wsl
    assert pb.find_browser(env={}, platform="win32", exists=lambda p: p == chrome_win, **kw) == chrome_win
    assert pb.find_browser(env={}, platform="win32", exists=lambda p: False, **kw) is None
    assert (
        pb.find_browser(env={}, platform="linux", wsl=False, exists=lambda p: True,
                        which=lambda n: "/usr/bin/chromium" if n == "chromium" else None)
        == Path("/usr/bin/chromium")
    )
    assert pb.find_browser(env={}, platform="linux", wsl=False, **kw) is None


def test_browser_argv_und_seite():
    argv = pb.browser_argv(Path("/b/msedge.exe"), "C:\\x\\render.html", "C:\\tmp\\p")
    assert argv[0] == "/b/msedge.exe" and argv[-1] == "C:\\x\\render.html"
    assert "--headless=new" in argv and "--dump-dom" in argv
    assert "--user-data-dir=C:\\tmp\\p" in argv
    page = pb.build_page('flowchart TD\n  A["</script><b>"] --> B')
    assert "</script><b>" not in page.split("const SRC")[1].split(";")[0]
    assert 'src="mermaid.min.js"' in page


def test_parse_dump():
    ok = '<html><pre id="out">{&quot;svg&quot;: &quot;&lt;svg/&gt;&quot;, &quot;png&quot;: &quot;data:,&quot;}</pre>'
    assert pb.parse_dump(ok) == {"svg": "<svg/>", "png": "data:,"}
    assert "keine Ergebnisseite" in pb.parse_dump("<html></html>")["error"]
    assert "nicht rechtzeitig" in pb.parse_dump('<pre id="out">pending</pre>')["error"]
    assert "nicht lesbar" in pb.parse_dump('<pre id="out">{kaputt</pre>')["error"]
    err = '<pre id="out">{"error": "Parse error on line 2"}</pre>'
    assert pb.parse_dump(err) == {"error": "Parse error on line 2"}


def test_render_schreibt_dateien_mit_gefaktem_browser(tmp_path, monkeypatch):
    mmd = tmp_path / "prozessbild.mmd"
    mmd.write_text(_MERMAID, encoding="utf-8")
    png = b"\x89PNG\r\n\x1a\nxyz"
    payload = {"svg": "<svg>ä</svg>", "png": "data:image/png;base64," + base64.b64encode(png).decode()}
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = argv
        seen["page"] = Path(argv[-1]).read_text(encoding="utf-8")
        assert (Path(argv[-1]).parent / "mermaid.min.js").is_file()
        dom = '<pre id="out">' + json.dumps(payload).replace('"', "&quot;") + "</pre>"
        return subprocess.CompletedProcess(argv, 0, dom, "")

    monkeypatch.setattr(pb.subprocess, "run", fake_run)
    svg_path, png_path = pb.render(mmd, Path("/usr/bin/chromium"))
    assert svg_path.read_text(encoding="utf-8") == "<svg>ä</svg>"
    assert png_path.read_bytes() == png
    assert "S1: Start" in seen["page"]
    assert not (tmp_path / ".prozessbild-tmp").exists()  # aufgeraeumt


def test_render_fehler_wird_runtimeerror(tmp_path, monkeypatch):
    mmd = tmp_path / "prozessbild.mmd"
    mmd.write_text(_MERMAID, encoding="utf-8")
    monkeypatch.setattr(
        pb.subprocess, "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, '<pre id="out">{"error": "Parse error"}</pre>', ""),
    )
    with pytest.raises(RuntimeError, match="Mermaid-Fehler in prozessbild.mmd: Parse error"):
        pb.render(mmd, Path("/usr/bin/chromium"))
    (tmp_path / "leer.mmd").write_text(" ", encoding="utf-8")
    with pytest.raises(RuntimeError, match="leer"):
        pb.render(tmp_path / "leer.mmd", Path("/usr/bin/chromium"))


def test_cli_analyze_no_prozessbild_flag(tmp_path, monkeypatch):
    from audioscribe import cli
    from audioscribe.agent import kommando

    seen = {}
    monkeypatch.setattr(kommando, "analyze", lambda args, resolve: seen.update(vars(args)) or 0)
    assert cli.main(["analyze", str(tmp_path), "--no-prozessbild"]) == 0
    assert seen["no_prozessbild"] is True


@pytest.mark.skipif(
    not os.environ.get("AUDIOSCRIBE_TEST_BROWSER"),
    reason="echtes Rendern nur mit AUDIOSCRIBE_TEST_BROWSER=1 (braucht Edge/Chrome)",
)
def test_render_echt_mit_browser(tmp_path):
    browser = pb.find_browser()
    assert browser is not None
    mmd = tmp_path / "prozessbild.mmd"
    mmd.write_text(_MERMAID, encoding="utf-8")
    svg, png = pb.render(mmd, browser)
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    text = svg.read_text(encoding="utf-8")
    assert "<svg" in text
    # Feste Pixelmasse statt width="100%" - sonst zeigen Bildbetrachter eine leere Flaeche.
    assert 'width="100%"' not in text and 'height="' in text
