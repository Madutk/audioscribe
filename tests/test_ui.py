import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from audioscribe.pipeline.diarize import make_progress_hook
from audioscribe.pipeline.media import AUDIO_SUFFIXES, VIDEO_SUFFIXES
from audioscribe.ui import browse, state
from audioscribe.ui.jobs import (
    MEDIA_SUFFIXES,
    JobOptions,
    build_argv,
    child_env,
    cuda_probe_argv,
    is_done,
    parse_duration_line,
    parse_progress,
    parse_stage,
    scan_media,
    select_files,
    transcript_path,
)
from audioscribe.ui.runner import BatchRunner, FileState, _Stage, batch_eta, file_fraction


def _opts(tmp_path: Path, **kwargs) -> JobOptions:
    return JobOptions(input_dir=tmp_path / "in", output_dir=tmp_path / "out", **kwargs)


# --- Medien-Scan ---


def test_media_suffixes_ist_vereinigung():
    assert MEDIA_SUFFIXES == VIDEO_SUFFIXES | AUDIO_SUFFIXES


def test_scan_media_findet_audio_und_video(tmp_path):
    for name in ("a.mp3", "b.MP4", "c.wav", "notiz.txt", "daten.json"):
        (tmp_path / name).touch()
    assert [p.name for p in scan_media(tmp_path)] == ["a.mp3", "b.MP4", "c.wav"]


def test_scan_media_ignoriert_unterordner_und_artefakte(tmp_path):
    (tmp_path / "film.mp4").touch()
    (tmp_path / "film.16k.wav").touch()  # Zwischenprodukt der Pipeline
    (tmp_path / ".versteckt.mp3").touch()
    sub = tmp_path / "unterordner"
    sub.mkdir()
    (sub / "tief.mp4").touch()
    assert [p.name for p in scan_media(tmp_path)] == ["film.mp4"]


def test_scan_media_sortiert_ohne_gross_klein(tmp_path):
    for name in ("Zebra.mp3", "apfel.mp3", "Birne.mp3"):
        (tmp_path / name).touch()
    assert [p.name for p in scan_media(tmp_path)] == ["apfel.mp3", "Birne.mp3", "Zebra.mp3"]


def test_scan_media_fehlender_ordner_wirft(tmp_path):
    with pytest.raises(NotADirectoryError):
        scan_media(tmp_path / "gibtsnicht")


def test_scan_media_ueberspringt_unlesbare_eintraege(tmp_path, monkeypatch):
    """Unter /mnt/c liegen Windows-Systemdateien, deren stat() 'Permission denied' liefert -
    der Ordner selbst ist lesbar und darf daran nicht scheitern."""
    (tmp_path / "gut.mp3").touch()
    (tmp_path / "gesperrt.mp4").touch()

    echtes_is_file = os.DirEntry.is_file

    def is_file(self):
        if self.name == "gesperrt.mp4":
            raise PermissionError(13, "Permission denied", self.path)
        return echtes_is_file(self)

    monkeypatch.setattr(os.DirEntry, "is_file", is_file, raising=False)
    assert [p.name for p in scan_media(tmp_path)] == ["gut.mp3"]


def test_is_done_erst_wenn_transkript_existiert(tmp_path):
    media = tmp_path / "meeting.mp4"
    out = tmp_path / "output"
    assert is_done(media, out) is False
    target = transcript_path(media, out)
    assert target == out / "meeting" / "transkript.md"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    assert is_done(media, out) is True


# --- Aufruf des CLI-Subprozesses ---


def test_build_argv_enthaelt_run_und_optionen(tmp_path):
    opts = _opts(tmp_path, model="medium", language="en", device="cpu")
    argv = build_argv(tmp_path / "a.mp4", opts, prefix=["python", "-m", "audioscribe.cli"])
    assert argv[:4] == ["python", "-m", "audioscribe.cli", "run"]
    assert argv[4] == str(tmp_path / "a.mp4")
    assert argv[argv.index("--output") + 1] == str(tmp_path / "out")
    assert argv[argv.index("--model") + 1] == "medium"
    assert argv[argv.index("--language") + 1] == "en"
    assert argv[argv.index("--device") + 1] == "cpu"


def test_build_argv_no_diarize_nur_wenn_abgeschaltet(tmp_path):
    assert "--no-diarize" not in build_argv(Path("a.mp4"), _opts(tmp_path, diarize=True), prefix=[])
    assert "--no-diarize" in build_argv(Path("a.mp4"), _opts(tmp_path, diarize=False), prefix=[])


