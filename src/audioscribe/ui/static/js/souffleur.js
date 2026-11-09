// Souffleur in der Live-Ansicht: Hinweise aus Wiki und KI neben dem Transkript (PRD §20).
// Der Abgleich laeuft im Server; hier werden Hinweise gezeichnet und mit dem Transkript verknuepft.

import { $, S, post, esc, icon, empty, tc, secs, sep, trimSep, projekt, modus, reducedMotion, cloudCompliant, toast } from './kern.js';
import { renderWikiState, loadWikiStatus } from './wiki.js';
import { pickFolder, askConfirm } from './dialoge.js';
import { setKontext } from './kontext.js';
import { herkunft, blinke, demoAktiv } from './demo.js';
import { tr } from './i18n.js';

// --- Souffleur (PRD §20): Hinweise aus Wiki und KI neben dem Transkript -----------
// Ereignisse vom Typ "hinweis" kommen ueber /api/live/status wie Segmente und Standbilder.
// Die Zeile im Transkript bekommt nur Klassen und einen Chip nach .lag - der Textknoten bleibt.

let liveRunning = false;         // aus dem letzten Poll der Live-Ansicht
let souffleurInfo = null;        // s.souffleur des letzten Polls (null = keine Sitzung / kein Souffleur)
let souffleurHints = [];         // hinweis-Ereignisse in Ankunftsreihenfolge
export const hintBySeg = new Map();     // segment_id -> hinweis (Markierung nachziehen, wenn die Zeile spaeter kommt)
const hintEls = new Map();       // hinweis.id -> details.hint-item
let souffleurEssenzen = [];      // Ergebnisse von /api/souffleur/essenz, aelteste zuerst
let souffleurToggling = false;   // laufender POST /api/souffleur/toggle - solange nicht vom Poll ueberschreiben
const HINT_DIRECT = 9;           // ab dem 10. Hinweis wandern die aelteren unter "Ältere (n)"
const HINT_OPEN = 1;             // nur der neueste Hinweis aufgeklappt - aeltere einzeilig, auf Klick
// Leitfaden (Meeting-Vorbereitung) - siehe unten
let lfVorschau = null;           // /api/leitfaden/vorschau der gewaehlten Datei (vor dem Start)
let lfKey = '';                  // zuletzt gezeichneter Stand - der Poll zeichnet nur bei Aenderung
let lfStand = { lf: null, interaktiv: false };  // letzte Daten aus dem Poll - fuer lokales Neuzeichnen
let lfAlle = false;              // false = Fokus (naechste offene Punkte), true = alle Punkte nach Abschnitt
const lfAuf = new Set();         // aufgeklappte Punkte (voller Text, KI-Stand)
const lfAnstoss = new Map();     // punkt_id -> Hinweis "anknuepfen": am Punkt markiert statt eigener Karte
let lfNeu = null;                // punkt_id, die beim naechsten Zeichnen kurz aufleuchtet
let lfSetzt = false;             // laufender POST - solange nicht vom Poll ueberschreiben
const LF_FOKUS = 3;              // so viele offene Punkte zeigt der Fokus

const ART = {
  widerspruch: { cls: 'widerspruch', icon: 'zap', wort: 'Widerspruch', label: 'Widerspruch' },
  offener_punkt: { cls: 'offen', icon: 'circle-dashed', wort: 'Offen', label: 'Offener Punkt' },
  frage: { cls: 'frage', icon: 'help-circle', wort: 'Frage', label: 'Frage' },
  anknuepfen: { cls: 'anknuepfen', icon: 'arrow-right', wort: 'Anknüpfen', label: 'Anknüpfen' },
};
// wort und label der drei Arten sind deutsche Schluessel - uebersetzt erst hier (en/module-b.js).
const artOf = (h) => {
  const a = ART[h.art];
  return a ? { ...a, wort: tr(a.wort), label: tr(a.label) }
    : { cls: 'frage', icon: 'help-circle', wort: h.label || h.art, label: h.label || h.art };
};
const hintId = (h) => `h-${h.id}`;
const tagKi = () => `<span class="tag ki">${icon('sparkles')}${tr('KI')}</span>`;

export function resetSouffleurView() {
  lfKey = ''; lfAlle = false; lfAuf.clear(); lfAnstoss.clear(); lfNeu = null;
  menuAuf(false);
  souffleurInfo = null; souffleurHints = []; souffleurEssenzen = [];
  hintBySeg.clear(); hintEls.clear();
  $('souffleurList').innerHTML = empty('lightbulb', tr('Hinweise zu Fragen, Widersprüchen und offenen Punkten erscheinen hier.'));
  $('souffleurEssenz').innerHTML = ''; $('souffleurEssenz').hidden = true;
  $('souffleurErr').textContent = '';
  $('souffleurLive').textContent = '';
  renderOpenPoints();
  updateHintCount();
  renderSouffleurState(null, false);
  renderWikiState($('souffleurWiki'), S.wikiStatus, true);
  renderWikiActions(S.wikiStatus);
  renderHandover(null);
  renderLeitfaden(null, false);
}

/** Wiki-Zustand des Projekts in der Karte zeigen - nur solange keine Sitzung ihren eigenen meldet. */
export function zeigeWikiStatus() {
  if (!souffleurInfo) { renderWikiState($('souffleurWiki'), S.wikiStatus, true); renderWikiActions(S.wikiStatus); }
}

// --- Wiki "on the fly" wechseln (Projekt: dauerhaft in projekt.json; Sofort aufnehmen: global) ----

