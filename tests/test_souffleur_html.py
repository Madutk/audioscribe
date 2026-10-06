"""Souffleur-Oberflaeche (PRD §20): Struktur von index.html, den Stylesheets und den Skripten.

Seit den Projekten (PRD §21) ist das Skript in Module aufgeteilt (static/js/*.js); die
Pruefungen laufen ueber alle Module zusammen bzw. gezielt ueber ``souffleur.js``.

Reine Textpruefungen nach dem Muster in tests/test_ui.py - kein Browser, kein Server.
Sie sichern die im UX-Konzept vereinbarten IDs, Klassen und Texte, auf die der
Live-Teil von app.js und die Prueflisten des UX-Reviews verweisen.
"""

import re
from pathlib import Path

import pytest

from audioscribe.ui import server

STATIC = Path(server.__file__).parent / "static"


@pytest.fixture(scope="module")
def html() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in (STATIC / "style.css", STATIC / "css" / "shell.css"))


@pytest.fixture(scope="module")
def js() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted((STATIC / "js").glob("*.js")))


@pytest.fixture(scope="module")
def souffleur_js() -> str:
    return (STATIC / "js" / "souffleur.js").read_text(encoding="utf-8")


# --- Sprite -------------------------------------------------------------------------------


def test_sprite_hat_die_neuen_symbole(html):
    for name in ("book", "book-x", "zap", "circle-dashed", "help-circle", "eye", "eye-off", "copy", "lightbulb", "fast-forward"):
        assert f'<symbol id="i-{name}"' in html, name


# --- Live-Reiter: rechte Spalte ---------------------------------------------------------------


def test_live_rechte_spalte_ist_live_aside_mit_souffleur_und_screenshots(html):
    assert 'class="live-aside" id="liveAside"' in html
    assert 'class="live-shots"' not in html
    assert 'class="card souffleur" id="souffleur"' in html
    # Souffleur oben, Screenshots darunter als zuklappbare Karte; Thumbnails und Zaehler bleiben erhalten.
    assert html.index('id="souffleur"') < html.index('id="liveShots"')
    assert '<details class="shots card" id="liveShots">' in html
    assert 'id="liveThumbs"' in html and 'id="liveShotCount"' in html
    assert html.index('id="liveShots"') < html.index('id="liveThumbs"')


def test_souffleur_kopf_hat_zaehler_schalter_zustand_und_ausblenden(html):
    assert 'id="souffleurCount"' in html
    assert '<label class="switch"' in html and 'id="souffleurOn"' in html
    assert 'id="souffleurState"' in html
    assert 'id="souffleurHide"' in html and 'aria-label="Souffleur ausblenden (Alt+S)"' in html
    assert '<button class="reopen" type="button" id="souffleurShow"' in html
    assert "Souffleur einblenden" in html
    # Reihenfolge im Kopf = Fokusreihenfolge: Schalter -> Zustand -> Ausblenden
    assert html.index('id="souffleurOn"') < html.index('id="souffleurState"') < html.index('id="souffleurHide"')


def test_live_region_nur_auf_dem_unsichtbaren_zaehler(html):
    assert 'class="sr-only" id="souffleurLive" aria-live="polite"' in html
    aside = html[html.index('id="liveAside"'):html.index('id="lightbox"')]
    assert aside.count("aria-live") == 1
    assert 'role="alert"' not in aside


def test_souffleur_wiki_zeile_werkzeuge_essenz_liste_offene_punkte(html):
    assert 'id="souffleurWiki"' in html and 'class="wiki-state none compact"' in html
    assert 'id="souffleurEssenz2"' in html and 'id="souffleurEssenz5"' in html
    assert "Essenz 2 min" in html and "Essenz 5 min" in html
    assert '<span class="key">Alt+S</span>' in html
    assert 'class="ki essenz" id="souffleurEssenz"' in html
    assert 'class="hint-list" id="souffleurList"' in html
    assert '<details class="open-box" id="souffleurOpen" open>' in html
    assert 'class="open-list" id="souffleurOpenList"' in html
    assert 'id="souffleurHandover"' in html
    assert 'id="souffleurErr"' in html
    # Reihenfolge innerhalb der Karte wie im Konzept
    order = ["souffleurWiki", "souffleurEssenz2", "souffleurEssenz", "souffleurList", "souffleurOpen"]
    positions = [html.index(f'id="{i}"') for i in order]
    assert positions == sorted(positions)


# --- Live-Reiter: Testmodus -------------------------------------------------------------------


def test_testmodus_unteroptionen_und_badge(html, js):
    assert 'class="subopts testmode" id="liveTestOpts" hidden' in html
    assert 'id="liveTestFile"' in html and 'id="pickLiveTestFile"' in html
    assert 'class="speed" role="radiogroup"' in html and 'id="liveTestSpeed"' in html
    assert 'class="badge warn" id="liveTestBadge" hidden' in html
    # Badge neben dem Phasen-Badge in den Gauges
    assert html.index('id="livePhase"') < html.index('id="liveTestBadge"') < html.index('id="liveElapsed"')
    assert 'id="liveStartLabel"' in html and "Aufnahme starten" in html
    # Die Kachel entsteht im Skript (live.js) in derselben Zeile wie die anderen Quellen.
    assert 'id="liveTestTile"' in js and 'data-kind="transcript"' in js
    assert "Transkript abspielen" in js and "Abspielen starten" in js


