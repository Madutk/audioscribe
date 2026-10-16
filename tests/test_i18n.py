"""Sprache der Oberfläche (i18n): Umschalten, und dass jeder deutsche Text eine englische
Fassung hat - im Python-Code (``tr("…")``), in den Skripten der Oberfläche (``tr('…')``) und
im statischen HTML."""

from __future__ import annotations

import ast
import json
import re
from html.parser import HTMLParser
from pathlib import Path


from audioscribe import i18n
from audioscribe.ui import state

SRC = Path(__file__).resolve().parents[1] / "src" / "audioscribe"
STATIC = SRC / "ui" / "static"


def _js_woerterbuch() -> dict[str, str]:
    alle: dict[str, str] = {}
    for datei in sorted((STATIC / "js" / "en").glob("*.js")):
        if datei.name == "index.js":
            continue
        text = datei.read_text(encoding="utf-8").strip()
        assert text.startswith("export default {") and text.endswith("};"), datei.name
        alle.update(json.loads(text[len("export default ") : -1]))
    return alle


def _js_dateien() -> list[Path]:
    return [p for p in (STATIC / "js").glob("*.js") if p.name != "i18n.js"]


_JS_UNESCAPE = re.compile(r"\\(.)")


def _js_tr_texte(text: str) -> list[str]:
    funde = []
    for m in re.finditer(r"\btr\(\s*(['\"`])((?:\\.|(?!\1).)*)\1", text, re.S):
        assert m.group(1) != "`", f"tr() mit Template-Literal: {m.group(0)[:60]} - Platzhalter {{name}} verwenden"
        funde.append(_JS_UNESCAPE.sub(lambda e: {"n": "\n", "t": "\t"}.get(e.group(1), e.group(1)), m.group(2)))
    return funde


def test_js_woerterbuecher_sind_json():
    assert _js_woerterbuch()  # wirft bei ungültigem JSON


def test_python_woerterbuecher_sind_json():
    for datei in (SRC / "i18n" / "en").glob("*.json"):
        assert isinstance(json.loads(datei.read_text(encoding="utf-8")), dict), datei.name


def test_jeder_js_text_ist_uebersetzt():
    en = _js_woerterbuch()
    fehlend = sorted(
        {f"{p.name}: {s}" for p in _js_dateien() for s in _js_tr_texte(p.read_text(encoding="utf-8")) if s not in en}
    )
    assert not fehlend, "\n".join(fehlend)


def test_jeder_python_text_ist_uebersetzt():
    en = i18n.woerterbuch("en")
    fehlend = []
    for datei in SRC.rglob("*.py"):
        baum = ast.parse(datei.read_text(encoding="utf-8"))
        for knoten in ast.walk(baum):
            if not (isinstance(knoten, ast.Call) and isinstance(knoten.func, ast.Name) and knoten.func.id == "tr"):
                continue
            if datei.parent.name == "i18n":
                continue
            arg = knoten.args[0] if knoten.args else None
            assert isinstance(arg, ast.Constant) and isinstance(arg.value, str), (
                f"{datei.name}:{knoten.lineno}: tr() braucht einen festen Text als erstes Argument"
            )
            if arg.value not in en:
                fehlend.append(f"{datei.relative_to(SRC)}:{knoten.lineno}: {arg.value}")
    assert not fehlend, "\n".join(fehlend)


def test_platzhalter_stimmen_ueberein():
    """Die englische Fassung nennt dieselben Platzhalter wie die deutsche."""
    platz = re.compile(r"\{(\w+)\}")
    for name, en in (("python", i18n.woerterbuch("en")), ("js", _js_woerterbuch())):
        falsch = [k for k, v in en.items() if set(platz.findall(k)) != set(platz.findall(v))]
        assert not falsch, f"{name}: {falsch}"


# --- Statisches HTML ----------------------------------------------------------------------

_OHNE = {"script", "style", "svg", "pre", "code"}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_ATTRIBUTE = ("title", "aria-label", "placeholder", "alt")
_NORM = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _NORM.sub(" ", s).strip()