function renderWikiActions(w) {
  $('souffleurMehr').hidden = modus() === 'demo';
  $('souffleurEinst').hidden = !projekt();  // ohne Projekt (Sofort aufnehmen) gibt es keine Projekteinstellungen
  $('souffleurWikiLoesen').hidden = !(w && w.zustand && w.zustand !== 'keins');
}

async function wikiSetzen(pfad) {
  $('souffleurErr').textContent = '';
  const btns = [$('souffleurWikiWechseln'), $('souffleurWikiLoesen')];
  for (const b of btns) b.disabled = true;
  try {
    setKontext(await post('/api/wiki/wechseln', { pfad }));
    await loadWikiStatus();
    toast(pfad ? tr('Wiki gewechselt – der Souffleur liest es ein') : tr('Wiki gelöst'));
  } catch (err) {
    $('souffleurErr').textContent = err.message;
  } finally {
    for (const b of btns) b.disabled = false;
  }
}

$('souffleurWikiWechseln').onclick = async () => {
  const w = souffleurInfo ? souffleurInfo.wiki : S.wikiStatus;
  const p = projekt();
  const pfad = await pickFolder({
    title: tr('LLM-Wiki wählen'), ok: tr('Dieses Wiki verwenden'),
    start: (w && w.pfad) || (p && (p.wiki_dir || p.wurzel)) || '',
  });
  if (pfad) wikiSetzen(pfad);
};
$('souffleurWikiLoesen').onclick = async () => {
  const ok = await askConfirm({
    title: tr('Wiki lösen?'),
    text: tr('Der Souffleur arbeitet danach ohne Belege; im Projekt wird die Verknüpfung gelöst. Die Dateien des Wikis bleiben unverändert.'),
    ok: tr('Wiki lösen'),
  });
  if (ok) wikiSetzen(null);
};

// --- ⋯-Menue: selten Gebrauchtes (Wiki wechseln/loesen, Einstellungen) aus der Karte heraus ----

function menuAuf(auf) {
  const m = $('souffleurMenu');
  if (m.hidden === !auf) return;
  m.hidden = !auf;
  $('souffleurMehr').setAttribute('aria-expanded', String(auf));
  if (auf) { const erst = m.querySelector('button:not([hidden]), a'); if (erst) erst.focus(); }
}
$('souffleurMehr').onclick = (e) => { e.stopPropagation(); menuAuf($('souffleurMenu').hidden); };
$('souffleurMenu').addEventListener('click', (e) => { if (e.target.closest('button, a')) menuAuf(false); });
$('souffleurMenu').addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  e.stopPropagation();  // sonst blendet Esc den ganzen Souffleur aus (live.js)
  menuAuf(false);
  $('souffleurMehr').focus();
});
document.addEventListener('click', (e) => {
  if (!e.target.closest || !e.target.closest('#souffleurMenu, #souffleurMehr')) menuAuf(false);
});

/** Markierung an die Transkriptzeile haengen: Klassen, Randstreifen, Chip nach .lag - der Text bleibt unberuehrt. */
export function markSegment(h) {
  const row = $('liveText').querySelector(`.seg[data-id="${CSS.escape(String(h.segment_id))}"]`);
  if (!row || row.querySelector('.mark')) return;
  const a = artOf(h);
  row.classList.add('marked', a.cls);
  // Anknuepfen hat keine eigene Karte - der Chip fuehrt zum Punkt im Leitfaden.
  const ziel = h.art === 'anknuepfen'
    ? `data-goto-punkt="${esc(String(h.punkt_id || ''))}" aria-label="${esc(tr('{art} – zum Leitfaden-Punkt {punkt}', { art: a.label, punkt: h.punkt_id || '' }))}"`
    : `data-goto-hint="${hintId(h)}" aria-label="${esc(tr('{art} – zum Hinweis {zeit}', { art: a.label, zeit: tc(h.t_start) }))}"`;
  row.dataset.hint = hintId(h);
  row.insertAdjacentHTML('beforeend', `<button class="mark ${a.cls}" type="button" ${ziel}>${icon(a.icon)}${esc(a.wort)}</button>`);
}

/** Wiki-Beleg: durchgezogen, hinterlegt, Fundstelle mit Kopierknopf (kopiert "datei › Überschrift"). */
function wikiQuoteHtml(h) {
  const f = (h.fundstellen && h.fundstellen[0]) || {};
  const zitat = h.wiki_zitat || f.auszug || '';
  const fund = h.fundstelle || f.datei || '';
  return `<blockquote class="wiki"><div class="src">${icon('book')}Wiki <span class="sep">·</span><code>${esc(f.datei || fund)}</code>`
    + (f.ueberschrift ? `<span class="sep">›</span>${esc(f.ueberschrift)}` : '')
    + `<button class="ghost copy" type="button" data-copy="${esc(fund)}" aria-label="${tr('Fundstelle kopieren')}" title="${tr('Fundstelle kopieren')}">${icon('copy')}</button>`
    + `</div>${esc(zitat)}</blockquote>`;
}

/** Beleg vom Bildschirm (Texterkennung eines Standbilds): gezeigt, nicht gesagt - mit Link aufs Bild. */
function bildQuoteHtml(b, zitat) {
  const url = `/api/live/frame/${encodeURIComponent(b.datei || '')}`;
  return `<blockquote class="wiki bild"><div class="src">${icon('image')}${tr('Bildschirm')} <span class="sep">·</span>`
    + `<a href="${esc(url)}" target="_blank" rel="noopener" title="${esc(tr('Standbild öffnen'))}">${esc(b.id || '')} · ${tc(b.t || 0)}</a></div>`
    + `${esc(zitat || '')}<p class="hint bild-hinweis">${tr('Per Texterkennung vom Standbild gelesen – gezeigt, nicht gesagt.')}</p></blockquote>`;
}

