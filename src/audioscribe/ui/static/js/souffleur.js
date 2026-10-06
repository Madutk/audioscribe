// Souffleur in der Live-Ansicht: Hinweise aus Wiki und KI neben dem Transkript (PRD §20).
// Der Abgleich laeuft im Server; hier werden Hinweise gezeichnet und mit dem Transkript verknuepft.

import { $, S, post, esc, icon, empty, tc, secs, sep, trimSep, projekt, reducedMotion } from './kern.js';
import { renderWikiState } from './wiki.js';

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
const HINT_OPEN = 3;             // hoechstens so viele Hinweise gleichzeitig aufgeklappt

const ART = {
  widerspruch: { cls: 'widerspruch', icon: 'zap', wort: 'Widerspruch', label: 'Widerspruch' },
  offener_punkt: { cls: 'offen', icon: 'circle-dashed', wort: 'Offen', label: 'Offener Punkt' },
  frage: { cls: 'frage', icon: 'help-circle', wort: 'Frage', label: 'Frage' },
};
const artOf = (h) => ART[h.art] || { cls: 'frage', icon: 'help-circle', wort: h.label || h.art, label: h.label || h.art };
const hintId = (h) => `h-${h.id}`;
const tagKi = () => `<span class="tag ki">${icon('sparkles')}KI</span>`;

export function resetSouffleurView() {
  souffleurInfo = null; souffleurHints = []; souffleurEssenzen = [];
  hintBySeg.clear(); hintEls.clear();
  $('souffleurList').innerHTML = empty('lightbulb', 'Hinweise zu Fragen, Widersprüchen und offenen Punkten erscheinen hier.');
  $('souffleurEssenz').innerHTML = ''; $('souffleurEssenz').hidden = true;
  $('souffleurErr').textContent = '';
  $('souffleurLive').textContent = '';
  renderOpenPoints();
  updateHintCount();
  renderSouffleurState(null, false);
  renderWikiState($('souffleurWiki'), S.wikiStatus, true);
  renderHandover(null);
}

/** Wiki-Zustand des Projekts in der Karte zeigen - nur solange keine Sitzung ihren eigenen meldet. */
export function zeigeWikiStatus() {
  if (!souffleurInfo) renderWikiState($('souffleurWiki'), S.wikiStatus, true);
}

/** Markierung an die Transkriptzeile haengen: Klassen, Randstreifen, Chip nach .lag - der Text bleibt unberuehrt. */
export function markSegment(h) {
  const row = $('liveText').querySelector(`.seg[data-id="${CSS.escape(String(h.segment_id))}"]`);
  if (!row || row.querySelector('.mark')) return;
  const a = artOf(h);
  row.classList.add('marked', a.cls);
  row.dataset.hint = hintId(h);
  row.insertAdjacentHTML('beforeend',
    `<button class="mark ${a.cls}" type="button" data-goto-hint="${hintId(h)}" aria-label="${esc(a.label)} – zum Hinweis ${tc(h.t_start)}">`
    + `${icon(a.icon)}${esc(a.wort)}</button>`);
}

/** Wiki-Beleg: durchgezogen, hinterlegt, Fundstelle mit Kopierknopf (kopiert "datei › Überschrift"). */
function wikiQuoteHtml(h) {
  const f = (h.fundstellen && h.fundstellen[0]) || {};
  const zitat = h.wiki_zitat || f.auszug || '';
  const fund = h.fundstelle || f.datei || '';
  return `<blockquote class="wiki"><div class="src">${icon('book')}Wiki <span class="sep">·</span><code>${esc(f.datei || fund)}</code>`
    + (f.ueberschrift ? `<span class="sep">›</span>${esc(f.ueberschrift)}` : '')
    + `<button class="ghost copy" type="button" data-copy="${esc(fund)}" aria-label="Fundstelle kopieren" title="Fundstelle kopieren">${icon('copy')}</button>`
    + `</div>${esc(zitat)}</blockquote>`;
}

const kiHtml = (rolle, text) => text
  ? `<div class="ki"><div class="ki-head">${tagKi()}${esc(rolle)}</div>${esc(text)}</div>` : '';