def test_child_env_setzt_pythonunbuffered_und_progress():
    env = child_env({"FOO": "bar"})
    # beides ueberlebt das os.execv des cuDNN-Bootstraps, anders als Kommandozeilen-Optionen
    assert env["PYTHONUNBUFFERED"] == "1"
    assert env["AUDIOSCRIBE_PROGRESS"] == "1"
    assert env["FOO"] == "bar"


# --- Dateiauswahl ---


def _make_media(tmp_path: Path, *names: str) -> Path:
    for name in names:
        (tmp_path / name).touch()
    return tmp_path


def test_select_files_behaelt_scan_reihenfolge(tmp_path):
    _make_media(tmp_path, "a.mp3", "b.mp4", "c.wav")
    chosen = select_files(tmp_path, ["c.wav", "a.mp3"])
    assert [p.name for p in chosen] == ["a.mp3", "c.wav"]


def test_select_files_weist_pfade_und_gefilterte_ab(tmp_path):
    _make_media(tmp_path, "a.mp3", ".versteckt.mp3", "film.16k.wav")
    (tmp_path / "unter").mkdir()
    (tmp_path / "unter" / "tief.mp3").touch()
    schlecht = ["../a.mp3", "unter/tief.mp3", "/etc/passwd", ".versteckt.mp3", "film.16k.wav"]
    assert select_files(tmp_path, schlecht) == []
    assert select_files(tmp_path, []) == []


def test_cuda_probe_laeuft_in_eigenem_prozess():
    argv = cuda_probe_argv("python")
    assert argv[0] == "python" and argv[1] == "-c"
    assert "torch.cuda.is_available" in argv[2]


# --- Stufen-Parser (Gegenstueck zu ConsoleReporter.stage) ---


def test_parse_stage_erkennt_stufenzeile():
    assert parse_stage("[Stufe 2/5] Transkription (faster-whisper large-v3)") == (
        2,
        5,
        "Transkription (faster-whisper large-v3)",
    )


def test_parse_stage_ignoriert_normale_zeilen():
    assert parse_stage("   - Markdown: output/x/transkript.md") is None
    assert parse_stage("") is None


# --- Feinfortschritt (WhisperX' eigene Zeilen + unsere) ---


def test_parse_progress_beide_formate():
    assert parse_progress("Progress: 42.50%...") == 42.5
    assert parse_progress("[Fortschritt] 7.0%") == 7.0
    assert parse_progress("Progress: 100.00%...") == 100.0


def test_parse_progress_verankert_gegen_fremdausgaben():
    # verankert, damit keine fremde Bibliotheksausgabe als Fortschritt gedeutet wird
    assert parse_progress("   - Progress: 5%") is None
    assert parse_progress("Downloading Progress: 10%...") is None
    assert parse_progress("Progress: 42.50%") is None
    assert parse_progress("[Stufe 2/5] Transkription") is None
    assert parse_progress("") is None


def test_parse_duration_line_nur_bei_ladezeile():
    assert parse_duration_line("   - meeting.16k.wav: 00:06:58 (419s)") == 419.0
    assert parse_duration_line("   - testton.wav: 00:00:03 (3s)") == 3.0
    # die anderen '   - ...:'-Zeilen duerfen nicht ansprechen
    assert parse_duration_line("   - Markdown: output/x/transkript.md") is None
    assert parse_duration_line("   - Sprache: de, 0 Segmente") is None


# --- Windows-/WSL-Pfade ---


def test_windows_to_wsl_laufwerksbuchstabe():
    assert browse.windows_to_wsl(r"C:\Users\user\Videos") == "/mnt/c/Users/user/Videos"
    assert browse.windows_to_wsl("c:/Users/user") == "/mnt/c/Users/user"
    assert browse.windows_to_wsl("D:\\") == "/mnt/d"
    assert browse.windows_to_wsl("E:") == "/mnt/e"


def test_windows_to_wsl_unc_pfad():
    assert browse.windows_to_wsl(r"\\wsl$\Ubuntu\home\user") == "/home/user"
    assert browse.windows_to_wsl(r"\\wsl.localhost\Ubuntu\home") == "/home"


def test_windows_to_wsl_laesst_posix_unveraendert():
    assert browse.windows_to_wsl("/mnt/c/x") == "/mnt/c/x"
    assert browse.windows_to_wsl("~/videos") == "~/videos"
    assert browse.windows_to_wsl("") == ""


def test_wsl_to_windows_mnt_und_laufwerk():
    assert browse.wsl_to_windows("/mnt/c/Users/user") == r"C:\Users\user"
    assert browse.wsl_to_windows("/mnt/d") == "D:\\"
    assert browse.wsl_to_windows("c:/Users/user") == r"C:\Users\user"
    # "C:" allein waere unter Windows das aktuelle Verzeichnis auf C: - Trenner muss dran.
    assert browse.wsl_to_windows("C:") == "C:\\"
    assert browse.wsl_to_windows(r'"C:\Users\user"') == r"C:\Users\user"