const hatBeleg = (h) => !h.ohne_befund && !!(h.wiki_zitat || (h.fundstellen && h.fundstellen.length));

/** Demo: der Beleg ist ein frueheres Gespraech - "Heute" neben "Meeting n" statt Datei im Wiki. */
function gegenHtml(h, her) {
  const f = (h.fundstellen && h.fundstellen[0]) || {};
  const zitat = (h.wiki_zitat || f.auszug || '').replace(/\s*\[Q-\d+[^\]]*\]/g, '');
  const heute = h.art === 'frage' ? '' : `<dt>${tr('Heute')}</dt><dd><q>${esc(h.aussage || '')}</q></dd>`;
  return `<dl class="gegen">${heute}<dt>${esc(tr('Meeting {nr}', { nr: her.nr }))}<span>${esc(her.datum)}</span></dt>`
    + `<dd class="frueher"><q>${esc(zitat)}</q></dd></dl>`;
}

// rolle: 'Antwortvorschlag' | 'Einschätzung' - deutscher Schluessel, uebersetzt erst hier.
const kiHtml = (rolle, text) => text
  ? `<div class="ki"><div class="ki-head">${tagKi()}${esc(tr(rolle))}</div>${esc(text)}</div>` : '';

/** Anstoss aus dem Leitfaden (aufgeklappter Punkt): die Stelle, an der er angesprochen wurde,
 *  und - KI-eingeschaetzt - was daran noch offen ist. */
function anknuepfenHtml(h) {
  return `<p class="said">${tr('Angesprochen:')} <q>${esc(h.aussage || '')}</q></p>`
    + kiHtml('Noch offen', h.ki_text);
}

/** Inhalt je Art: Widerspruch = Gesagt + Beleg + KI-Einschaetzung; Frage = Beleg (+ Antwortvorschlag);
 *  ohne Befund = nur "Im Wiki liegt dazu nichts vor." - bewusst kein KI-Text (Entscheidung des Auftraggebers). */
function hintBodyHtml(h) {
  const said = `<p class="said">${h.sprecher ? tr('Gesagt ({sprecher}):', { sprecher: esc(h.sprecher) }) : tr('Gesagt:')} <q>${esc(h.aussage || '')}</q></p>`;
  // Beleg vom Bildschirm (Frage per Standbild beantwortet) - neben oder statt des Wiki-Belegs.
  const bild = h.bild ? bildQuoteHtml(h.bild, h.bild.zitat) : '';
  if (!hatBeleg(h) && !bild) {
    return demoAktiv() ? `<p class="wiki none">${icon('plus')}${tr('Neu – steht noch nicht im Wiki.')}</p>`
      : `<p class="wiki none">${icon('book-x')}${tr('Im Wiki liegt dazu nichts vor.')}</p>`;
  }
  const her = herkunft(h);
  if (her) return gegenHtml(h, her) + kiHtml(h.art === 'frage' ? 'Antwortvorschlag' : 'Einschätzung', h.ki_text);
  const wiki = hatBeleg(h) ? wikiQuoteHtml(h) : '';
  if (h.art === 'frage') return wiki + bild + kiHtml('Antwortvorschlag', h.ki_text);
  return said + wiki + bild + kiHtml('Einschätzung', h.ki_text);
}

function hintItemEl(h) {
  const a = artOf(h);
  const el = document.createElement('details');
  el.className = `hint-item ${a.cls} new`;
  el.id = hintId(h);
  el.open = true;
  const lag = h.verzoegerung_s === null || h.verzoegerung_s === undefined ? '' : '+' + secs(h.verzoegerung_s);
  el.innerHTML = `<summary><span class="mark ${a.cls}">${icon(a.icon)}${esc(a.wort)}</span>`
    + `<button class="ts" type="button" data-goto-seg="${esc(String(h.segment_id))}" title="${tr('Zur Transkriptzeile')}">${tc(h.t_start)}</button>`
    + `<span class="title">${esc(h.aussage || a.label)}</span>`
    + `<span class="lag" title="${tr('Verzögerung Aussage → Hinweis')}">${esc(lag)}</span></summary>`
    + `<div class="hint-body">${hintBodyHtml(h)}</div>`;
  setTimeout(() => el.classList.remove('new'), 400);
  return el;
}

export function addHint(h) {
  if (hintEls.has(h.id)) return;
  if (h.art === 'anknuepfen') { addAnstoss(h); return; }
  souffleurHints.push(h);
  hintBySeg.set(h.segment_id, h);
  markSegment(h);
  const list = $('souffleurList');
  const leer = list.querySelector(':scope > .empty');
  if (leer) leer.remove();
  const el = hintItemEl(h);
  hintEls.set(h.id, el);
  list.prepend(el);  // neueste oben
  const her = herkunft(h);
  if (her) blinke(her.id);
  layoutHints();
  limitOpenHints();
  updateHintCount();
  $('souffleurLive').textContent = tr('{n} Hinweise, zuletzt: {art} {zeit}', { n: souffleurHints.length, art: artOf(h).label, zeit: tc(h.t_start) });
  renderOpenPoints();
}

/** Anstoss "nachhaken" an den Leitfaden-Punkt haengen: er rueckt im Fokus nach oben und leuchtet kurz. */
function addAnstoss(h) {
  hintEls.set(h.id, null);
  hintBySeg.set(h.segment_id, h);
  markSegment(h);
  lfAnstoss.set(h.punkt_id, h);
  lfNeu = h.punkt_id;
  zeichneLeitfaden();
  $('souffleurLive').textContent = tr('Leitfaden {punkt}: nachhaken', { punkt: h.punkt_id || '' });
}

