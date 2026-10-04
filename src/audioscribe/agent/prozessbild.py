"""Prozessbild: das Mermaid-Diagramm der Prozessdoku als PNG und SVG (FR-35).

Mermaid zeichnet mit JavaScript - zum Rendern braucht es eine Browser-Engine. Statt
Playwright (eigener Chromium, unter WSL fehlen dessen Systembibliotheken -> sudo) wird
der ohnehin installierte **Edge oder Chrome headless** aufgerufen, unter WSL die
Windows-Exe ueber ``/mnt/c``. Die Mermaid-Bibliothek liegt im Paket (``assets/``),
damit das Rendern offline und hinter Firmen-Proxys funktioniert.

Ablauf je ``prozessbild*.mmd``: Render-Seite in einen temporaeren Ordner schreiben,
Browser mit ``--dump-dom`` starten, das Ergebnis-JSON (SVG + PNG als data-URL) aus
dem ``<pre id="out">`` des DOM lesen, Dateien schreiben. Fehler werden gemeldet, nie
geworfen: das Prozessbild ist eine Zugabe und darf eine Analyse nicht kippen.
"""

from __future__ import annotations

import base64
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

ASSETS = Path(__file__).parent / "assets"
MMD_NAME = "prozessbild.mmd"
_TMP_DIR = ".prozessbild-tmp"
_TIMEOUT_S = 90

_MERMAID_BLOCK_RE = re.compile(r"^```mermaid[ \t]*\r?\n(.*?)^```[ \t]*$", re.S | re.M)
_OUT_RE = re.compile(r'<pre id="out">(.*?)</pre>', re.S)

# Relative Installationsorte unter Windows (C:\ bzw. /mnt/c/ unter WSL).
_WINDOWS_BROWSERS = (
    "Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "Program Files/Microsoft/Edge/Application/msedge.exe",
    "Program Files/Google/Chrome/Application/chrome.exe",
    "Program Files (x86)/Google/Chrome/Application/chrome.exe",
)
_LINUX_BROWSERS = ("chromium", "chromium-browser", "google-chrome", "microsoft-edge")
# Relative Installationsorte unter macOS (/Applications bzw. ~/Applications).
_MAC_BROWSERS = (
    "Google Chrome.app/Contents/MacOS/Google Chrome",
    "Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "Chromium.app/Contents/MacOS/Chromium",
    "Brave Browser.app/Contents/MacOS/Brave Browser",
)