def test_wsl_to_windows_laesst_linux_pfade_stehen():
    assert browse.wsl_to_windows("/home/user") == "/home/user"
    assert browse.wsl_to_windows(r"\\wsl$\Ubuntu\home\user") == r"\\wsl$\Ubuntu\home\user"
    assert browse.wsl_to_windows("") == ""


def test_to_native_richtet_sich_nach_dem_system():
    assert browse.to_native(r"C:\Users\user", windows=True) == r"C:\Users\user"
    assert browse.to_native(r"C:\Users\user", windows=False) == "/mnt/c/Users/user"


def test_normalize_path_nutzt_default_bei_leerer_eingabe(tmp_path):
    assert browse.normalize_path("", default=tmp_path) == tmp_path.resolve()


# --- Verzeichnis-Listing ---


def test_list_dirs_nur_verzeichnisse_ohne_punktordner(tmp_path):
    (tmp_path / "beta").mkdir()
    (tmp_path / "Alpha").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / "datei.txt").touch()
    assert [p.name for p in browse.list_dirs(tmp_path)] == ["Alpha", "beta"]


@pytest.mark.skipif(os.name != "nt", reason="Datei-Attribute gibt es nur unter Windows")
def test_list_dirs_blendet_versteckte_windows_ordner_aus(tmp_path):
    import ctypes

    (tmp_path / "sichtbar").mkdir()
    versteckt = tmp_path / "versteckt"
    versteckt.mkdir()
    # FILE_ATTRIBUTE_HIDDEN - so sind z. B. "$Recycle.Bin" und "System Volume Information"
    # in C:\ markiert; ohne Punkt im Namen wuerden sie sonst mitten in der Liste stehen.
    assert ctypes.windll.kernel32.SetFileAttributesW(str(versteckt), 0x2)

    assert [p.name for p in browse.list_dirs(tmp_path)] == ["sichtbar"]
    assert [p.name for p in browse.list_dirs(tmp_path, show_hidden=True)] == [
        "sichtbar",
        "versteckt",
    ]


@pytest.mark.skipif(os.name == "nt", reason="POSIX-Wurzel")
def test_breadcrumbs_pfadkette_posix():
    assert browse.breadcrumbs(Path("/mnt/c/Users")) == [
        ("/", "/"),
        ("mnt", "/mnt"),
        ("c", "/mnt/c"),
        ("Users", "/mnt/c/Users"),
    ]


@pytest.mark.skipif(os.name != "nt", reason="Laufwerksbuchstaben")
def test_breadcrumbs_pfadkette_windows():
    # Wurzel ist das Laufwerk, nicht "/" - sonst zeigen alle Krumen ins Leere.
    assert browse.breadcrumbs(Path(r"C:\Users\user")) == [
        ("C:", "C:\\"),
        ("Users", r"C:\Users"),
        ("user", r"C:\Users\user"),
    ]


def test_quick_links_windows_bietet_laufwerke_und_nutzerordner(tmp_path, monkeypatch):
    root = tmp_path / "projekt"
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    root.mkdir()
    laufwerk = tmp_path / "laufwerk_c"
    laufwerk.mkdir()
    monkeypatch.setattr(browse, "windows_drives", lambda: [laufwerk])

    links = browse.quick_links(
        project_root=root,
        input_dir=root / "input",  # nicht vorhanden -> faellt raus
        output_dir=root,  # gleicher Pfad wie Projekt -> nur einmal
        home=home,
        windows=True,
    )
    assert [label for label, _ in links] == ["Projekt", "Home", laufwerk.drive, "Downloads"]


def test_quick_links_findet_nur_laufwerksbuchstaben(tmp_path):
    mnt = tmp_path / "mnt"
    for name in ("c", "d", "wslg"):
        (mnt / name).mkdir(parents=True)
    root = tmp_path / "projekt"
    root.mkdir()
    links = browse.quick_links(
        project_root=root,
        input_dir=root,  # gleicher Pfad -> darf nur einmal auftauchen
        output_dir=tmp_path / "fehlt",  # nicht vorhanden -> faellt raus
        home=root,
        mnt_root=mnt,
        windows=False,
    )
    labels = [label for label, _ in links]
    assert labels == ["Projekt", "Windows C:", "Windows D:"]


# --- Runner (ohne Modelle: die Kind-Prozesse sind python -c Einzeiler) ---