/** Ab dem 10. Eintrag wandern die aeltesten unter "Ältere (n)" - die Knoten ziehen um, ihr Zustand bleibt. */
function layoutHints() {
  const list = $('souffleurList');
  let older = list.querySelector(':scope > details.older');
  const direct = [...list.children].filter((n) => n.classList.contains('hint-item'));
  if (direct.length > HINT_DIRECT) {
    if (!older) {
      older = document.createElement('details');
      older.className = 'older';
      older.innerHTML = `<summary>${icon('chevron-right')}<span></span></summary>`;
    }
    for (const el of direct.slice(HINT_DIRECT)) { el.open = false; older.querySelector('summary').after(el); }
  }
  if (older) {
    older.querySelector('summary span').textContent = tr('Ältere ({n})', { n: older.querySelectorAll('.hint-item').length });
    list.append(older);
  }
}

/** Hoechstens drei aufgeklappt: der vierte klappt den aeltesten zu (DOM-Reihenfolge = neueste zuerst). */
function limitOpenHints() {
  const open = [...$('souffleurList').querySelectorAll('details.hint-item[open]')];
  for (const el of open.slice(HINT_OPEN)) el.open = false;
}

function updateHintCount() {
  const n = souffleurHints.length;
  $('souffleurCount').textContent = n === 1 ? tr('{n} Hinweis', { n }) : tr('{n} Hinweise', { n });
}

/** Bilanz fuer die Schlusszeile der Demo: Widersprueche, aus dem Wiki beantwortete Fragen, Neues ohne Beleg. */
export function hinweisZahlen() {
  const z = { widerspruch: 0, beantwortet: 0, neu: 0 };
  for (const h of souffleurHints) {
    if (h.art === 'anknuepfen') continue;
    if (!hatBeleg(h)) z.neu += 1;
    else if (h.art === 'widerspruch') z.widerspruch += 1;
    else if (h.art === 'frage') z.beantwortet += 1;
  }
  return z;
}

let openKey = '';

/** Offene Punkte: alle Hinweise mit offener_punkt=true (offener Punkt, Frage ohne Befund), neueste oben.
 *  Waehrend der Sitzung laesst sich jeder in den Leitfaden uebernehmen - dann verfolgt ihn der Souffleur,
 *  und er landet sonst in "Fuer das Folgemeeting". */
function renderOpenPoints() {
  const offen = souffleurHints.filter((h) => h.offener_punkt).reverse();
  const kann = !!(souffleurInfo && liveRunning && !souffleurInfo.beendet);
  const lf = souffleurInfo && souffleurInfo.leitfaden;
  const im = new Map((lf && lf.punkte || []).filter((p) => p.herkunft).map((p) => [p.herkunft, p.id]));
  const key = JSON.stringify([offen.map((h) => h.id), kann, [...im]]);
  if (key === openKey) return;
  openKey = key;
  $('souffleurOpenCount').textContent = offen.length ? tr('({n} offen)', { n: offen.length }) : tr('(keine)');
  $('souffleurOpenList').innerHTML = offen.map((h) => {
    const pid = im.get(`hinweis:${h.id}`);
    const lfTeil = pid
      ? `<button class="ghost sm" type="button" data-goto-punkt-lf="${esc(pid)}" title="${esc(tr('Zum Leitfaden-Punkt'))}">${icon('list')}${esc(pid)}</button>`
      : kann ? `<button class="ghost sm" type="button" data-lf-neu="${esc(String(h.id))}" title="${esc(tr('Als Punkt in den Leitfaden übernehmen – der Souffleur verfolgt ihn dann'))}">${icon('plus')}${tr('Leitfaden')}</button>` : '';
    return `<li><button class="ts" type="button" data-goto-seg="${esc(String(h.segment_id))}" title="${tr('Zur Transkriptzeile')}">[${tc(h.t_start)}]</button>`
      + `<span class="text">${esc(h.aussage || '')}</span><span class="mark offen">${icon('circle-dashed')}${tr('Offen')}</span>${lfTeil}</li>`;
  }).join('') || `<li class="hint">${tr('Noch keine offenen Punkte.')}</li>`;
}

async function uebernimmPunkt(btn) {
  $('souffleurErr').textContent = '';
  btn.disabled = true;
  try {
    const lf = await post('/api/leitfaden/punkt', { hinweis_id: Number(btn.dataset.lfNeu) });
    if (souffleurInfo) souffleurInfo = { ...souffleurInfo, leitfaden: lf };
    renderLeitfaden(lf, true);
    renderOpenPoints();
  } catch (err) {
    $('souffleurErr').textContent = err.message;
    btn.disabled = false;
  }
}

/** Hinweiszeile zur Wiki-Ablage: was nach dem Stopp mit der Sitzung geschieht bzw. geschehen ist. */
export function renderHandover(ablage) {
  const box = $('souffleurHandover');
  const p = projekt();
  const key = JSON.stringify([ablage, p && p.wiki_speichern, p && p.wiki_markierungen, p && p.raw_dir]);
  if (box.dataset.key === key) return;
  box.dataset.key = key;
  if (ablage && ablage.ordner) {
    // Die Markierungen gehen nur auf Wunsch mit (KI-erzeugt) - sagen, was tatsaechlich dort liegt.
    const ordner = `<code>${esc(ablage.ordner)}</code>`;
    box.innerHTML = (ablage.frei ? tr('Gespeichert: {ordner}', { ordner }) : tr('Ins Wiki gespeichert: {ordner}', { ordner })) + ' ('
      + (ablage.markierungen ? '<code>markierungen.md</code>, ' : '') + '<code>transkript.md</code>)'
      + (ablage.markierungen ? '' : ' – ' + tr('die Markierungen bleiben im Sitzungsordner'));
  } else if (p && !p.demo && p.hat_wiki && p.wiki_speichern === 'immer') {
    box.innerHTML = p.wiki_markierungen
      ? tr('Beim Stopp gehen Transkript und Markierungen ins Wiki: {pfad}', { pfad: `<code>${esc(trimSep(p.raw_dir))}${esc(sep())}…${esc(sep())}markierungen.md</code>` })
      : tr('Beim Stopp geht das Transkript ins Wiki: {pfad} – die Markierungen bleiben im Sitzungsordner', { pfad: `<code>${esc(trimSep(p.raw_dir))}</code>` });
  } else {
    box.innerHTML = '';
  }
}