def test_startlive_sendet_replay_felder_und_keine_geraete_im_testmodus(js):
    start = js[js.index("async function startLive(resume)"):js.index("function insertByTime")]
    assert "replay_transcript: replay" in start and "replay_speed: replaySpeed()" in start
    assert "mic: test ? 'none'" in start and "loopback: test ? 'none'" in start
    # PRD §21: Sitzungstitel und - bei einer Wiederaufnahme - der Ordner der unterbrochenen Sitzung
    assert "titel: $('liveTitle').value.trim()" in start and "resume: resume || ''" in start


def test_live_defaults_belegen_testmodus_vor(js):
    assert "d.replay_transcript" in js and "d.replay_speeds" in js and "d.replay_speed" in js
    assert "d.source === 'transcript'" in js


# --- Einstellungen: Karte Wiki (Souffleur) ----------------------------------------------------


def test_projekteinstellungen_karte_wiki(html):
    """K1 seit PRD §21: das Wiki gehoert zum Projekt - Zustand in den Projekteinstellungen."""
    karte = html[html.index('id="setWikiCard"'):html.index('id="pSitzungen"')]
    assert "Projekt und Wiki" in karte and 'id="pWurzel"' in karte
    assert 'id="setWikiState"' in karte and 'class="wiki-state none"' in karte
    # Kein freies Wiki-Feld und kein Uebergabeordner mehr; kein Glossar-Feld (Glossar ist Teil des Wikis).
    for alt in ("setWiki", "pickSetWiki", "setHandover", "pickSetHandover", "setGlossar", "setGlossary"):
        assert f'id="{alt}"' not in html
    # Das Modell des Souffleurs ist eine Einstellung: global und je Projekt ueberschreibbar.
    assert '<select id="gSouffleurModel">' in html and '<select id="pSouffleurModel">' in html


def test_wiki_zustand_und_ordnerwahl_im_skript(js):
    assert "/api/wiki/status?path=" in js
    assert "export function renderWikiState(box, w, compact)" in js
    assert "pickFolder({ title: 'Sitzungsordner zum Abspielen wählen'" in js
    assert "'/api/projekt/pruefen'" in js and "'/api/wiki/speichern'" in js


# --- Skripte: Souffleur-Logik ------------------------------------------------------------------


def test_segmente_tragen_data_id_und_markierung_laesst_text_unveraendert(js):
    assert "el.dataset.id = ev.id" in js
    assert "hintBySeg.get(ev.id)" in js  # Markierung nachziehen, wenn die Zeile nach dem Hinweis kommt
    mark = js[js.index("function markSegment"):js.index("function wikiQuoteHtml")]
    assert "classList.add('marked', a.cls)" in mark
    assert "insertAdjacentHTML('beforeend'" in mark  # Chip NACH .lag, kein Umbau des Textknotens
    assert "data-goto-hint" in mark and "aria-label=" in mark
    assert ".textContent" not in mark and ".innerHTML" not in mark


def test_drei_arten_mit_eigener_klasse_icon_und_wort(js):
    assert "widerspruch: { cls: 'widerspruch', icon: 'zap', wort: 'Widerspruch'" in js
    assert "offener_punkt: { cls: 'offen', icon: 'circle-dashed', wort: 'Offen'" in js
    assert "frage: { cls: 'frage', icon: 'help-circle', wort: 'Frage'" in js


def test_hinweisinhalt_wiki_beleg_ki_und_ohne_befund(js):
    body = js[js.index("function hintBodyHtml"):js.index("function hintItemEl")]
    assert "Im Wiki liegt dazu nichts vor." in body
    # ohne Befund: KEIN KI-Text
    assert body.index("Im Wiki liegt dazu nichts vor.") < body.index("kiHtml(")
    assert "kiHtml('Antwortvorschlag', h.ki_text)" in body and "kiHtml('Einschätzung', h.ki_text)" in body
    quote = js[js.index("function wikiQuoteHtml"):js.index("const kiHtml")]
    assert '<blockquote class="wiki">' in quote and "data-copy=" in quote and 'aria-label="Fundstelle kopieren"' in quote
    assert "h.wiki_zitat" in quote
    assert 'class="tag ki"' in js and "KI</span>" in js


def test_kein_produktname_in_der_oberflaeche(html, souffleur_js):
    """Der Souffleur sagt nur „KI“. Welcher Dienst dahintersteht, steht allein in den Einstellungen."""
    aside = html[html.index('id="liveAside"'):html.index('id="lightbox"')]
    karte = html[html.index('id="setWikiCard"'):html.index('id="pSitzungen"')]
    for text in (aside, karte, souffleur_js):
        assert not re.search(r"claude|anthropic|gpt|openai|sonnet|opus|haiku", text, re.I)