_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><script src="mermaid.min.js"></script></head>
<body><pre id="out">pending</pre><script>
const SRC = __SRC__;
const MODE = __MODE__;  // 'mermaid': Quelltext rendern | 'svg': fertiges SVG nur nach PNG
(async () => {
  const out = document.getElementById('out');
  try {
    let svg = SRC;
    if (MODE === 'mermaid') {
      // htmlLabels:false -> reine SVG-Texte: Word/PowerPoint-tauglich, kein foreignObject.
      mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', flowchart: { htmlLabels: false } });
      svg = (await mermaid.render('prozessbild', SRC)).svg;
    }
    const box = document.createElement('div');
    box.innerHTML = svg;
    document.body.appendChild(box);
    const el = box.querySelector('svg');
    const vb = el.viewBox.baseVal;
    const w = Math.ceil(vb.width), h = Math.ceil(vb.height);
    // 2-fach fuer scharfe PNGs; sehr grosse Diagramme so weit abregeln, dass der
    // Canvas unter der Browser-Grenze (~16k Pixel je Kante) bleibt.
    const scale = Math.max(0.5, Math.min(2, 12000 / Math.max(w, h)));
    // Mermaid schreibt width="100%" ohne Hoehe - Bildbetrachter wie die Windows-Fotos-
    // App oder die Explorer-Vorschau zeigen das als leere Flaeche. Feste Pixelmasse.
    el.setAttribute('width', w);
    el.setAttribute('height', h);
    el.style.removeProperty('max-width');
    const text = new XMLSerializer().serializeToString(el);
    const img = new Image();
    // data-URL statt Blob: eine Blob-Quelle "verunreinigt" den Canvas unter file://.
    img.src = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(text)));
    await img.decode();
    const c = document.createElement('canvas');
    c.width = Math.round(w * scale);
    c.height = Math.round(h * scale);
    const ctx = c.getContext('2d');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.drawImage(img, 0, 0, c.width, c.height);
    out.textContent = JSON.stringify({ svg: text, png: c.toDataURL('image/png'), width: w, height: h });
  } catch (e) {
    out.textContent = JSON.stringify({ error: String((e && e.message) || e) });
  }
})();
</script></body></html>
"""


# --- Mermaid-Quelle ------------------------------------------------------------------


def extract_mermaid(markdown: str) -> list[str]:
    """Inhalte aller ```mermaid-Codebloecke (leere werden uebergangen)."""
    return [m.group(1).strip() for m in _MERMAID_BLOCK_RE.finditer(markdown) if m.group(1).strip()]


def ensure_source(workspace: Path, docs: Sequence[str]) -> list[Path]:
    """Alle ``prozessbild*.mmd`` im Ergebnisordner - notfalls aus den Dokumenten erzeugt.

    Normalerweise schreibt der Agent ``prozessbild.mmd`` selbst (Systemprompt). Fehlt
    sie, wird der erste Mermaid-Block der Dokumente uebernommen; Dokumente mit
    "prozess" im Namen zuerst.
    """
    ws = Path(workspace)
    vorhanden = sorted(ws.glob("prozessbild*.mmd"), key=_mmd_order)
    if vorhanden:
        return vorhanden
    kandidaten = sorted(
        (d for d in docs if d.lower().endswith(".md")),
        key=lambda d: (0 if "prozess" in Path(d).name.lower() else 1, d),
    )
    for rel in kandidaten:
        try:
            text = (ws / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        blocks = extract_mermaid(text)
        if blocks:
            target = ws / MMD_NAME
            target.write_text(blocks[0] + "\n", encoding="utf-8")
            return [target]
    return []


def _mmd_order(path: Path) -> tuple[int, str]:
    """prozessbild.mmd zuerst, dann prozessbild-2.mmd, -3, ... numerisch."""
    m = re.fullmatch(r"prozessbild(?:-(\d+))?\.mmd", path.name)
    return (int(m.group(1) or 1) if m else 10_000, path.name)


# --- Browser -----------------------------------------------------------------------


def _is_wsl() -> bool:
    return sys.platform.startswith("linux") and "microsoft" in os.uname().release.lower()


def find_browser(
    *,
    env: dict[str, str] | None = None,
    platform: str | None = None,
    wsl: bool | None = None,
    exists: Callable[[Path], bool] = Path.is_file,
    which: Callable[[str], str | None] = shutil.which,
    home: Path | None = None,
) -> Path | None:
    """Edge/Chrome/Chromium fuer das headless Rendern; ``None`` wenn keiner da ist.

    Der Browser ist die einzige Komponente ausserhalb von pip - und optional (nur fuer das
    Prozessbild). Safari kann nicht headless rendern, darum auch auf dem Mac Chrome/Edge.
    """
    env = os.environ if env is None else env
    override = env.get("AUDIOSCRIBE_BROWSER", "").strip()
    if override:
        return Path(override)
    platform = sys.platform if platform is None else platform
    if platform == "darwin":
        roots = (Path("/Applications"), (Path.home() if home is None else Path(home)) / "Applications")
        for root in roots:
            for rel in _MAC_BROWSERS:
                candidate = root / rel
                if exists(candidate):
                    return candidate
        for name in _LINUX_BROWSERS:
            found = which(name)
            if found:
                return Path(found)
        return None
    windows_root: Path | None = None
    if platform == "win32":
        windows_root = Path(env.get("SystemDrive", "C:") + "/")
    elif _is_wsl() if wsl is None else wsl:
        windows_root = Path("/mnt/c")
    if windows_root is not None:
        for rel in _WINDOWS_BROWSERS:
            candidate = windows_root / rel
            if exists(candidate):
                return candidate
        if platform == "win32":
            return None
    for name in _LINUX_BROWSERS:
        found = which(name)
        if found:
            return Path(found)
    return None


def is_windows_exe_from_wsl(browser: Path) -> bool:
    return sys.platform != "win32" and browser.suffix.lower() == ".exe"


def to_browser_path(path: Path, browser: Path) -> str:
    """Pfad so, wie der Browser ihn versteht (Windows-Exe unter WSL -> ``wslpath -w``)."""
    if not is_windows_exe_from_wsl(browser):
        return str(path)
    return subprocess.run(
        ["wslpath", "-w", str(path)], capture_output=True, text=True, check=True
    ).stdout.strip()


def _profile_dir(browser: Path) -> str:
    """Eigenes Browser-Profil, getrennt vom Profil des Nutzers.

    Fuer die Windows-Exe unter WSL im Windows-%TEMP%: auf einem \\\\wsl.localhost-Pfad
    scheitert Edge an Dateisperren seines Absturzberichts.
    """
    if is_windows_exe_from_wsl(browser):
        try:
            temp = subprocess.run(
                ["cmd.exe", "/c", "echo %TEMP%"],
                capture_output=True, text=True, timeout=15, cwd="/mnt/c",
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            temp = ""
        if temp and "%" not in temp:
            return temp + "\\audioscribe-prozessbild"
    return str(Path(tempfile.gettempdir()) / "audioscribe-prozessbild")


def browser_argv(browser: Path, url: str, profile_dir: str) -> list[str]:
    return [
        str(browser),
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        f"--user-data-dir={profile_dir}",
        # Laesst das asynchrone Rendern (Mermaid, Bild-Dekodierung) vor dem DOM-Abzug laufen.
        "--virtual-time-budget=15000",
        "--dump-dom",
        url,
    ]


# --- Rendern -----------------------------------------------------------------------


def build_page(source: str, mode: str = "mermaid") -> str:
    """Render-Seite: ``mode="mermaid"`` rendert Quelltext, ``"svg"`` wandelt fertiges SVG um."""
    # JSON ist gueltiges JS; "</" entschaerfen, damit der Quelltext das <script> nicht schliesst.
    def js(value: str) -> str:
        return json.dumps(value).replace("</", "<\\/")

    return _PAGE.replace("__SRC__", js(source)).replace("__MODE__", js(mode))


def parse_dump(dom: str) -> dict:
    """Ergebnis-JSON aus dem abgezogenen DOM; ``{"error": ...}`` bei jedem Problem."""
    m = _OUT_RE.search(dom)
    if not m:
        return {"error": "Browser lieferte keine Ergebnisseite."}
    raw = html.unescape(m.group(1)).strip()
    if raw == "pending":
        return {"error": "Rendern nicht rechtzeitig fertig geworden."}
    try:
        data = json.loads(raw)
    except ValueError:
        return {"error": "Ergebnis nicht lesbar."}
    return data if isinstance(data, dict) else {"error": "Ergebnis nicht lesbar."}


def run_page(page_html: str, workdir: Path, browser: Path) -> dict:
    """Render-Seite im Browser ausfuehren und ihr Ergebnis-JSON liefern.

    Die Seite liegt dabei kurz in ``<workdir>/.prozessbild-tmp/``. ``RuntimeError``, wenn
    der Browser nicht startet oder nicht antwortet; Render-Fehler stehen als ``error``
    im Ergebnis.
    """
    tmp = Path(workdir) / _TMP_DIR
    tmp.mkdir(exist_ok=True)
    try:
        shutil.copy2(ASSETS / "mermaid.min.js", tmp / "mermaid.min.js")
        page = tmp / "render.html"
        page.write_text(page_html, encoding="utf-8")
        argv = browser_argv(browser, to_browser_path(page, browser), _profile_dir(browser))
        try:
            proc = subprocess.run(  # noqa: S603 - fester Aufruf, Pfade aus dem Programm
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Browser antwortet nicht ({_TIMEOUT_S}s).") from exc
        except OSError as exc:
            raise RuntimeError(f"Browser nicht startbar: {exc}") from exc
        return parse_dump(proc.stdout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _write_png(data_url: str, path: Path) -> None:
    path.write_bytes(base64.b64decode(data_url.split(",", 1)[1]))


def render(mmd: Path, browser: Path) -> tuple[Path, Path]:
    """``prozessbild.mmd`` -> ``prozessbild.svg`` + ``prozessbild.png`` daneben.

    ``RuntimeError`` mit lesbarer Meldung, wenn es nicht klappt.
    """
    mmd = Path(mmd)
    source = mmd.read_text(encoding="utf-8").strip()
    if not source:
        raise RuntimeError(f"{mmd.name} ist leer.")
    data = run_page(build_page(source), mmd.parent, browser)
    if "error" in data:
        raise RuntimeError(f"Mermaid-Fehler in {mmd.name}: {data['error']}")
    svg_path, png_path = mmd.with_suffix(".svg"), mmd.with_suffix(".png")
    svg_path.write_text(data["svg"], encoding="utf-8")
    _write_png(data["png"], png_path)
    return svg_path, png_path


def svg_to_png(svg: str, png_path: Path, browser: Path) -> Path:
    """Fertiges SVG (z. B. das BPMN-Bild) ueber den Browser als PNG speichern."""
    png_path = Path(png_path)
    data = run_page(build_page(svg, mode="svg"), png_path.parent, browser)
    if "error" in data:
        raise RuntimeError(f"PNG-Umwandlung fehlgeschlagen: {data['error']}")
    _write_png(data["png"], png_path)
    return png_path


def erzeuge_prozessbilder(
    workspace: Path,
    docs: Sequence[str] = (),
    *,
    log: Callable[[str], None] = print,
    browser: Path | None = None,
) -> list[Path]:
    """Einstieg fuer Runner und CLI: Quellen sichern, alle Prozessbilder rendern.

    Gibt die erzeugten Bilddateien zurueck; Probleme erscheinen nur im Protokoll.
    """
    ws = Path(workspace)
    quellen = ensure_source(ws, docs)
    if not quellen:
        log("[Prozessbild] Kein Mermaid-Diagramm gefunden - kein Prozessbild erzeugt.")
        return []
    browser = browser or find_browser()
    if browser is None:
        log(
            "[Prozessbild] Kein Edge/Chrome/Chromium gefunden - nur prozessbild.mmd erzeugt. "
            "Pfad ueber AUDIOSCRIBE_BROWSER angeben."
        )
        return []
    erzeugt: list[Path] = []
    for mmd in quellen:
        try:
            svg, png = render(mmd, browser)
        except RuntimeError as exc:
            log(f"[Prozessbild] {exc}")
            continue
        erzeugt += [png, svg]
        log(f"[Prozessbild] {png.name}, {svg.name}")
    return erzeugt