def _esc_text(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\xa0", "&nbsp;")


class _Sammler(HTMLParser):
    """Texte, die i18n.uebersetzeDom ersetzt: Textknoten, Attribute und data-t-Blöcke."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stapel: list[tuple[str, bool]] = []  # (Tag, übersprungen)
        self.texte: list[str] = []
        self.dt: list[list[str]] = []  # offene data-t-Blöcke (inneres HTML)
        self.dt_tiefe: list[int] = []

    def _uebersprungen(self) -> bool:
        return bool(self.stapel) and self.stapel[-1][1]

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for name in _ATTRIBUTE:
            if a.get(name) and re.search(r"[A-Za-zÄÖÜäöüß]", a[name]):
                self.texte.append(_norm(a[name]))
        if self.dt:
            attr = "".join(f' {k}="{(v or "").replace("&", "&amp;").replace(chr(34), "&quot;")}"' for k, v in attrs)
            self.dt[-1].append(f"<{tag}{attr}>")
        skip = self._uebersprungen() or tag in _OHNE or a.get("translate") == "no"
        if "data-t" in a and not skip:
            self.dt.append([])
            self.dt_tiefe.append(len(self.stapel))
            skip = True
        if tag not in _VOID:
            self.stapel.append((tag, skip))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        while self.stapel:
            t, _ = self.stapel.pop()
            if self.dt and len(self.stapel) == self.dt_tiefe[-1]:
                self.texte.append(_norm("".join(self.dt.pop())))
                self.dt_tiefe.pop()
                break
            if self.dt:
                self.dt[-1].append(f"</{t}>")
            if t == tag:
                break

    def handle_data(self, data):
        if self.dt:
            self.dt[-1].append(_esc_text(data))
        if self._uebersprungen() or not re.search(r"[A-Za-zÄÖÜäöüß]", data):
            return
        self.texte.append(_norm(data))


def test_statisches_html_ist_uebersetzt():
    seite = STATIC / "index.html"
    en = _js_woerterbuch()
    sammler = _Sammler()
    text = seite.read_text(encoding="utf-8")
    # Nur den Körper - <title> übersetzt i18n.js gesondert.
    sammler.feed(text[text.index("<body") :])
    fehlend = sorted({t for t in sammler.texte if t not in en})
    assert not fehlend, "\n".join(fehlend)


# --- Umschalten ---------------------------------------------------------------------------


def test_tr_folgt_der_einstellung():
    i18n._woerterbuch["en"] = {"Die Demo läuft bereits.": "The demo is already running.", "{n} Meetings": "{n} meetings"}
    try:
        assert i18n.tr("Die Demo läuft bereits.") == "Die Demo läuft bereits."
        state.save_state({"ui_sprache": "en"})
        assert i18n.sprache() == "en"
        assert i18n.tr("Die Demo läuft bereits.") == "The demo is already running."
        assert i18n.tr("{n} Meetings", n=3) == "3 meetings"
        assert i18n.tr("Unbekannt {x}", x=1) == "Unbekannt 1"
    finally:
        i18n._woerterbuch.clear()


def test_ungueltige_sprache_wird_nicht_gespeichert():
    state.save_state({"ui_sprache": "fr\" onload=\"x"})
    assert "ui_sprache" not in state.load_state()
    assert i18n.sprache() == "de"


def test_html_traegt_die_sprache():
    from audioscribe.ui.server import inject_theme

    assert '<html lang="de" data-theme="system">' in inject_theme('<html lang="de">')
    state.save_state({"ui_sprache": "en"})
    assert '<html lang="en" data-theme="system">' in inject_theme('<html lang="de">')


def test_demo_je_sprache():
    from audioscribe.ui import kontext

    deutsch = kontext.demo_wurzel()
    state.save_state({"ui_sprache": "en"})
    englisch = kontext.demo_wurzel()
    assert deutsch.name == "llm-wiki" and englisch.name == "llm-wiki-en"
    assert (englisch / kontext.DEMO_TRANSKRIPT).is_file()
    v = kontext.demo_vorgeschichte()
    assert len(v["meetings"]) == 3 and v["wiki"]["anforderungen"] > 0
