"""Kompatibilitaets-Shims fuer den ML-Stack."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from audioscribe.config import settings

_TORCH_LOAD_PATCHED = False
_HF_HUB_PATCHED = False

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


def _cudnn8_lib_dir() -> Path:
    return settings.cache_dir / "cudnn8" / "lib"


def ensure_cudnn8(log=None) -> Path:
    """Stellt die cuDNN-8-Bibliotheken bereit (einmaliger Download), liefert ihr Lib-Verzeichnis.

    Laedt das ``nvidia-cudnn-cu12``-Wheel (cuDNN 8.9.x) von PyPI und entpackt nur die
    ``.so``-Dateien in ein eigenes Cache-Verzeichnis. Das kollidiert NICHT mit dem von
    torch mitgebrachten cuDNN 9 (andere SO-Namen, ``.so.8`` vs. ``.so.9``).
    """
    log = log or (lambda _m: None)
    lib_dir = _cudnn8_lib_dir()
    sentinel = lib_dir / "libcudnn_ops_infer.so.8"
    if sentinel.exists():
        return lib_dir

    import json
    import tempfile
    import urllib.request
    import zipfile

    lib_dir.mkdir(parents=True, exist_ok=True)
    log(f"Lade cuDNN 8 ({CUDNN8_VERSION}) fuer ctranslate2 (einmalig, ~ein paar 100 MB)...")
    meta_url = f"https://pypi.org/pypi/nvidia-cudnn-cu12/{CUDNN8_VERSION}/json"
    with urllib.request.urlopen(meta_url) as resp:  # noqa: S310 - PyPI ist vertrauenswuerdig
        meta = json.load(resp)
    wheel_url = next(
        u["url"]
        for u in meta["urls"]
        if u["filename"].endswith(".whl") and "x86_64" in u["filename"]
    )
    with tempfile.TemporaryDirectory() as td:
        whl = Path(td) / "cudnn8.whl"
        urllib.request.urlretrieve(wheel_url, whl)  # noqa: S310
        with zipfile.ZipFile(whl) as z:
            for name in z.namelist():
                if "/cudnn/lib/" in name and ".so" in name and not name.endswith("/"):
                    (lib_dir / Path(name).name).write_bytes(z.read(name))
    log(f"cuDNN 8 entpackt nach {lib_dir}")
    return lib_dir


def ensure_native_libs(log=None) -> None:
    """Macht die cuDNN-8-Libs (fuer ctranslate2) ueber LD_LIBRARY_PATH auffindbar.

    LD_LIBRARY_PATH wirkt nur, wenn es vor Prozessstart gesetzt ist; darum setzen wir
    es und starten den Prozess einmalig per ``execv`` neu (Marker verhindert Schleifen).
    Muss VOR dem Import von torch/whisperx aufgerufen werden.
    """
    log = log or (lambda _m: None)
    lib_dir = ensure_cudnn8(log)

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