/** Inhalt je Art: Widerspruch = Gesagt + Beleg + KI-Einschaetzung; Frage = Beleg (+ Antwortvorschlag);
 *  ohne Befund = nur "Im Wiki liegt dazu nichts vor." - bewusst kein KI-Text (Entscheidung des Auftraggebers). */
function hintBodyHtml(h) {
  const said = `<p class="said">Gesagt${h.sprecher ? ` (${esc(h.sprecher)})` : ''}: <q>${esc(h.aussage || '')}</q></p>`;
  const hasWiki = !h.ohne_befund && (h.wiki_zitat || (h.fundstellen && h.fundstellen.length));
  if (!hasWiki) return `<p class="wiki none">${icon('book-x')}Im Wiki liegt dazu nichts vor.</p>`;
  if (h.art === 'frage') return wikiQuoteHtml(h) + kiHtml('Antwortvorschlag', h.ki_text);
  return said + wikiQuoteHtml(h) + kiHtml('Einschätzung', h.ki_text);
}

function hintItemEl(h) {
  const a = artOf(h);
  const el = document.createElement('details');
  el.className = `hint-item ${a.cls} new`;
  el.id = hintId(h);
  el.open = true;
  const lag = h.verzoegerung_s === null || h.verzoegerung_s === undefined ? '' : '+' + secs(h.verzoegerung_s);
  el.innerHTML = `<summary><span class="mark ${a.cls}">${icon(a.icon)}${esc(a.wort)}</span>`
    + `<button class="ts" type="button" data-goto-seg="${esc(String(h.segment_id))}" title="Zur Transkriptzeile">${tc(h.t_start)}</button>`
    + `<span class="title">${esc(h.aussage || a.label)}</span>`
    + `<span class="lag" title="Verzögerung Aussage → Hinweis">${esc(lag)}</span></summary>`
    + `<div class="hint-body">${hintBodyHtml(h)}</div>`;
  setTimeout(() => el.classList.remove('new'), 400);
  return el;
}

export function addHint(h) {
  if (hintEls.has(h.id)) return;
  souffleurHints.push(h);
  hintBySeg.set(h.segment_id, h);
  markSegment(h);
  const list = $('souffleurList');
  const leer = list.querySelector(':scope > .empty');
  if (leer) leer.remove();
  const el = hintItemEl(h);
  hintEls.set(h.id, el);
  list.prepend(el);  // neueste oben
  layoutHints();
  limitOpenHints();
  updateHintCount();
  $('souffleurLive').textContent = `${souffleurHints.length} Hinweise, zuletzt: ${artOf(h).label} ${tc(h.t_start)}`;
  renderOpenPoints();
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
    older.querySelector('summary span').textContent = `Ältere (${older.querySelectorAll('.hint-item').length})`;
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
  $('souffleurCount').textContent = `${n} ${n === 1 ? 'Hinweis' : 'Hinweise'}`;
}

/** Offene Punkte: alle Hinweise mit offener_punkt=true (offener Punkt, Frage ohne Befund), neueste oben. */
function renderOpenPoints() {
  const offen = souffleurHints.filter((h) => h.offener_punkt).reverse();
  $('souffleurOpenCount').textContent = offen.length ? `(${offen.length} offen)` : '(keine)';
  $('souffleurOpenList').innerHTML = offen.map((h) =>
    `<li><button class="ts" type="button" data-goto-seg="${esc(String(h.segment_id))}" title="Zur Transkriptzeile">[${tc(h.t_start)}]</button>`
    + `<span class="text">${esc(h.aussage || '')}</span><span class="mark offen">${icon('circle-dashed')}Offen</span></li>`).join('')
    || '<li class="hint">Noch keine offenen Punkte.</li>';
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
    box.innerHTML = `Ins Wiki gespeichert: <code>${esc(ablage.ordner)}</code> (`
      + (ablage.markierungen ? '<code>markierungen.md</code>, ' : '') + '<code>transkript.md</code>)'
      + (ablage.markierungen ? '' : ' – die Markierungen bleiben im Sitzungsordner');
  } else if (p && !p.demo && p.wiki_speichern === 'immer') {
    box.innerHTML = p.wiki_markierungen
      ? `Beim Stopp gehen Transkript und Markierungen ins Wiki: <code>${esc(trimSep(p.raw_dir))}${esc(sep())}…${esc(sep())}markierungen.md</code>`
      : `Beim Stopp geht das Transkript ins Wiki: <code>${esc(trimSep(p.raw_dir))}</code> – die Markierungen bleiben im Sitzungsordner`;
  } else {
    box.innerHTML = '';
  }
}

