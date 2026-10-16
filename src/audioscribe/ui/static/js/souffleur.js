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
const HINT_OPEN = 3;             // hoechstens so viele Hinweise gleichzeitig aufgeklappt

const ART = {
  widerspruch: { cls: 'widerspruch', icon: 'zap', wort: 'Widerspruch', label: 'Widerspruch' },
  offener_punkt: { cls: 'offen', icon: 'circle-dashed', wort: 'Offen', label: 'Offener Punkt' },
  frage: { cls: 'frage', icon: 'help-circle', wort: 'Frage', label: 'Frage' },
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
}

/** Wiki-Zustand des Projekts in der Karte zeigen - nur solange keine Sitzung ihren eigenen meldet. */
export function zeigeWikiStatus() {
  if (!souffleurInfo) { renderWikiState($('souffleurWiki'), S.wikiStatus, true); renderWikiActions(S.wikiStatus); }
}

// --- Wiki "on the fly" wechseln (Projekt: dauerhaft in projekt.json; Sofort aufnehmen: global) ----

function renderWikiActions(w) {
  $('souffleurWikiActions').hidden = modus() === 'demo';
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

/** Markierung an die Transkriptzeile haengen: Klassen, Randstreifen, Chip nach .lag - der Text bleibt unberuehrt. */
export function markSegment(h) {
  const row = $('liveText').querySelector(`.seg[data-id="${CSS.escape(String(h.segment_id))}"]`);
  if (!row || row.querySelector('.mark')) return;
  const a = artOf(h);
  row.classList.add('marked', a.cls);
  row.dataset.hint = hintId(h);
  row.insertAdjacentHTML('beforeend',
    `<button class="mark ${a.cls}" type="button" data-goto-hint="${hintId(h)}" aria-label="${esc(tr('{art} – zum Hinweis {zeit}', { art: a.label, zeit: tc(h.t_start) }))}">`
    + `${icon(a.icon)}${esc(a.wort)}</button>`);
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

/** Inhalt je Art: Widerspruch = Gesagt + Beleg + KI-Einschaetzung; Frage = Beleg (+ Antwortvorschlag);
 *  ohne Befund = nur "Im Wiki liegt dazu nichts vor." - bewusst kein KI-Text (Entscheidung des Auftraggebers). */
function hintBodyHtml(h) {
  const said = `<p class="said">${h.sprecher ? tr('Gesagt ({sprecher}):', { sprecher: esc(h.sprecher) }) : tr('Gesagt:')} <q>${esc(h.aussage || '')}</q></p>`;
  if (!hatBeleg(h)) {
    return demoAktiv() ? `<p class="wiki none">${icon('plus')}${tr('Neu – steht noch nicht im Wiki.')}</p>`
      : `<p class="wiki none">${icon('book-x')}${tr('Im Wiki liegt dazu nichts vor.')}</p>`;
  }
  const her = herkunft(h);
  if (her) return gegenHtml(h, her) + kiHtml(h.art === 'frage' ? 'Antwortvorschlag' : 'Einschätzung', h.ki_text);
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
    + `<button class="ts" type="button" data-goto-seg="${esc(String(h.segment_id))}" title="${tr('Zur Transkriptzeile')}">${tc(h.t_start)}</button>`
    + `<span class="title">${esc(h.aussage || a.label)}</span>`
    + `<span class="lag" title="${tr('Verzögerung Aussage → Hinweis')}">${esc(lag)}</span></summary>`
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
  const her = herkunft(h);
  if (her) blinke(her.id);
  layoutHints();
  limitOpenHints();
  updateHintCount();
  $('souffleurLive').textContent = tr('{n} Hinweise, zuletzt: {art} {zeit}', { n: souffleurHints.length, art: artOf(h).label, zeit: tc(h.t_start) });
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
    if (!hatBeleg(h)) z.neu += 1;
    else if (h.art === 'widerspruch') z.widerspruch += 1;
    else if (h.art === 'frage') z.beantwortet += 1;
  }
  return z;
}

/** Offene Punkte: alle Hinweise mit offener_punkt=true (offener Punkt, Frage ohne Befund), neueste oben. */
function renderOpenPoints() {
  const offen = souffleurHints.filter((h) => h.offener_punkt).reverse();
  $('souffleurOpenCount').textContent = offen.length ? tr('({n} offen)', { n: offen.length }) : tr('(keine)');
  $('souffleurOpenList').innerHTML = offen.map((h) =>
    `<li><button class="ts" type="button" data-goto-seg="${esc(String(h.segment_id))}" title="${tr('Zur Transkriptzeile')}">[${tc(h.t_start)}]</button>`
    + `<span class="text">${esc(h.aussage || '')}</span><span class="mark offen">${icon('circle-dashed')}${tr('Offen')}</span></li>`).join('')
    || `<li class="hint">${tr('Noch keine offenen Punkte.')}</li>`;
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