/** Zustand im Kopf: läuft · pausiert · ohne Wiki · KI nicht verfügbar - aus Schalter, Wiki und KI-Dienst. */
function renderSouffleurState(sf, running) {
  const aktiv = sf ? sf.aktiv : $('souffleurOn').checked;
  const wiki = sf ? sf.wiki : S.wikiStatus;
  const ki = sf ? sf.ki : null;
  let text = tr('bereit'), cls = '', title = '';
  if (!aktiv) { text = tr('pausiert'); title = tr('Auswertung ausgeschaltet – es entstehen keine neuen Hinweise.'); }
  else if (ki && (ki.zustand === 'fehlt' || ki.zustand === 'fehler')) { text = cloudCompliant() ? tr('lokale KI fehlt') : tr('KI fehlt'); cls = 'fail'; title = ki.meldung || tr('KI nicht verfügbar'); }
  else if (wiki && wiki.zustand === 'laedt') { text = tr('Wiki lädt'); cls = 'laeuft'; title = wiki.meldung || tr('Wiki wird gelesen …'); }
  else if (!wiki || wiki.zustand !== 'ok') { text = tr('ohne Wiki'); cls = 'warn'; title = tr('Ohne Wiki: nur Fragen und Essenz – keine Belege, keine Widersprüche.'); }
  else if (sf && sf.beendet) { text = tr('beendet'); cls = 'fertig'; }
  else if (sf && running) { text = tr('läuft'); cls = 'laeuft'; }
  else if (ki && ki.zustand === 'pause') { text = tr('pausiert'); title = ki.meldung || ''; }
  const badge = $('souffleurState');
  badge.textContent = text;
  badge.className = 'badge ' + cls;
  badge.title = title;
}

export function renderSouffleur(s) {
  const sf = s.souffleur || null;
  liveRunning = !!s.running;
  souffleurInfo = sf;
  if (sf && !souffleurToggling) $('souffleurOn').checked = !!sf.aktiv;
  renderSouffleurState(sf, !!s.running);
  renderWikiState($('souffleurWiki'), sf ? sf.wiki : S.wikiStatus, true);
  renderWikiActions(sf ? sf.wiki : S.wikiStatus);
  renderLeitfaden(sf ? sf.leitfaden : null, !!(sf && s.running && !sf.beendet));
  renderOpenPoints();
  const kannEssenz = !!sf;
  $('souffleurEssenz2').disabled = !kannEssenz;
  $('souffleurEssenz5').disabled = !kannEssenz;
}

async function toggleSouffleur() {
  const aktiv = $('souffleurOn').checked;
  souffleurToggling = true;
  $('souffleurErr').textContent = '';
  try {
    await post('/api/souffleur/toggle', { aktiv });
  } catch (err) {
    $('souffleurErr').textContent = err.message;
    $('souffleurOn').checked = !aktiv;
  } finally {
    souffleurToggling = false;
  }
  renderSouffleurState(souffleurInfo && { ...souffleurInfo, aktiv: $('souffleurOn').checked }, liveRunning);
}

/** Essenz der letzten 2 oder 5 Minuten - Fehler (400/409) erscheinen ruhig im Bereich, kein Toast. */
async function essenz(minuten) {
  $('souffleurErr').textContent = '';
  const btns = [$('souffleurEssenz2'), $('souffleurEssenz5')];
  for (const b of btns) b.disabled = true;
  try {
    const e = await post('/api/souffleur/essenz', { minuten });
    souffleurEssenzen.push(e);
    renderEssenz();
  } catch (err) {
    $('souffleurErr').textContent = err.message;
  } finally {
    for (const b of btns) b.disabled = !souffleurInfo;
  }
}

function essenzHtml(e) {
  const punkte = (e.punkte || []).map((p) => `<li>${esc(p)}</li>`).join('');
  const offen = (e.offen || []).length
    ? `<div class="offen-titel">${tr('Offen:')}</div><ul>${e.offen.map((o) => `<li>${esc(o)}</li>`).join('')}</ul>` : '';
  return `<div class="ki-head">${tagKi()}${esc(tr('Essenz {fenster}', { fenster: e.fenster || `${e.minuten} min` }))}<span class="spacer"></span>`
    + `<span class="lag" title="${tr('Dauer der Erzeugung')}">${tr('erzeugt in {dauer}', { dauer: secs(e.ki_s) })}</span></div>`
    + (punkte ? `<ul>${punkte}</ul>` : `<p class="hint">${tr('Keine Punkte.')}</p>`) + offen;
}