def test_liste_neueste_oben_max_drei_offen_aeltere_ab_zehn(js):
    assert "list.prepend(el)" in js
    assert "const HINT_OPEN = 3;" in js and "const HINT_DIRECT = 9;" in js
    assert "`Ältere (${" in js
    assert "Verzögerung Aussage → Hinweis" in js


def test_zustaende_und_essenz(js):
    state = js[js.index("function renderSouffleurState"):js.index("function renderSouffleur(")]
    for text in ("'pausiert'", "'läuft'", "'ohne Wiki'", "'KI nicht verfügbar'"):
        assert text in state, text
    assert "post('/api/souffleur/toggle', { aktiv })" in js
    assert "post('/api/souffleur/essenz', { minuten })" in js
    # Fehler ruhig im Bereich, kein alert/Toast
    essenz = js[js.index("async function essenz("):js.index("function essenzHtml")]
    assert "$('souffleurErr').textContent = err.message" in essenz and "alert(" not in essenz
    assert "erzeugt in" in js


def test_offene_punkte_aus_hinweisen_und_wiki_ablage(js):
    assert "h.offener_punkt" in js
    # Statt der automatischen Uebergabe zeigt die Karte die Wiki-Ablage der Sitzung (PRD §21).
    assert "ablage.ordner" in js and "markierungen.md" in js and "sf.uebergabe" not in js
    # keine eigene Route noetig
    assert "/api/souffleur/offene-punkte" not in js


def test_ausblenden_alt_s_esc_und_chips(js):
    assert "classList.toggle('collapsed', hidden)" in js
    assert "classList.toggle('souffleur-hidden', hidden)" in js
    assert "e.key.toLowerCase() === 's'" in js and "e.altKey" in js
    assert "$('liveAside').contains(document.activeElement)" in js


def test_reset_leert_souffleur(js):
    reset = js[js.index("function resetLiveView()"):js.index("async function resetLive()")]
    assert "resetSouffleurView()" in reset
    sreset = js[js.index("function resetSouffleurView()"):js.index("function markSegment")]
    for text in ("souffleurHints = []", "souffleurEssenzen = []", "hintBySeg.clear()", "hintEls.clear()",
                 "$('souffleurEssenz').innerHTML = ''", "updateHintCount()", "renderOpenPoints()"):
        assert text in sreset, text


def test_phase_abschluss_bekannt(js):
    assert "abschluss: 'Souffleur schließt ab …'" in js
    assert "abschluss: 'laeuft'" in js


# --- style.css ---------------------------------------------------------------------------------


def test_css_grid_und_bausteine(css):
    assert "#tabLive { grid-template-columns: minmax(0, .85fr) minmax(0, 1.9fr) minmax(0, 1.15fr); }" in css
    assert ".live-shots" not in css
    for sel in (".live-aside", ".live-aside.collapsed", ".hint-list", ".hint-item", ".mark.widerspruch", ".mark.offen",
                ".mark.frage", "blockquote.wiki", "p.wiki.none", ".ki {", ".tag.ki", ".wiki-state", ".switch",
                ".speed", ".monitor.test", ".seg.flash", ".sr-only", "body.souffleur-hidden .seg .mark", ".reopen",
                "details.open-box", "ul.open-list", "details.older", "details.shots"):
        assert sel in css, sel


def test_css_formen_der_drei_arten(css):
    assert ".mark.offen" in css and "border-style: dashed" in css.split(".mark.offen")[1].split("\n")[0]
    assert ".seg.marked.offen { border-left-color: var(--warn); border-left-style: dashed; }" in css
    assert ".mark.frage       { background: transparent;" in css
    assert ".ki { border: 1px dashed var(--border-strong);" in css


def test_css_tokens_tragen_beide_modi_und_souffleur_bleibt_ohne_harte_farben(css):
    # Ein Satz Tokens mit light-dark() statt dreier Bloecke; data-theme erzwingt eine Seite.
    assert "--bg: light-dark(" in css and "color-scheme: light dark;" in css
    assert ':root[data-theme="light"] { color-scheme: light; }' in css
    assert ':root[data-theme="dark"] { color-scheme: dark; }' in css
    assert "@media (prefers-color-scheme: dark)" not in css
    block = css[css.index("/* --- Souffleur"):css.index("/* --- Responsiv")]
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", block)


def test_css_responsiv_und_reduced_motion(css):
    r1200 = css[css.index("@media (max-width: 1200px)"):css.index("@media (max-width: 860px)")]
    assert ".live-aside { grid-column: 1 / -1; }" in r1200
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in r1200
    r860 = css[css.index("@media (max-width: 860px)"):css.index("@media (max-width: 560px)")]
    assert ".hint-list { grid-template-columns: 1fr; }" in r860
    assert "@media (prefers-reduced-motion: reduce)" in css