/** Zustand im Kopf: läuft · pausiert · ohne Wiki · KI nicht verfügbar - aus Schalter, Wiki und KI-Dienst. */
function renderSouffleurState(sf, running) {
  const aktiv = sf ? sf.aktiv : $('souffleurOn').checked;
  const wiki = sf ? sf.wiki : S.wikiStatus;
  const ki = sf ? sf.ki : null;
  let text = 'bereit', cls = '', title = '';
  if (!aktiv) { text = 'pausiert'; title = 'Auswertung ausgeschaltet – es entstehen keine neuen Hinweise.'; }
  else if (ki && (ki.zustand === 'fehlt' || ki.zustand === 'fehler')) { text = 'KI fehlt'; cls = 'fail'; title = ki.meldung || 'KI nicht verfügbar'; }
  else if (wiki && wiki.zustand === 'laedt') { text = 'Wiki lädt'; cls = 'laeuft'; title = wiki.meldung || 'Wiki wird gelesen …'; }
  else if (!wiki || wiki.zustand !== 'ok') { text = 'ohne Wiki'; cls = 'warn'; title = 'Ohne Wiki: nur Fragen und Essenz – keine Belege, keine Widersprüche.'; }
  else if (sf && sf.beendet) { text = 'beendet'; cls = 'fertig'; }
  else if (sf && running) { text = 'läuft'; cls = 'laeuft'; }
  else if (ki && ki.zustand === 'pause') { text = 'pausiert'; title = ki.meldung || ''; }
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
    ? `<div class="offen-titel">Offen:</div><ul>${e.offen.map((o) => `<li>${esc(o)}</li>`).join('')}</ul>` : '';
  return `<div class="ki-head">${tagKi()}Essenz ${esc(e.fenster || `${e.minuten} min`)}<span class="spacer"></span>`
    + `<span class="lag" title="Dauer der Erzeugung">erzeugt in ${secs(e.ki_s)}</span></div>`
    + (punkte ? `<ul>${punkte}</ul>` : '<p class="hint">Keine Punkte.</p>') + offen;
}

/** Nur die letzte Essenz offen; aeltere unter "Ältere Essenzen (n)". */
function renderEssenz() {
  const box = $('souffleurEssenz');
  if (!souffleurEssenzen.length) { box.hidden = true; box.innerHTML = ''; return; }
  const letzte = souffleurEssenzen[souffleurEssenzen.length - 1];
  const aeltere = souffleurEssenzen.slice(0, -1).reverse();
  box.innerHTML = essenzHtml(letzte) + (aeltere.length
    ? `<details class="older"><summary>${icon('chevron-right')}Ältere Essenzen (${aeltere.length})</summary>`
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
  const el = document.getElementById(id);
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
  row.scrollIntoView({ block: 'center', behavior: reducedMotion() ? 'auto' : 'smooth' });
  flash(row);
}

async function copyFundstelle(btn) {
  const use = btn.querySelector('use');
  try {
    await navigator.clipboard.writeText(btn.dataset.copy || '');
    btn.title = 'Kopiert';
    if (use) use.setAttribute('href', '#i-check');
  } catch (e) {
    btn.title = 'Kopieren nicht möglich';
  }
  setTimeout(() => { btn.title = 'Fundstelle kopieren'; if (use) use.setAttribute('href', '#i-copy'); }, 1500);
}

/** Ausblenden = nur Sicht (Streifen + keine Chips); die Auswertung laeuft weiter. Ein Frame, kein Uebergang. */
export function setSouffleurHidden(hidden) {
  if ($('liveAside').classList.contains('collapsed') === hidden) return;
  $('liveAside').classList.toggle('collapsed', hidden);
  document.body.classList.toggle('souffleur-hidden', hidden);
  if (!$('tabLive').hidden) (hidden ? $('souffleurShow') : $('souffleurHide')).focus({ preventScroll: true });
}

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
  if (copy) { e.preventDefault(); copyFundstelle(copy); }
};
