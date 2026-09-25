"""Kompatibilitaets-Shims fuer den ML-Stack."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from audioscribe.config import settings

_TORCH_LOAD_PATCHED = False
_HF_HUB_PATCHED = False
_LAZY_MODULE_PATCHED = False

# ctranslate2 4.4.0 (von WhisperX gepinnt, <4.5) ist gegen cuDNN 8 gebaut, waehrend
# torch 2.6 cuDNN 9 mitbringt. Wir stellen die cuDNN-8-Libs einmalig separat bereit.
CUDNN8_VERSION = "8.9.7.29"
_LD_MARKER = "AUDIOSCRIBE_LD_BOOTSTRAPPED"


def apply_torch_load_compat() -> None:
    """Stellt das vor-PyTorch-2.6-Verhalten von ``torch.load`` wieder her.

    PyTorch >= 2.6 hat den Default von ``torch.load(..., weights_only=True)``
    umgestellt. Die pyannote-Checkpoints (VAD fuer WhisperX sowie die
    Diarisierung) serialisieren ``omegaconf``-Objekte (``ListConfig`` etc.) und
    lassen sich mit ``weights_only=True`` nicht laden -> ``UnpicklingError``.

    Da in dieser Pipeline ``torch.load`` ausschliesslich auf Modellgewichte aus
    vertrauenswuerdiger, lokaler Quelle (offizielle Hugging-Face-Repos) angewandt
    wird, erzwingen wir ``weights_only=False``. Das ueberschreibt bewusst auch
    Aufrufer wie Lightning/pyannote, die intern explizit ``weights_only=True``
    setzen (sonst greift ein blosser Default nicht). Idempotent.
    """
    global _TORCH_LOAD_PATCHED
    if _TORCH_LOAD_PATCHED:
        return

    import torch

    _orig_load = torch.load

    def _load(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["weights_only"] = False
        return _orig_load(*args, **kwargs)

    torch.load = _load  # type: ignore[assignment]
    _TORCH_LOAD_PATCHED = True


def apply_hf_hub_compat() -> None:
    """Uebersetzt das veraltete ``use_auth_token``-Argument zu ``token``.

    pyannote.audio 3.x ruft ``hf_hub_download(..., use_auth_token=...)`` auf, aber
    neuere ``huggingface_hub``-Versionen (>= 1.x) kennen nur noch ``token`` ->
    ``TypeError: hf_hub_download() got an unexpected keyword argument 'use_auth_token'``.
    Wir wrappen ``hf_hub_download`` so, dass ``use_auth_token`` auf ``token`` gemappt
    wird, und ziehen die Referenz in bereits importierten Modulen (pyannote) nach.
    Idempotent.

    Nebenbei spart der Wrapper Netzwerkrunden: pyannote fragt je Modell-Datei den Hub nach
    der aktuellen Revision, obwohl sie längst im Cache liegt. Setzt der Aufrufer
    ``local_files_only`` nicht selbst, versuchen wir erst den Cache und gehen nur dann
    online, wenn dort etwas fehlt.
    """
    global _HF_HUB_PATCHED
    if _HF_HUB_PATCHED:
        return

    import functools
    import sys

    import huggingface_hub

    orig = huggingface_hub.hf_hub_download

    @functools.wraps(orig)
    def _download(*args, **kwargs):  # type: ignore[no-untyped-def]
        if "use_auth_token" in kwargs:
            token = kwargs.pop("use_auth_token")
            kwargs.setdefault("token", token)
        if "local_files_only" not in kwargs:
            try:
                return orig(*args, local_files_only=True, **kwargs)
            except Exception:  # noqa: BLE001 - nicht im Cache -> regulaer (online) laden
                pass
        return orig(*args, **kwargs)

    huggingface_hub.hf_hub_download = _download
    # pyannote-Module, die ``from huggingface_hub import hf_hub_download`` gemacht haben,
    # nachziehen. Bewusst nur ``pyannote.*`` antasten: ein Scan ueber ALLE sys.modules
    # wuerde bei lazy/deprecated Modulen (speechbrain/torchaudio) deren Warnungen ausloesen.
    for name, module in list(sys.modules.items()):
        if module is None or not name.startswith("pyannote"):
            continue
        try:
            if getattr(module, "hf_hub_download", None) is orig:
                module.hf_hub_download = _download  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - defensive
            pass
    _HF_HUB_PATCHED = True


def apply_speechbrain_lazy_compat() -> None:
    """Verhindert, dass ``inspect`` speechbrains Lazy-Module nachlaedt (Windows-Bug).

    pytorch_lightning prueft beim Laden eines Checkpoints per ``inspect.stack()``, ob
    gerade TorchScript laeuft. ``inspect.getmodule`` fasst dabei jedes Modul in
    ``sys.modules`` mit ``hasattr(module, "__file__")`` an - und speechbrain legt dort
    Platzhalter ab, die bei JEDEM Attributzugriff nachladen. Fuer
    ``speechbrain.integrations.k2_fsa`` scheitert das mangels ``k2``-Paket, und weil
    ``hasattr`` nur AttributeError schluckt, reisst der ImportError den ganzen Lauf mit -
    beim Laden des VAD-Modells, also mitten in Stufe 3.

    speechbrain kennt den Fall und bricht Zugriffe aus ``inspect.py`` selbst ab, prueft
    den Aufrufer aber mit ``filename.endswith("/inspect.py")`` - mit Schraegstrich. Unter
    Windows heisst der Pfad ``...\\Lib\\inspect.py``, der Schutz greift also nie. Wir
    setzen genau diese Pruefung trennzeichen-neutral davor. Idempotent; ohne speechbrain
    passiert nichts.
    """
    global _LAZY_MODULE_PATCHED
    if _LAZY_MODULE_PATCHED:
        return
    try:
        from speechbrain.utils.importutils import LazyModule
    except Exception:  # noqa: BLE001 - ohne speechbrain gibt es nichts zu reparieren
        return

    orig = LazyModule.__getattr__

    def _getattr(self, attr):  # type: ignore[no-untyped-def]
        try:
            caller = sys._getframe(1).f_code.co_filename
        except (AttributeError, ValueError):  # kein CPython-Stack -> wie gehabt weiter
            return orig(self, attr)
        if os.path.basename(caller) == "inspect.py":
            raise AttributeError(attr)
        return orig(self, attr)

    LazyModule.__getattr__ = _getattr  # type: ignore[method-assign]
    _LAZY_MODULE_PATCHED = True


def clear_execstack_flag(path: Path) -> bool:
    """Loescht das Executable-Stack-Flag (PF_X) im ``PT_GNU_STACK``-Header einer ELF64-Lib.

    Liefert True, wenn die Datei geaendert wurde; False, wenn nichts zu tun war
    (kein ELF64, kein GNU_STACK-Header oder Flag bereits sauber).
    """
    import struct

    pt_gnu_stack = 0x6474E551
    with path.open("r+b") as f:
        ident = f.read(16)
        # Nur little-endian ELF64 (x86_64-Wheels); alles andere unangetastet lassen.
        if ident[:4] != b"\x7fELF" or ident[4] != 2 or ident[5] != 1:
            return False
        f.seek(0x20)
        (e_phoff,) = struct.unpack("<Q", f.read(8))
        f.seek(0x36)
        e_phentsize, e_phnum = struct.unpack("<HH", f.read(4))
        for i in range(e_phnum):
            off = e_phoff + i * e_phentsize
            f.seek(off)
            p_type, p_flags = struct.unpack("<II", f.read(8))
            if p_type != pt_gnu_stack:
                continue
            if not p_flags & 0x1:  # PF_X nicht gesetzt -> nichts zu tun
                return False
            f.seek(off + 4)
            f.write(struct.pack("<I", p_flags & ~0x1))
            return True
    return False


def ensure_ctranslate2_loadable(log=None) -> None:
    """Repariert das ctranslate2-Wheel fuer neuere glibc (>= 2.41, z.B. Ubuntu 25.x).

    Die gebundelte ``libctranslate2`` (4.4.0) traegt ein ``PT_GNU_STACK``-Header-Flag
    ``RWE`` (Build-Artefakt, tatsaechlich wird kein ausfuehrbarer Stack benoetigt).
    Neuere glibc verweigert solche Libraries beim ``dlopen`` hart
    ("cannot enable executable stack as shared object requires"). Wir loeschen das
    X-Bit einmalig direkt in der installierten ``.so`` (idempotent, wie
    ``execstack -c``). Muss VOR dem ersten ``import ctranslate2`` laufen.
    """
    log = log or (lambda _m: None)
    try:
        import importlib.util

        spec = importlib.util.find_spec("ctranslate2")
        if spec is None or not spec.origin:
            return
        libs_dir = Path(spec.origin).parent.parent / "ctranslate2.libs"
        if not libs_dir.is_dir():
            return
        for so in libs_dir.glob("*.so*"):
            if clear_execstack_flag(so):
                log(f"ctranslate2: Executable-Stack-Flag entfernt ({so.name}, glibc >= 2.41)")
    except Exception:  # noqa: BLE001 - best effort; der Import schlaegt sonst ohnehin fehl
        pass


def ensure_pkg_resources(log=None) -> None:
    """Legt ein minimales ``pkg_resources`` an, falls setuptools keines mehr mitbringt.

    ctranslate2 < 4.5 macht beim Import **unter Windows** ein ``import pkg_resources``,
    einzig um sein eigenes Paketverzeichnis zu finden und die DLLs daraus zu laden.
    ``pkg_resources`` kam bisher mit setuptools mit, ist dort aber seit Version 81
    abgekuendigt und in 82 entfernt -> ``ModuleNotFoundError: No module named
    'pkg_resources'`` mitten in Stufe 3 (Transkription). Ein Upgrade von ctranslate2
    scheidet aus: WhisperX pinnt ``ctranslate2<4.5.0``.

    Ersetzt wird nur die eine tatsaechlich benutzte Funktion (``resource_filename``).
    Muss VOR dem ersten ``import ctranslate2`` laufen; ausserhalb von Windows und bei
    vorhandenem setuptools passiert nichts. Idempotent.
    """
    log = log or (lambda _m: None)
    if os.name != "nt" or "pkg_resources" in sys.modules:
        return

    import importlib.util
    import types

    try:
        if importlib.util.find_spec("pkg_resources") is not None:
            return
    except (ImportError, ValueError):  # kaputte/halbe Installation -> Shim setzen
        pass

    def resource_filename(package: str, resource: str) -> str:
        spec = importlib.util.find_spec(package)
        if spec is None or not spec.origin:
            raise ImportError(f"Paketverzeichnis nicht auffindbar: {package}")
        return str(Path(spec.origin).parent / resource)

    module = types.ModuleType("pkg_resources")
    module.resource_filename = resource_filename  # type: ignore[attr-defined]
    sys.modules["pkg_resources"] = module
    log("pkg_resources fehlt (setuptools >= 81) - Ersatz fuer ctranslate2 bereitgestellt")


# Windows legt die DLLs unter bin/, Linux die .so-Dateien unter lib/ - beide bekommen ein
# eigenes Verzeichnis, damit ein Wechsel des Systems im selben Cache nichts vermischt.
def _cudnn8_lib_dir() -> Path:
    return settings.cache_dir / "cudnn8" / ("bin" if os.name == "nt" else "lib")


# Nur die Inferenz-Bibliotheken werden entpackt: die *_train*-Varianten (rund 230 MB)
# braucht ctranslate2 nie, und die Dateien sind einzeln mehrere hundert MB gross.
_CUDNN8_WINDOWS_DLLS = ("cudnn64_8.dll", "cudnn_ops_infer64_8.dll", "cudnn_cnn_infer64_8.dll",
                        "cudnn_adv_infer64_8.dll")


def ensure_cudnn8(log=None) -> Path:
    """Stellt die cuDNN-8-Bibliotheken bereit (einmaliger Download), liefert ihr Lib-Verzeichnis.

    Laedt das ``nvidia-cudnn-cu12``-Wheel (cuDNN 8.9.x) von PyPI und entpackt die
    Inferenz-Bibliotheken in ein eigenes Cache-Verzeichnis. Das kollidiert NICHT mit dem
    von torch mitgebrachten cuDNN 9: die Dateinamen tragen die Hauptversion
    (``.so.8`` vs. ``.so.9`` bzw. ``64_8.dll`` vs. ``64_9.dll``).

    Es gibt das Wheel fuer Linux UND fuer Windows - unter Windows bringt ctranslate2 zwar
    ``cudnn64_8.dll`` mit, das ist aber nur der Verteiler; die eigentlichen
    ``cudnn_*_infer64_8.dll`` fehlen, und ohne sie stirbt der Lauf beim Modell-Laden mit
    "Could not locate cudnn_ops_infer64_8.dll".
    """
    log = log or (lambda _m: None)
    windows = os.name == "nt"
    lib_dir = _cudnn8_lib_dir()
    sentinel = lib_dir / ("cudnn_ops_infer64_8.dll" if windows else "libcudnn_ops_infer.so.8")
    if sentinel.exists():
        return lib_dir

    import json
    import tempfile
    import urllib.request
    import zipfile

    lib_dir.mkdir(parents=True, exist_ok=True)
    log(f"Lade cuDNN 8 ({CUDNN8_VERSION}) fuer ctranslate2 (einmalig, ~700 MB)...")
    meta_url = f"https://pypi.org/pypi/nvidia-cudnn-cu12/{CUDNN8_VERSION}/json"
    with urllib.request.urlopen(meta_url) as resp:  # noqa: S310 - PyPI ist vertrauenswuerdig
        meta = json.load(resp)
    plattform = "win_amd64" if windows else "manylinux"
    wheel_url = next(
        u["url"]
        for u in meta["urls"]
        if u["filename"].endswith(".whl") and plattform in u["filename"]
    )
    # Fortschritt melden: 700 MB ohne jede Rueckmeldung sehen im Protokoll wie ein
    # Haenger aus - gerade in der Stapel-Oberflaeche, wo nur das Log sichtbar ist.
    def _fortschritt(bloecke: int, blockgroesse: int, gesamt: int) -> None:
        if gesamt <= 0:
            return
        anteil = min(100, int(100 * bloecke * blockgroesse / gesamt))
        if anteil >= _fortschritt.naechste:  # type: ignore[attr-defined]
            log(f"  cuDNN 8: {anteil}% ({gesamt // (1024 * 1024)} MB)")
            _fortschritt.naechste = anteil + 20  # type: ignore[attr-defined]

    _fortschritt.naechste = 0  # type: ignore[attr-defined]

    with tempfile.TemporaryDirectory() as td:
        whl = Path(td) / "cudnn8.whl"
        urllib.request.urlretrieve(wheel_url, whl, reporthook=_fortschritt)  # noqa: S310
        with zipfile.ZipFile(whl) as z:
            for name in z.namelist():
                if name.endswith("/"):
                    continue
                datei = Path(name).name
                if windows:
                    if "/cudnn/bin/" in name and datei in _CUDNN8_WINDOWS_DLLS:
                        (lib_dir / datei).write_bytes(z.read(name))
                elif "/cudnn/lib/" in name and ".so" in name:
                    (lib_dir / datei).write_bytes(z.read(name))
    log(f"cuDNN 8 entpackt nach {lib_dir}")
    return lib_dir


# Handles der registrierten DLL-Verzeichnisse: Werden sie eingesammelt, macht Windows die
# Registrierung rueckgaengig - deshalb halten wir sie fuer die Prozesslaufzeit fest.
_DLL_DIR_HANDLES: list = []


def _add_windows_dll_dirs(lib_dir: Path, log) -> None:
    """Macht cuDNN 8 und die cuBLAS-DLLs von torch fuer ctranslate2 auffindbar.

    BEIDE Wege sind noetig, und zwar aus verschiedenen Gruenden:

    * ``os.add_dll_directory`` gilt fuer DLLs, die Python selbst laedt (ctypes und die
      Importmaschinerie nutzen die eingeschraenkte Suche mit ``LOAD_LIBRARY_SEARCH_*``).
    * ``PATH`` gilt fuer DLLs, die eine bereits geladene DLL ihrerseits nachlaedt. Genau
      das tut ``cudnn64_8.dll``: es ist nur ein Verteiler und holt sich
      ``cudnn_ops_infer64_8.dll`` per ``LoadLibrary`` mit blossem Namen - dieser Aufruf
      kennt die per ``add_dll_directory`` registrierten Verzeichnisse NICHT und sucht in
      der klassischen Reihenfolge, in der PATH das letzte Glied ist.

    Ohne den PATH-Teil scheitert der Lauf trotz vorhandener Datei mit
    "Could not locate cudnn_ops_infer64_8.dll".
    """
    import sysconfig

    purelib = Path(sysconfig.get_paths()["purelib"])
    # cuDNN 8 zuerst; cuBLAS liegt unter Windows in torch/lib (nicht in nvidia/cublas).
    verzeichnisse = [p for p in (lib_dir, purelib / "torch" / "lib") if p.is_dir()]
    for pfad in verzeichnisse:
        try:
            _DLL_DIR_HANDLES.append(os.add_dll_directory(str(pfad)))
        except OSError as exc:  # noqa: PERF203 - defensiv, darf den Lauf nicht kippen
            log(f"DLL-Verzeichnis nicht nutzbar ({pfad}): {exc}")

    pfade = os.environ.get("PATH", "").split(os.pathsep)
    neu = [str(p) for p in verzeichnisse if str(p) not in pfade]
    if neu:
        os.environ["PATH"] = os.pathsep.join([*neu, *pfade])
    log(f"cuDNN 8 bereit: {lib_dir}")


def ensure_native_libs(log=None) -> None:
    """Macht die cuDNN-8-Libs (fuer ctranslate2) ueber LD_LIBRARY_PATH auffindbar.

    LD_LIBRARY_PATH wirkt nur, wenn es vor Prozessstart gesetzt ist; darum setzen wir
    es und starten den Prozess einmalig per ``execv`` neu (Marker verhindert Schleifen).
    Muss VOR dem Import von torch/whisperx aufgerufen werden.

    Unter Windows ist es einfacher: ``os.add_dll_directory`` wirkt sofort im laufenden
    Prozess, ein Neustart entfaellt. Das zurueckgegebene Handle muss allerdings am Leben
    bleiben - wird es eingesammelt, nimmt Windows das Verzeichnis wieder aus der Suche.
    """
    log = log or (lambda _m: None)
    lib_dir = ensure_cudnn8(log)

    if os.name == "nt":
        _add_windows_dll_dirs(lib_dir, log)
        return

    if os.environ.get(_LD_MARKER) == "1":
        return

    import sysconfig

    # cuDNN 8 benoetigt cuBLAS (von torch mitgebracht) -> dessen Verzeichnis mit aufnehmen.
    purelib = Path(sysconfig.get_paths()["purelib"])
    candidates = [str(lib_dir), str(purelib / "nvidia" / "cublas" / "lib")]

    current = os.environ.get("LD_LIBRARY_PATH", "")
    parts = current.split(os.pathsep) if current else []
    prepend = [d for d in candidates if d not in parts and Path(d).exists()]
    os.environ["LD_LIBRARY_PATH"] = os.pathsep.join([*prepend, *parts])
    os.environ[_LD_MARKER] = "1"

    os.execv(sys.executable, [sys.executable, *sys.argv])