/** Nur die letzte Essenz offen; aeltere unter "Ältere Essenzen (n)". */
function renderEssenz() {
  const box = $('souffleurEssenz');
  if (!souffleurEssenzen.length) { box.hidden = true; box.innerHTML = ''; return; }
  const letzte = souffleurEssenzen[souffleurEssenzen.length - 1];
  const aeltere = souffleurEssenzen.slice(0, -1).reverse();
  box.innerHTML = essenzHtml(letzte) + (aeltere.length
    ? `<details class="older"><summary>${icon('chevron-right')}${tr('Ältere Essenzen ({n})', { n: aeltere.length })}</summary>`
      + aeltere.map((e) => `<div class="ki">${essenzHtml(e)}</div>`).join('') + '</details>' : '');
  box.hidden = false;
}

function flash(el) {
  if (!el || reducedMotion()) return;
  el.classList.remove('flash');
  void el.offsetWidth;  // Animation neu starten
  el.classList.add('flash');
  setTimeout(() => el.classList.remove('flash'), 1300);
}

/** Vom Chip in der Transkriptzeile zum Hinweis: aufklappen, ins Bild scrollen, kurz pulsen. */
export function gotoHint(id) {
  const el = $(id);
  if (!el) return;
  setSouffleurHidden(false);
  const older = el.closest('details.older');
  if (older) older.open = true;
  el.open = true;
  const open = [...$('souffleurList').querySelectorAll('details.hint-item[open]')].filter((o) => o !== el);
  for (const o of open.slice(HINT_OPEN - 1)) o.open = false;
  el.scrollIntoView({ block: 'nearest', behavior: reducedMotion() ? 'auto' : 'smooth' });
  flash(el);
  const head = el.querySelector('summary');
  if (head) head.focus({ preventScroll: true });
}

/** Vom Hinweis zur Transkriptzeile. */
function gotoSeg(segId) {
  const row = $('liveText').querySelector(`.seg[data-id="${CSS.escape(String(segId))}"]`);
  if (!row) return;
  window.focus();  // aus dem ausgekoppelten Souffleur: das Hauptfenster mit dem Transkript nach vorn
  row.scrollIntoView({ block: 'center', behavior: reducedMotion() ? 'auto' : 'smooth' });
  flash(row);
}

async function copyFundstelle(btn) {
  const use = btn.querySelector('use');
  try {
    await navigator.clipboard.writeText(btn.dataset.copy || '');
    btn.title = tr('Kopiert');
    if (use) use.setAttribute('href', '#i-check');
  } catch (e) {
    btn.title = tr('Kopieren nicht möglich');
  }
  setTimeout(() => { btn.title = tr('Fundstelle kopieren'); if (use) use.setAttribute('href', '#i-copy'); }, 1500);
}

/** Ausblenden = nur Sicht (Streifen + keine Chips); die Auswertung laeuft weiter. Ein Frame, kein Uebergang. */
export function setSouffleurHidden(hidden) {
  if ($('liveAside').classList.contains('collapsed') === hidden) return;
  $('liveAside').classList.toggle('collapsed', hidden);
  document.body.classList.toggle('souffleur-hidden', hidden);
  if (!$('tabLive').hidden) (hidden ? $('souffleurShow') : $('souffleurHide')).focus({ preventScroll: true });
}

// --- Leitfaden: Meeting-Vorbereitung als Checkliste ---------------------------------------
// Vor dem Start zeigt die Karte die Vorschau der gewaehlten Datei, waehrend der Sitzung den
// Stand des Souffleurs (s.souffleur.leitfaden). Klick aufs Symbol setzt den Status von Hand.

const LF_FOLGE = { offen: 'angesprochen', angesprochen: 'geklaert', geklaert: 'vertagt', vertagt: 'offen' };
const LF_ICON = { offen: 'circle', angesprochen: 'circle-dashed', geklaert: 'check', vertagt: 'pause' };
const LF_WORT = { offen: 'noch nicht besprochen', angesprochen: 'angesprochen', geklaert: 'geklärt', vertagt: 'vertagt' };

/** Vorschau der gewaehlten Vorbereitung (oder null) - gilt, solange keine Sitzung ihren Stand meldet. */
export function setLeitfadenVorschau(lf) {
  lfVorschau = lf;
  if (!souffleurInfo || !souffleurInfo.leitfaden) renderLeitfaden(null, false);
}

const lfErledigt = (p) => p.status === 'geklaert' || p.status === 'vertagt';
// Ein Anstoss gilt, bis der Punkt geklaert oder vertagt ist - oder wieder aufgegriffen wurde
// (letzte Erwaehnung nach der Stelle, auf die der Anstoss zeigt).
const lfAnstossVon = (p) => {
  const h = lfErledigt(p) ? null : lfAnstoss.get(p.id) || null;
  return h && !(p.t_zuletzt > h.t_start) ? h : null;
};

/** Was das Wiki zum Punkt festhaelt (p.wiki) - per Kennung sicher, per Suche nur "vermutlich". */
function lfWikiHtml(p) {
  return (p.wiki || []).map((w) => wikiQuoteHtml({
    fundstellen: [w], wiki_zitat: w.auszug, fundstelle: w.ueberschrift ? `${w.datei} › ${w.ueberschrift}` : w.datei,
  }) + (w.art === 'suche' ? `<p class="hint lf-wiki-suche">${tr('Per Suche gefunden – bitte prüfen, ob es passt.')}</p>` : '')).join('');
}

/** Was beim Aufklappen erscheint: der Anstoss (angesprochen + KI "noch offen"), sonst der KI-Stand -
 *  darunter, was das Wiki dazu festhaelt. */