def _wait_until_idle(runner: BatchRunner, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = runner.snapshot()
        if not snap["running"] and snap["summary"]:
            return snap
        time.sleep(0.05)
    raise AssertionError("Runner wurde nicht fertig")


def test_runner_streamt_log_und_meldet_erfolg(tmp_path):
    runner = BatchRunner()
    runner.start(
        _opts(tmp_path),
        [Path("a.mp4")],
        argv_builder=lambda media, opts: [sys.executable, "-c", "print('[Stufe 1/2] Test')"],
    )
    snap = _wait_until_idle(runner)
    assert [f["state"] for f in snap["files"]] == ["fertig"]
    assert any("[Stufe 1/2] Test" in line for line in snap["lines"])
    assert "1 von 1 transkribiert" in snap["summary"]


def test_runner_setzt_fehler_und_macht_weiter(tmp_path):
    codes = {"a.mp4": "raise SystemExit(3)", "b.mp4": "print('ok')"}
    runner = BatchRunner()
    runner.start(
        _opts(tmp_path),
        [Path("a.mp4"), Path("b.mp4")],
        argv_builder=lambda media, opts: [sys.executable, "-c", codes[media.name]],
    )
    snap = _wait_until_idle(runner)
    assert [f["state"] for f in snap["files"]] == ["fehler", "fertig"]
    assert snap["files"][0]["returncode"] == 3
    assert "1 fehlgeschlagen: a.mp4" in snap["summary"]


def test_runner_startet_auch_bereits_transkribierte(tmp_path):
    """Die Auswahl in der Oberflaeche entscheidet - wer eine fertige Datei ankreuzt,
    will sie neu haben. Es gibt darum kein Ueberspringen mehr."""
    opts = _opts(tmp_path)
    media = tmp_path / "fertig.mp4"
    transcript_path(media, opts.output_dir).parent.mkdir(parents=True)
    transcript_path(media, opts.output_dir).write_text("x", encoding="utf-8")

    gestartet = []
    runner = BatchRunner()
    runner.start(
        opts,
        [media],
        argv_builder=lambda m, o: gestartet.append(m) or [sys.executable, "-c", "pass"],
    )
    snap = _wait_until_idle(runner)
    assert gestartet == [media]
    assert [f["state"] for f in snap["files"]] == ["fertig"]


def test_runner_lehnt_zweiten_start_ab(tmp_path):
    runner = BatchRunner()
    argv_builder = lambda media, opts: [sys.executable, "-c", "import time; time.sleep(3)"]  # noqa: E731
    runner.start(_opts(tmp_path), [Path("a.mp4")], argv_builder=argv_builder)
    try:
        with pytest.raises(RuntimeError):
            runner.start(_opts(tmp_path), [Path("b.mp4")], argv_builder=argv_builder)
    finally:
        runner.cancel()
    snap = _wait_until_idle(runner)
    assert snap["cancelled"] is True


def test_runner_snapshot_offset_liefert_nur_neue_zeilen(tmp_path):
    runner = BatchRunner()
    runner.start(
        _opts(tmp_path),
        [Path("a.mp4")],
        argv_builder=lambda media, opts: [sys.executable, "-c", "print('hallo')"],
    )
    snap = _wait_until_idle(runner)
    assert runner.snapshot(snap["offset"])["lines"] == []


def test_runner_liest_prozent_und_dauer_und_flutet_den_log_nicht(tmp_path):
    """20 Fortschrittszeilen -> percent erreicht 100, aber nur die Zehnerschritte
    landen im Protokoll (eine Zweistundendatei erzeugt sonst ~240 Zeilen)."""
    kind = (
        "print('[Stufe 2/2] Transkription')\n"
        "print('   - a.mp3: 00:01:00 (60s)')\n"
        "[print(f'Progress: {(i+1)*5:.2f}%...') for i in range(20)]\n"
    )
    runner = BatchRunner()
    runner.start(
        _opts(tmp_path),
        [Path("a.mp3")],
        argv_builder=lambda media, opts: [sys.executable, "-c", kind],
    )
    snap = _wait_until_idle(runner)
    entry = snap["files"][0]
    assert entry["percent"] == 100.0
    assert entry["duration"] == 60.0
    assert entry["fraction"] == 1.0
    prozentzeilen = [line for line in snap["lines"] if line.strip().endswith("%")]
    assert 0 < len(prozentzeilen) <= 12


def test_runner_setzt_prozent_zwischen_dateien_zurueck(tmp_path):
    kind = "print('[Stufe 1/2] Eins')\nprint('Progress: 100.00%...')"
    runner = BatchRunner()
    runner.start(
        _opts(tmp_path),
        [Path("a.mp3"), Path("b.mp3")],
        argv_builder=lambda media, opts: [
            sys.executable,
            "-c",
            kind if media.name == "a.mp3" else "print('[Stufe 1/2] Eins')",
        ],
    )
    snap = _wait_until_idle(runner)
    # b.mp3 hat keine Prozentzeile gesendet -> darf die 100 % von a.mp3 nicht erben
    assert snap["files"][1]["percent"] is None


def test_cli_kennt_ui_subkommando():
    proc = subprocess.run(
        [sys.executable, "-m", "audioscribe.cli", "ui", "--help"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "--port" in proc.stdout and "8766" in proc.stdout


# --- Fortschrittsbalken je Datei ---


def test_file_fraction_aus_stufe_und_prozent():
    assert file_fraction(None, None) == 0.0
    assert file_fraction(_Stage(3, 5, "x"), 50.0) == pytest.approx(0.5)
    assert file_fraction(_Stage(1, 5, "x"), 0.0) == pytest.approx(0.0)
    assert file_fraction(_Stage(5, 5, "x"), 100.0) == pytest.approx(1.0)
    # ohne Feinfortschritt zaehlt der Stufenanfang
    assert file_fraction(_Stage(3, 4, "x"), None) == pytest.approx(0.5)


def test_file_fraction_ist_monoton():
    folge = [(_Stage(1, 3, "a"), None), (_Stage(1, 3, "a"), 50.0), (_Stage(2, 3, "b"), None),
             (_Stage(2, 3, "b"), 90.0), (_Stage(3, 3, "c"), 100.0)]
    werte = [file_fraction(stage, pct) for stage, pct in folge]
    assert werte == sorted(werte)


# --- Restzeit ---


def _fs(name, state, duration=None, seconds=None, fraction=0.0):
    return FileState(
        name=name, path=name, state=state, duration=duration, seconds=seconds, fraction=fraction
    )


def test_batch_eta_ohne_fertige_datei_keine_schaetzung():
    files = [_fs("a", "laeuft", duration=600, fraction=0.5)]
    eta = batch_eta(files, 0, elapsed_current=30)
    assert eta["eta_s"] is None
    assert eta["audio_total_s"] == 600
    # der angebrochene Anteil laeuft in den Gesamtbalken ein
    assert eta["audio_done_s"] == 300


def test_batch_eta_rechnet_aus_einer_fertigen_datei():
    files = [
        _fs("a", "fertig", duration=600, seconds=60, fraction=1.0),
        _fs("b", "wartet", duration=600),
    ]
    eta = batch_eta(files, None, elapsed_current=0)
    assert eta["eta_s"] == pytest.approx(60, abs=1)


def test_batch_eta_trennt_festen_aufwand_vom_durchsatz():
    # 20 s Grundkosten je Datei + 0.1 x Audiodauer
    files = [
        _fs("a", "fertig", duration=100, seconds=30, fraction=1.0),
        _fs("b", "fertig", duration=600, seconds=80, fraction=1.0),
        _fs("c", "wartet", duration=600),
    ]
    eta = batch_eta(files, None, elapsed_current=0)
    assert eta["eta_s"] == pytest.approx(80, abs=2)


def test_batch_eta_ignoriert_fehlgeschlagene_und_unbekannte():
    files = [
        _fs("a", "fertig", duration=600, seconds=60, fraction=1.0),
        _fs("kaputt", "fehler", duration=600, seconds=2),  # verbrennt Zeit ohne Audio
        _fs("ohne", "wartet", duration=None),  # Laenge unbekannt
        _fs("b", "wartet", duration=600),
    ]
    eta = batch_eta(files, None, elapsed_current=0)
    assert eta["eta_s"] == pytest.approx(60, abs=1)
    assert eta["unknown_count"] == 1
    # die fehlgeschlagene Datei blockiert den Gesamtbalken nicht
    assert eta["audio_done_s"] == 1200


# --- pyannote-Hook fuer den Diarisierungs-Fortschritt ---


def test_hook_bildet_beide_schritte_auf_einen_balken_ab():
    gemeldet = []
    hook = make_progress_hook(gemeldet.append, min_delta=0.0, min_interval=0.0)
    hook("segmentation", None, total=10, completed=5)
    hook("embeddings", None, total=10, completed=5)
    assert gemeldet == [pytest.approx(25.0), pytest.approx(75.0)]


def test_hook_ignoriert_artefakt_aufrufe():
    gemeldet = []
    hook = make_progress_hook(gemeldet.append, min_delta=0.0, min_interval=0.0)
    hook("segmentation", object())  # nur Artefakt, kein completed/total
    hook("speaker_counting", object(), total=10, completed=5)  # Schritt ohne Balken
    hook("embeddings", None, total=0, completed=5)  # Division durch null
    assert gemeldet == []


def test_hook_bleibt_monoton():
    gemeldet = []
    hook = make_progress_hook(gemeldet.append, min_delta=0.0, min_interval=0.0)
    hook("segmentation", None, total=10, completed=8)
    hook("segmentation", None, total=10, completed=3)  # Rueckschritt
    assert gemeldet == [pytest.approx(40.0)]


def test_hook_drosselt_die_meldungen():
    gemeldet = []
    hook = make_progress_hook(gemeldet.append, min_delta=1.0, min_interval=0.0)
    for i in range(1000):
        hook("segmentation", None, total=1000, completed=i + 1)
    assert len(gemeldet) <= 51  # der Schritt deckt nur 0..50 %


def test_hook_kippt_die_diarisierung_nicht():
    """pyannote ruft den Hook ungeschuetzt auf - eine Ausnahme darf nie durchschlagen."""
    def kaputt(_percent):
        raise RuntimeError("boom")

    hook = make_progress_hook(kaputt, min_delta=0.0, min_interval=0.0)
    assert hook("segmentation", None, total=10, completed=5) is None


# --- Gemerkter Zustand ---


def test_state_rundlauf(tmp_path):
    state.save_state({"input_dir": "/a", "model": "medium", "diarize": False}, tmp_path)
    assert state.load_state(tmp_path) == {"input_dir": "/a", "model": "medium", "diarize": False}
    # zweiter Schreibvorgang ergaenzt, statt zu ersetzen
    state.save_state({"output_dir": "/b"}, tmp_path)
    assert state.load_state(tmp_path)["input_dir"] == "/a"


def test_state_speichert_nur_bekannte_schluessel(tmp_path):
    state.save_state({"input_dir": "/a", "boeses": "rm -rf", "output_dir": "  "}, tmp_path)
    gespeichert = state.load_state(tmp_path)
    assert gespeichert == {"input_dir": "/a"}  # leerer Pfad und Fremdschluessel fallen raus


def test_state_ueberlebt_kaputte_datei(tmp_path):
    state.state_path(tmp_path).write_text("{kein json", encoding="utf-8")
    assert state.load_state(tmp_path) == {}


def test_state_merge_defaults():
    gemischt = state.merge_defaults(
        {"input_dir": "/default", "model": "large-v3", "devices": "bleibt"},
        {"input_dir": "/gemerkt", "unbekannt": "x"},
    )
    assert gemischt["input_dir"] == "/gemerkt"
    assert gemischt["model"] == "large-v3"
    assert gemischt["devices"] == "bleibt"
    assert "unbekannt" not in gemischt


# --- CUDA-Probe der Oberflaeche ---


def test_cuda_probe_wird_kurz_gecacht_und_laeuft_dann_neu(monkeypatch):
    """Ein Cache ohne Ablauf haelt eine geaenderte Installation fest.

    Nach 'uv sync --extra cu124' stuende sonst weiter 'cuda (nicht verfuegbar)' in der
    Oberflaeche, bis jemand den Server neu startet.
    """
    from audioscribe.ui import server

    proben = []
    monkeypatch.setattr(
        server.jobs,
        "probe_accelerator",
        lambda: (proben.append(1), {"cuda": len(proben) > 1, "mps": False, "backend": "faster-whisper"})[1],
    )
    monkeypatch.setattr(server, "_cuda_cache", None)

    uhr = [1000.0]
    monkeypatch.setattr(server.time, "monotonic", lambda: uhr[0])

    assert server._cuda() is False
    uhr[0] += server._CUDA_TTL_S - 1
    assert server._cuda() is False  # noch aus dem Cache
    assert len(proben) == 1

    uhr[0] += 2  # TTL abgelaufen
    assert server._cuda() is True
    assert len(proben) == 2


def test_state_theme_nur_bekannte_werte(tmp_path):
    state.save_state({"theme": "dark"}, tmp_path)
    assert state.load_state(tmp_path)["theme"] == "dark"
    state.save_state({"theme": "neon"}, tmp_path)  # unbekannt -> bleibt bei dark
    assert state.load_state(tmp_path)["theme"] == "dark"
    assert "theme" not in state.load_state(tmp_path / "leer")
    state.save_state({"theme": ""}, tmp_path / "leer")
    assert "theme" not in state.load_state(tmp_path / "leer")


# --- Routen der Oberflaeche ---


@pytest.fixture
def ui_client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from audioscribe.ui import server

    monkeypatch.setattr(state, "state_path", lambda cache_dir=None: tmp_path / "ui-state.json")
    return TestClient(server.create_app())


def test_index_injiziert_theme(ui_client):
    assert 'data-theme="system"' in ui_client.get("/").text
    assert ui_client.post("/api/state", json={"theme": "dark"}).status_code == 200
    assert 'data-theme="dark"' in ui_client.get("/").text
    assert ui_client.get("/api/defaults").json()["theme"] == "dark"


def test_static_assets(ui_client):
    css = ui_client.get("/static/style.css")
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")
    assert css.headers["cache-control"] == "no-cache"
    assert ui_client.get("/static/app.js").status_code == 200
    assert ui_client.get("/static/server.py").status_code == 404
    assert ui_client.get("/static/..%2Fserver.py").status_code == 404


# --- Reiter "Einstellungen": Standardordner und Umgebungs-Check (FR-47) ---


def test_defaults_liefern_analyse_ordner_und_state_merkt_ihn(ui_client, tmp_path):
    ziel = tmp_path / "analysen"
    ziel.mkdir()
    assert ui_client.post("/api/state", json={"agent_output_dir": str(ziel)}).status_code == 200
    data = ui_client.get("/api/defaults").json()
    assert Path(data["agent_output_dir"]) == ziel
    # Dieselbe Quelle wie der Reiter KI-Analyse
    assert Path(ui_client.get("/api/agent/defaults").json()["output_dir"]) == ziel


def test_defaults_verwerfen_fremden_analyse_ordner(ui_client, tmp_path):
    from audioscribe.config import settings

    ui_client.post("/api/state", json={"agent_output_dir": str(tmp_path / "weg" / "ganz" / "weg")})
    data = ui_client.get("/api/defaults").json()
    assert data["agent_output_dir"] == str(settings.agent_output_dir)


def test_index_hat_einstellungen_reiter_ohne_alte_ordnerfelder(ui_client):
    html = ui_client.get("/").text
    assert 'id="tabSet"' in html and 'data-tab="Set"' in html
    for feld in ("setIn", "setOut", "setAna", "envChecks", "transTarget", "liveTarget", "anaTarget"):
        assert f'id="{feld}"' in html
    for alt in ("inDir", "outDir", "anaOut", "pickIn", "pickOut", "pickAna"):
        assert f'id="{alt}"' not in html


def test_doctor_argv_ruft_json_modus():
    from audioscribe.ui.jobs import doctor_argv

    argv = doctor_argv("python")
    assert argv[0] == "python" and argv[-2:] == ["doctor", "--json"]
    assert "audioscribe.cli" in argv


def test_probe_environment_liest_letzte_json_zeile(monkeypatch):
    from audioscribe.ui import jobs

    class Proc:
        returncode = 1  # ein FAIL ist normal, kein Abbruch
        stdout = 'Warnung: irgendwas\n[{"status": "FAIL", "name": "ffmpeg", "detail": "fehlt"}, {"name": "x"}]\n'

    monkeypatch.setattr(jobs.subprocess, "run", lambda *a, **k: Proc())
    checks = jobs.probe_environment()
    assert checks == [
        {"status": "FAIL", "name": "ffmpeg", "detail": "fehlt"},
        {"status": "WARN", "name": "x", "detail": ""},
    ]


def test_probe_environment_ohne_json_ist_unbekannt(monkeypatch):
    from audioscribe.ui import jobs

    class Proc:
        returncode = 0
        stdout = "kein json\n"

    monkeypatch.setattr(jobs.subprocess, "run", lambda *a, **k: Proc())
    assert jobs.probe_environment() is None
    monkeypatch.setattr(jobs.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("x", 1)))
    assert jobs.probe_environment() is None


def test_environment_route_cacht_und_refresh_umgeht(ui_client, monkeypatch):
    from audioscribe.ui import server

    proben = []
    monkeypatch.setattr(
        server.jobs, "probe_environment",
        lambda: (proben.append(1), [{"status": "OK", "name": "Python", "detail": str(len(proben))}])[1],
    )
    monkeypatch.setattr(server, "_env_cache", None)

    erste = ui_client.get("/api/environment").json()
    assert erste["checks"][0]["name"] == "Python" and erste["checked_at"]
    zweite = ui_client.get("/api/environment").json()
    assert zweite["checks"] == erste["checks"] and len(proben) == 1
    dritte = ui_client.get("/api/environment?refresh=1").json()
    assert dritte["checks"][0]["detail"] == "2" and len(proben) == 2


def test_environment_route_meldet_unbekannt(ui_client, monkeypatch):
    from audioscribe.ui import server

    monkeypatch.setattr(server.jobs, "probe_environment", lambda: None)
    monkeypatch.setattr(server, "_env_cache", None)
    assert ui_client.get("/api/environment").json()["checks"] is None


def test_run_doctor_json_gibt_liste_aus(monkeypatch, capsys):
    from audioscribe import doctor

    def kaputt():
        raise RuntimeError("peng")

    kaputt.__name__ = "_check_kaputt"
    monkeypatch.setattr(
        doctor, "CHECKS",
        (lambda: doctor.CheckResult("OK", "Python", "3.12"), kaputt),
    )
    code = doctor.run_doctor(as_json=True)
    import json

    zeilen = json.loads(capsys.readouterr().out.strip())
    assert code == 1
    assert zeilen[0] == {"status": "OK", "name": "Python", "detail": "3.12"}
    assert zeilen[1]["status"] == "FAIL" and zeilen[1]["name"] == "kaputt" and "peng" in zeilen[1]["detail"]


def test_cli_doctor_kennt_json_flag():
    proc = subprocess.run(
        [sys.executable, "-m", "audioscribe.cli", "doctor", "--help"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0 and "--json" in proc.stdout


# --- Apple Silicon (PRD §19): Geraete, Probe, Pfade ---


def test_devices_enthalten_mps_und_argv_reicht_es_durch(tmp_path):
    from audioscribe.ui.jobs import DEVICES, JobOptions, build_argv

    assert "mps" in DEVICES
    argv = build_argv(tmp_path / "x.mp3", JobOptions(input_dir=tmp_path, output_dir=tmp_path, device="mps"), prefix=["a"])
    assert "--device=mps" in argv or "--device" in argv


def test_accelerator_probe_laeuft_in_eigenem_prozess():
    from audioscribe.ui.jobs import accelerator_probe_argv

    argv = accelerator_probe_argv("python")
    assert argv[0] == "python" and argv[1] == "-c"
    assert "mps" in argv[2] and "mlx_whisper" in argv[2] and "cuda" in argv[2]


def test_parse_accelerator_liest_letzte_zeile_und_waehlt_backend():
    from audioscribe.ui.jobs import parse_accelerator

    out = parse_accelerator('Warnung\n{"cuda": false, "mps": true, "mlx": true}')
    assert out == {"cuda": False, "mps": True, "backend": "mlx"}
    # Erzwungenes faster-whisper gewinnt; mit CUDA bleibt es faster-whisper.
    assert parse_accelerator('{"cuda": false, "mps": true, "mlx": true}', "faster-whisper")["backend"] == "faster-whisper"
    assert parse_accelerator('{"cuda": true, "mps": false, "mlx": true}')["backend"] == "faster-whisper"
    assert parse_accelerator("") is None
    assert parse_accelerator("kein json") is None
    assert parse_accelerator("[1, 2]") is None


def test_probe_accelerator_und_probe_cuda(monkeypatch):
    from audioscribe.ui import jobs

    class Proc:
        returncode = 0
        stdout = '{"cuda": false, "mps": true, "mlx": false}\n'

    monkeypatch.setattr(jobs.subprocess, "run", lambda *a, **k: Proc())
    assert jobs.probe_accelerator() == {"cuda": False, "mps": True, "backend": "faster-whisper"}
    assert jobs.probe_cuda() is False
    Proc.returncode = 1
    assert jobs.probe_accelerator() is None and jobs.probe_cuda() is None


def test_to_native_mac_laesst_windows_pfade_in_ruhe():
    assert browse.to_native(r"C:\Users\x", windows=False, mac=True) == r"C:\Users\x"
    assert browse.to_native(' "/Users/x/Downloads" ', windows=False, mac=True) == "/Users/x/Downloads"
    # Ohne mac-Flag bleibt das WSL-Verhalten.
    assert browse.to_native(r"C:\Users\x", windows=False, mac=False) == "/mnt/c/Users/x"


def test_quick_links_mac_volumes_und_nutzerordner(tmp_path):
    home = tmp_path / "home"
    (home / "Desktop").mkdir(parents=True)
    (home / "Downloads").mkdir()
    volumes = tmp_path / "Volumes"
    (volumes / "USB").mkdir(parents=True)
    (volumes / "Macintosh HD").symlink_to("/")
    mnt = tmp_path / "mnt"
    (mnt / "c").mkdir(parents=True)  # darf auf dem Mac nicht als "Windows C:" erscheinen
    root = tmp_path / "projekt"
    root.mkdir()
    links = browse.quick_links(
        project_root=root,
        input_dir=root,
        output_dir=tmp_path / "fehlt",
        home=home,
        mnt_root=mnt,
        volumes_root=volumes,
        windows=False,
        mac=True,
    )
    assert [label for label, _ in links] == ["Projekt", "Home", "Schreibtisch", "Downloads", "Volume USB"]
