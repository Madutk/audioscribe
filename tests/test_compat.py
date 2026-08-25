"""Kompatibilitaets-Shims: die beiden Windows-Stolpersteine des ML-Stacks."""

import importlib.util
import inspect
import os
import sys
from pathlib import Path

import pytest

from audioscribe import compat


@pytest.mark.skipif(os.name != "nt", reason="Der Shim greift nur unter Windows")
def test_ensure_pkg_resources_legt_ersatz_an(monkeypatch):
    """Fehlt pkg_resources (setuptools >= 81), muss ctranslate2 trotzdem importierbar sein."""
    orig_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a, **k: None if name == "pkg_resources" else orig_find_spec(name, *a, **k),
    )
    monkeypatch.delitem(sys.modules, "pkg_resources", raising=False)
    try:
        compat.ensure_pkg_resources()
        shim = sys.modules["pkg_resources"]
        # Genau der eine Aufruf, den ctranslate2 macht: das eigene Paketverzeichnis.
        import audioscribe

        assert shim.resource_filename("audioscribe", "") == str(Path(audioscribe.__file__).parent)
    finally:
        sys.modules.pop("pkg_resources", None)


def test_ensure_pkg_resources_laesst_vorhandenes_modul_in_ruhe(monkeypatch):
    marker = object()
    monkeypatch.setitem(sys.modules, "pkg_resources", marker)
    compat.ensure_pkg_resources()
    assert sys.modules["pkg_resources"] is marker


def test_speechbrain_lazy_module_reisst_inspect_stack_nicht_mit(monkeypatch):
    """``inspect.stack()`` darf keinen fehlschlagenden Lazy-Import ausloesen.

    Genau daran starb der Lauf unter Windows in Stufe 3: pytorch_lightning ruft beim
    Laden des VAD-Checkpoints ``inspect.stack()``, das jedes Modul in ``sys.modules``
    anfasst - inklusive speechbrains Platzhalter fuer das nicht installierte ``k2``.
    """
    pytest.importorskip("speechbrain")
    from speechbrain.utils.importutils import LazyModule

    platzhalter = LazyModule(name="k2_test", target="paket_das_es_nicht_gibt", package=None)
    monkeypatch.setitem(sys.modules, "audioscribe_lazy_test", platzhalter)

    compat.apply_speechbrain_lazy_compat()

    assert inspect.stack()  # ohne den Shim: ImportError
    # Ausserhalb von inspect bleibt das Lazy-Verhalten unangetastet.
    with pytest.raises(ImportError):
        platzhalter.irgendein_attribut


def test_ensure_native_libs_laedt_unter_windows_nichts(monkeypatch):
    """Der cuDNN-8-Bootstrap ist ein Linux-Workaround.

    Das ctranslate2-Windows-Wheel bringt cudnn64_8.dll selbst mit; ohne den Abbruch
    zoege der CUDA-Pfad mehrere hundert MB Linux-.so-Dateien und startete den Prozess
    danach grundlos per execv neu.
    """
    gerufen = []
    monkeypatch.setattr(compat.os, "name", "nt")
    monkeypatch.setattr(compat, "ensure_cudnn8", lambda log=None: gerufen.append("download"))

    compat.ensure_native_libs()

    assert gerufen == []