function lfDetailHtml(p, anstoss) {
  let html = '';
  if (anstoss) html = anknuepfenHtml(anstoss);
  else if (p.stand) html = `<p class="lf-stand">${tagKi()} ${esc(p.stand)}</p>`;
  else if (p.notiz) html = `<p class="lf-stand">${esc(p.notiz)}</p>`;
  if (p.bild && p.aussage) html += bildQuoteHtml(p.bild, p.aussage);
  if (p.abweichung) {
    const a = p.abweichung;
    html += `<p class="lf-abweichung">${icon('zap')}${tagKi()} ${tr('Das Ergebnis weicht vom Wiki ab:')}</p>`
      + wikiQuoteHtml({ fundstellen: [a], wiki_zitat: a.zitat, fundstelle: a.ueberschrift ? `${a.datei} › ${a.ueberschrift}` : a.datei });
    return html;  // der abweichende Auszug ersetzt hier die Liste der Wiki-Bezuege
  }
  return html + lfWikiHtml(p);
}

/** Eine Zeile: Status (Klick = naechster Status) · ID + Text (Klick = aufklappen) · nachhaken · Zeit. */
function lfPunktHtml(p, interaktiv) {
  const wort = tr(LF_WORT[p.status] || p.status);
  const naechst = tr(LF_WORT[LF_FOLGE[p.status]] || '');
  const titel = interaktiv ? tr('{status} – Klick: {naechst}', { status: wort, naechst }) : wort;
  const anstoss = lfAnstossVon(p);
  const detail = lfDetailHtml(p, anstoss);
  const auf = lfAuf.has(p.id);
  const muss = p.prioritaet === 'muss';
  const zuletzt = p.t_zuletzt !== null && p.t_zuletzt !== undefined;
  const zeit = p.segment_id !== null && p.segment_id !== undefined && zuletzt
    ? `<button class="ts" type="button" data-goto-seg="${esc(String(p.segment_id))}" title="${tr('Zur Transkriptzeile')}">${tc(p.t_zuletzt)}</button>`
    : p.bild && zuletzt ? `<span class="ts bild" title="${esc(tr('Vom Bildschirm belegt'))}">${icon('image')}${tc(p.t_zuletzt)}</span>` : '';
  const cls = [`st-${p.status}`, muss ? 'muss' : '', anstoss ? 'anstoss' : '', auf ? 'auf' : '']
    .filter(Boolean).join(' ');
  return `<li class="${esc(cls)}" data-punkt-li="${esc(p.id)}">`
    + `<button class="lf-status" type="button" data-punkt="${esc(p.id)}" data-status="${esc(p.status)}"`
    + `${interaktiv ? '' : ' disabled'} title="${esc(titel)}" aria-label="${esc(`${p.id}: ${titel}`)}">${icon(LF_ICON[p.status] || 'circle')}</button>`
    + `<button class="lf-text" type="button" data-lf-auf="${esc(p.id)}" aria-expanded="${auf}"`
    + ` title="${esc(auf ? tr('Zuklappen') : tr('Aufklappen'))}">`
    + `<span class="lf-id">${esc(p.id)}</span>${muss ? `<span class="sr-only">${tr('Muss')}</span>` : ''}${esc(p.text)}</button>`
    + (p.wiki && p.wiki.length
      ? `<span class="lf-wiki${p.wiki.some((w) => w.art === 'kennung') ? '' : ' vermutlich'}" title="${esc(tr('Im Wiki: {ort}', { ort: p.wiki.map((w) => w.datei).join(', ') }))}">${icon('book')}<span class="sr-only">${tr('Im Wiki')}</span></span>` : '')
    + (p.abweichung ? `<span class="mark widerspruch" title="${esc(tr('Das Ergebnis weicht vom Wiki ab – aufklappen für die Stelle'))}">${icon('zap')}${tr('weicht ab')}</span>` : '')
    + (anstoss ? `<span class="mark anknuepfen" title="${esc(tr('Angesprochen, aber noch offen – nachhaken'))}">${icon('arrow-right')}${tr('nachhaken')}</span>` : '')
    + zeit
    + (auf && detail ? `<div class="lf-detail">${detail}</div>` : '')
    + '</li>';
}

/** Fokus: hoechstens LF_FOKUS offene Punkte - zuerst nachhaken, dann Pflicht, sonst in Reihenfolge der Datei. */
function lfFokus(punkte) {
  const rang = (p) => (lfAnstossVon(p) ? 0 : p.prioritaet === 'muss' ? 1 : 2);
  return punkte.map((p, i) => [p, i]).filter(([p]) => !lfErledigt(p))
    .sort((x, y) => rang(x[0]) - rang(y[0]) || x[1] - y[1]).slice(0, LF_FOKUS).map(([p]) => p);
}

/** Alle Punkte, nach Abschnitt der Vorbereitung gruppiert, mit "erledigt/gesamt" je Abschnitt. */
function lfAlleHtml(punkte, interaktiv) {
  const gruppen = [];
  for (const p of punkte) {
    const name = p.abschnitt || '';
    if (!gruppen.length || gruppen[gruppen.length - 1].name !== name) gruppen.push({ name, punkte: [] });
    gruppen[gruppen.length - 1].punkte.push(p);
  }
  const mitKopf = gruppen.length > 1 || (gruppen[0] && gruppen[0].name);
  return gruppen.map((g) => (mitKopf
    ? `<li class="lf-abschnitt"><span>${esc(g.name || tr('Punkte'))}</span>`
      + `<span class="hint">${g.punkte.filter(lfErledigt).length}/${g.punkte.length}</span></li>` : '')
    + g.punkte.map((p) => lfPunktHtml(p, interaktiv)).join('')).join('');
}

/** Leitfaden zeichnen: lf = Stand der Sitzung, sonst die Vorschau. Oben Fortschritt, darunter der Fokus
 *  (oder alle Punkte). Kein eigener Scrollbereich - die Karte scrollt als Ganzes. */
function renderLeitfaden(lf, interaktiv) {
  lfStand = { lf, interaktiv };
  if (lfSetzt) return;
  const daten = lf || lfVorschau;
  const key = JSON.stringify([daten, interaktiv, lfAlle, [...lfAuf], [...lfAnstoss.values()].map((h) => h.id)]);
  if (key === lfKey) return;
  lfKey = key;
  const box = $('souffleurLeitfaden');
  box.hidden = !daten;
  if (!daten) { $('souffleurLeitfadenList').innerHTML = ''; return; }
  const b = daten.bilanz || {};
  const n = b.punkte || 0, geklaert = b.geklaert || 0;
  $('souffleurLeitfadenBar').style.width = `${n ? Math.round((100 * geklaert) / n) : 0}%`;
  $('souffleurLeitfadenCount').innerHTML = esc(tr('{geklaert}/{n} geklärt', { geklaert, n }))
    + (b.muss_offen ? ` · <span class="lf-muss-zahl">${esc(tr('{muss} Pflicht offen', { muss: b.muss_offen }))}</span>` : '');
  const punkte = daten.punkte || [];
  let html, gezeigt;
  if (lfAlle) {
    html = lfAlleHtml(punkte, interaktiv);
    gezeigt = punkte.length;
  } else {
    const fokus = lfFokus(punkte);
    html = fokus.map((p) => lfPunktHtml(p, interaktiv)).join('');
    gezeigt = fokus.length;
    if (!html && punkte.length) html = `<li class="hint">${tr('Alles geklärt oder vertagt.')}</li>`;
  }
  $('souffleurLeitfadenList').innerHTML = html || `<li class="hint">${tr('Keine Punkte.')}</li>`;
  if (lfNeu) {
    flash($('souffleurLeitfadenList').querySelector(`[data-punkt-li="${CSS.escape(lfNeu)}"]`));
    lfNeu = null;
  }
  const alle = $('souffleurLeitfadenAlle');
  alle.hidden = !lfAlle && gezeigt >= punkte.length;
  alle.setAttribute('aria-expanded', String(lfAlle));
  alle.innerHTML = lfAlle ? `${icon('chevron-left')}${tr('Nur die nächsten offenen')}`
    : `${icon('chevron-right')}${tr('Alle {n} Punkte anzeigen', { n: punkte.length })}`;
}

/** Mit den letzten Daten neu zeichnen (Aufklappen, Umschalten, neuer Anstoss). */
function zeichneLeitfaden() {
  lfKey = '';
  renderLeitfaden(lfStand.lf, lfStand.interaktiv);
}

async function setzePunkt(btn) {
  const status = LF_FOLGE[btn.dataset.status] || 'offen';
  $('souffleurErr').textContent = '';
  btn.disabled = true;
  lfSetzt = true;
  try {
    const lf = await post('/api/leitfaden/status', { punkt_id: btn.dataset.punkt, status });
    if (souffleurInfo) souffleurInfo = { ...souffleurInfo, leitfaden: lf };
    lfSetzt = false;
    renderLeitfaden(lf, true);
  } catch (err) {
    lfSetzt = false;
    $('souffleurErr').textContent = err.message;
    btn.disabled = false;
  }
}

/** Vom Chip im Transkript zum Leitfaden-Punkt: notfalls alle Punkte zeigen, aufklappen, ins Bild, pulsen. */
export function gotoPunkt(id) {
  setSouffleurHidden(false);
  const daten = lfStand.lf || lfVorschau;
  if (!daten) return;
  if (!lfAlle && !lfFokus(daten.punkte || []).some((p) => p.id === id)) lfAlle = true;
  lfAuf.add(id);
  zeichneLeitfaden();
  const li = $('souffleurLeitfadenList').querySelector(`[data-punkt-li="${CSS.escape(id)}"]`);
  if (!li) return;
  li.scrollIntoView({ block: 'nearest', behavior: reducedMotion() ? 'auto' : 'smooth' });
  flash(li);
}

$('souffleurLeitfadenAlle').onclick = () => { lfAlle = !lfAlle; zeichneLeitfaden(); };

$('souffleurHide').onclick = () => setSouffleurHidden(true);
$('souffleurShow').onclick = () => setSouffleurHidden(false);
$('souffleurOn').onchange = toggleSouffleur;
$('souffleurEssenz2').onclick = () => essenz(2);
$('souffleurEssenz5').onclick = () => essenz(5);
$('souffleurEssenz2').disabled = true;
$('souffleurEssenz5').disabled = true;
$('souffleur').onclick = (e) => {
  const seg = e.target.closest('[data-goto-seg]');
  if (seg) { e.preventDefault(); gotoSeg(seg.dataset.gotoSeg); return; }
  const copy = e.target.closest('[data-copy]');
  if (copy) { e.preventDefault(); copyFundstelle(copy); return; }
  const neu = e.target.closest('button[data-lf-neu]');
  if (neu && !neu.disabled) { e.preventDefault(); uebernimmPunkt(neu); return; }
  const zumPunkt = e.target.closest('button[data-goto-punkt-lf]');
  if (zumPunkt) { e.preventDefault(); gotoPunkt(zumPunkt.dataset.gotoPunktLf); return; }
  const punkt = e.target.closest('button.lf-status[data-punkt]');
  if (punkt && !punkt.disabled) { e.preventDefault(); setzePunkt(punkt); return; }
  const auf = e.target.closest('button.lf-text[data-lf-auf]');
  if (auf) {
    e.preventDefault();
    const id = auf.dataset.lfAuf;
    if (lfAuf.has(id)) lfAuf.delete(id); else lfAuf.add(id);
    zeichneLeitfaden();
  }
};
