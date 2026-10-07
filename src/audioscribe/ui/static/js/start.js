// Startseite (vier Einstiege, zuletzt geoeffnete Projekte, unterbrochene Sitzungen) und der
// Assistent "Neues Projekt" (PRD §21).

import { $, S, api, post, esc, icon, hms, toast, fillOptions, sep, trimSep, dirname } from './kern.js';
import { go, HOME, setKontext, wechsle, oeffneProjekt, ladeKontext } from './kontext.js';
import { pickFolder } from './dialoge.js';
import { renderWikiState, slugify } from './wiki.js';

// --- Startseite ---------------------------------------------------------------------------

export function enterStart() {
  $('launchErr').textContent = '';
  renderStart();
  ladeKontext().catch(() => {});  // Liste und Banner frisch holen (z. B. nach einem Absturz)
}

export function renderStart() {
  const k = S.kontext;
  if (!k) return;
  // Zuletzt geoeffnet
  $('recentsBox').hidden = !k.zuletzt.length;
  $('recents').innerHTML = k.zuletzt.map((z) => `
    <div class="recent ${z.vorhanden ? '' : 'fehlt'}">
      ${icon(z.vorhanden ? 'book' : 'book-x')}
      <button class="open" type="button" data-open="${esc(z.pfad)}" ${z.vorhanden ? '' : 'disabled'}>
        <span>${esc(z.name || z.pfad)}</span>
        <small title="${esc(z.pfad)}">${esc(z.vorhanden ? z.pfad : 'nicht erreichbar: ' + z.pfad)}</small>
      </button>
      <button class="icon-btn" type="button" data-forget="${esc(z.pfad)}" aria-label="Aus der Liste entfernen" title="Aus der Liste entfernen (das Projekt bleibt erhalten)">${icon('x')}</button>
    </div>`).join('');
  // Demo nur, wenn die Demo-Daten da sind
  $('launchDemo').setAttribute('aria-disabled', String(!k.demo_verfuegbar));
  $('launchDemo').querySelector('.launch-go').disabled = !k.demo_verfuegbar;
  // Unterbrochene Sitzungen (Absturz, Stromausfall): ein Klick fuehrt zurueck in die Sitzung
  $('startBanner').innerHTML = (k.unterbrochen || []).map((s) => `
    <div class="banner" role="status">
      ${icon('triangle')}
      <div class="text"><b>Unterbrochene Sitzung${s.titel ? ` „${esc(s.titel)}“` : ''}</b> im Projekt ${esc(s.projekt_name || '')}
        <small>${esc(s.gestartet ? s.gestartet.replace('T', ' ').slice(0, 16) : s.name)} · ${hms(s.dauer_s || 0)} aufgezeichnet · ${s.segmente || 0} Abschnitte gesichert</small></div>
      <div class="actions"><button type="button" data-resume="${esc(s.projekt)}">${icon('folder-open')}Projekt öffnen und fortsetzen</button></div>
    </div>`).join('');
}

async function launch(what, btn) {
  $('launchErr').textContent = '';
  try {
    if (what === 'neu') go('#/neu');
    else if (what === 'datei' || what === 'demo') await wechsle(what);
    else if (what === 'oeffnen') {
      // Projektordner (enthaelt .audioscribe/) - bei aelteren Projekten ist das der Wiki-Ordner.
      const pfad = await pickFolder({ title: 'Projekt öffnen – Projektordner wählen', ok: 'Projekt in diesem Ordner öffnen',
        start: (S.kontext.zuletzt[0] && dirname(S.kontext.zuletzt[0].pfad)) || (S.kontext.neu && S.kontext.neu.speicherort) || '' });
      if (pfad) await oeffne(pfad);
    }
  } catch (err) {
    $('launchErr').textContent = err.message;
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function oeffne(pfad) {
  $('launchErr').textContent = '';
  try {
    await oeffneProjekt(pfad);
  } catch (err) {
    $('launchErr').textContent = err.message;
  }
}

$('viewStart').addEventListener('click', async (e) => {
  const go_ = e.target.closest('[data-launch]');
  if (go_) { launch(go_.dataset.launch); return; }
  const open = e.target.closest('[data-open]');
  if (open) { oeffne(open.dataset.open); return; }
  const resume = e.target.closest('[data-resume]');
  if (resume) { oeffne(resume.dataset.resume); return; }
  const forget = e.target.closest('[data-forget]');
  if (forget) {
    try { setKontext(await post('/api/projekte/vergessen', { pfad: forget.dataset.forget })); } catch (err) { toast(err.message, 'fehler'); }
  }
});

// --- Assistent "Neues Projekt" ---------------------------------------------------------------
//
// Vier Schritte mit einem roten Faden: (1) Projektordner, (2) Wiki - optional, (3) Sitzungen und
// Ablage, (4) KI und Sprache. Die Strukturvorschau unter den Schritten zeigt auf jedem Schritt,
// welche Ordner am Ende entstehen.

const W = { step: 1, auto: { ordnername: true, sitzungen: true, assets: true }, timer: null, gen: 0, optionen: null, pfade: null };
const wizWikiArt = () => document.querySelector('input[name="wizWikiArt"]:checked').value;
const wizWurzel = () => {
  const ort = trimSep($('wizSpeicherort').value.trim());
  const name = $('wizOrdnername').value.trim();
  if (!ort && !name) return '';
  return ort && name ? `${ort}${sep()}${name}` : (ort || name);
};
const wizBody = () => ({
  name: $('wizName').value.trim(),
  wurzel: wizWurzel(),
  wiki_art: wizWikiArt(),
  wiki_dir: $('wizWikiDir').value.trim(),
  sitzungen_dir: $('wizSitzungen').value.trim(),
  assets_dir: $('wizAssets').value.trim(),
});
const FELD = { name: 'wizErrName', wurzel: 'wizErrWurzel', wiki_dir: 'wizErrWikiDir', sitzungen_dir: 'wizErrSitzungen', assets_dir: 'wizErrAssets' };
const SCHRITT = { 1: ['name', 'wurzel'], 2: ['wiki_dir'], 3: ['sitzungen_dir', 'assets_dir'], 4: [] };
const LETZTER = 4;

export async function enterNeu() {
  W.step = 1; W.auto = { ordnername: true, sitzungen: true, assets: true }; W.pfade = null; W.wikiVorgeschlagen = false;
  for (const id of ['wizName', 'wizOrdnername', 'wizWikiDir', 'wizSitzungen', 'wizAssets']) $(id).value = '';
  const neu = S.kontext.neu || {};
  $('wizSpeicherort').value = neu.speicherort || '';
  // Uebernahme einer Installation von vor den Projekten: das bisherige Wiki anbieten.
  $('wizWikiDir').value = neu.wiki_dir || '';
  document.querySelector(`input[name="wizWikiArt"][value="${neu.wiki_dir ? 'vorhanden' : 'keins'}"]`).checked = true;
  document.querySelector('input[name="wizSpeichern"][value="fragen"]').checked = true;
  $('wizBilder').checked = true;
  $('wizMarkierungen').checked = false;
  for (const id of [...Object.values(FELD), 'wizErr']) $(id).textContent = '';
  $('wizWikiState').hidden = true;
  $('wizMehr').open = false;
  zeigeWikiArt();
  showStep();
  renderTree(null);
  $('wizName').focus();
  try {
    const e = await api('/api/einstellungen');
    W.optionen = e;
    const global = (liste, wert) => `Globale Einstellung (${(liste.find((x) => x.id === wert) || { label: wert }).label})`;
    fillOptions($('wizKiDienst'), e.optionen.ki_dienste, '', global(e.optionen.ki_dienste, e.werte.ki_dienst));
    fillOptions($('wizSouffleurModel'), e.optionen.souffleur_models, '', global(e.optionen.souffleur_models, e.werte.souffleur_model));
    fillOptions($('wizAgentModel'), e.optionen.agent_models, '', global(e.optionen.agent_models, e.werte.agent_model));
    fillOptions($('wizSprache'), e.optionen.sprachen, '', global(e.optionen.sprachen, e.werte.sprache));
  } catch (err) {
    $('wizErr').textContent = err.message;
  }
}

function showStep() {
  for (let n = 1; n <= LETZTER; n += 1) $('wiz' + n).hidden = n !== W.step;
  for (const li of $('wizSteps').children) {
    const n = Number(li.dataset.step);
    li.classList.toggle('active', n === W.step);
    li.classList.toggle('done', n < W.step);
    if (n === W.step) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
  }
  $('wizBack').hidden = W.step === 1;
  $('wizNext').hidden = W.step === LETZTER;
  $('wizCreate').hidden = W.step !== LETZTER;
  $('wizErr').textContent = '';
}

/** Felder des Wiki-Schritts und der Ablage je nach gewaehlter Wiki-Art ein- und ausblenden. */
function zeigeWikiArt() {
  const art = wizWikiArt();
  $('wizWikiDirField').hidden = art !== 'vorhanden';
  $('wizWikiAblage').hidden = art === 'keins';
  $('wizOhneWikiHint').hidden = art !== 'keins';
}

/** Strukturvorschau: der rote Faden durch alle Schritte - Zeilen, die umbrechen duerfen. */
function renderTree(r) {
  const s = sep();
  const pf = (r && r.pfade) || {};
  const ort = trimSep($('wizSpeicherort').value.trim());
  const name = $('wizOrdnername').value.trim();
  // Solange der Ordnername fehlt, steht ein Platzhalter - die Zeile bleibt lesbar.
  const wurzel = name ? trimSep(pf.wurzel || wizWurzel()) : `${ort || '…'}${s}<Projektordner>`;
  const art = wizWikiArt();
  const rel = (pfad) => {
    // Pfad relativ zum Projektordner, wenn er darin liegt - sonst absolut (mit Pfeil).
    const p = trimSep(pfad || '');
    if (!p) return null;
    const unten = (x) => x.toLowerCase().replace(/[\\/]/g, '/');
    return unten(p).startsWith(unten(wurzel) + '/') ? { innen: true, text: p.slice(wurzel.length + 1) } : { innen: false, text: p };
  };
  const rows = [];
  const row = (pfad, was, cls = '') => rows.push(`<div class="row ${cls}" role="listitem"><code>${esc(pfad)}</code><span class="was">${was}</span></div>`);
  row(`${wurzel}${s}`, 'Projektordner', 'root');
  row(`.audioscribe${s}projekt.json`, 'Projekteinstellungen');
  const aussen = [];
  const sitz = rel(pf.sitzungen_dir || $('wizSitzungen').value) || { innen: true, text: 'sitzungen' };
  const sitzText = `Sitzungen (live-…${s}) und KI-Analysen (analysen${s})`;
  if (sitz.innen) row(`${sitz.text}${s}`, sitzText); else aussen.push([`${sitz.text}${s}`, sitzText]);
  if (art === 'neu') {
    row(`llm-wiki${s}`, `neues LLM-Wiki – raw${s} (Quellen, Bilder) und wiki${s} (Seiten)`);
  } else if (art === 'vorhanden') {
    const wiki = rel(pf.wiki_dir || $('wizWikiDir').value);
    const text = `verknüpftes LLM-Wiki – raw${s} (Quellen) und wiki${s} (Seiten)`;
    if (!wiki) row('…', 'verknüpftes LLM-Wiki – Ordner noch wählen');
    else if (wiki.innen) row(`${wiki.text}${s}`, text);
    else aussen.push([`${wiki.text}${s}`, text]);
  } else {
    row('(kein Wiki)', 'Souffleur ohne Belege, keine Ablage ins Wiki');
  }
  for (const [pfad, was] of aussen) row(pfad, was, 'aussen');
  $('wizTree').innerHTML = rows.join('');
}

/** Angaben beim Server pruefen: Wiki-Zustand, Meldung je Feld, Vorschlaege fuer die Ordner. */
async function pruefe({ zeigen = [] } = {}) {
  const gen = ++W.gen;
  let r;
  try {
    r = await post('/api/projekt/pruefen', wizBody());
  } catch (err) {
    $('wizErr').textContent = err.message;
    return null;
  }
  if (gen !== W.gen) return null;  // eine neuere Eingabe ist unterwegs
  W.pfade = r.pfade;
  // Ordner vorschlagen, solange der Nutzer sie nicht selbst gesetzt hat
  if (r.vorschlag && r.vorschlag.sitzungen_dir) {
    if (W.auto.sitzungen) $('wizSitzungen').value = r.vorschlag.sitzungen_dir;
    if (W.auto.assets) $('wizAssets').value = r.vorschlag.assets_dir || '';
  }
  // Der gewaehlte Projektordner ist selbst ein Wiki (fruehere Projekte): verknuepfen anbieten.
  if (r.wurzel_ist_wiki && wizWikiArt() === 'keins' && !W.wikiVorgeschlagen) {
    W.wikiVorgeschlagen = true;
    document.querySelector('input[name="wizWikiArt"][value="vorhanden"]').checked = true;
    $('wizWikiDir').value = r.pfade.wurzel;
    zeigeWikiArt();
  }
  const vorhanden = wizWikiArt() === 'vorhanden';
  $('wizWikiState').hidden = !vorhanden || !$('wizWikiDir').value.trim();
  if (r.wiki) renderWikiState($('wizWikiState'), r.wiki, false);
  // Neue Meldungen nur fuer die verlangten Felder; behobene verschwinden ueberall sofort.
  for (const feld of Object.keys(FELD)) {
    if (!r.fehler[feld]) $(FELD[feld]).textContent = '';
    else if (zeigen.includes(feld)) $(FELD[feld]).textContent = r.fehler[feld];
  }
  if (r.fehler.assets_dir && zeigen.includes('assets_dir')) $('wizMehr').open = true;
  renderTree(r);
  return r;
}

function pruefeSpaeter() {
  clearTimeout(W.timer);
  W.timer = setTimeout(() => pruefe(), 350);
}

async function weiter() {
  clearTimeout(W.timer);  // eine noch wartende Pruefung der Eingabe wuerde diese hier ueberholen
  // Die Vorschlaege haengen von Projektordner und Wiki ab - nach Schritt 1 und 2 einmal mit Vorschlag pruefen.
  let r = await pruefe({ zeigen: SCHRITT[W.step] });
  if (r && W.step <= 2 && !SCHRITT[W.step].some((f) => r.fehler[f])) r = await pruefe({ zeigen: SCHRITT[W.step] });
  if (!r || SCHRITT[W.step].some((f) => r.fehler[f])) return;
  W.step += 1;
  showStep();
  ($('wiz' + W.step).querySelector('input:not([hidden]), select') || $('wizNext')).focus();
}

async function anlegen() {
  $('wizErr').textContent = '';
  $('wizCreate').disabled = true;
  const mitWiki = wizWikiArt() !== 'keins';
  try {
    const k = await post('/api/projekt/neu', {
      ...wizBody(),
      ki_dienst: $('wizKiDienst').value || null,
      souffleur_model: $('wizSouffleurModel').value || null,
      agent_model: $('wizAgentModel').value || null,
      sprache: $('wizSprache').value || null,
      wiki_speichern: mitWiki ? document.querySelector('input[name="wizSpeichern"]:checked').value : 'fragen',
      wiki_bilder: mitWiki ? $('wizBilder').checked : true,
      wiki_markierungen: mitWiki ? $('wizMarkierungen').checked : false,
    });
    setKontext(k);
    toast(`Projekt „${k.projekt.name}“ angelegt`);
    go(HOME.projekt);
  } catch (err) {
    $('wizErr').textContent = err.message;
  } finally {
    $('wizCreate').disabled = false;
  }
}

async function wizPick(feld, titel, start) {
  const pfad = await pickFolder({ title: titel, start: start || $(feld).value.trim() || wizWurzel() });
  if (!pfad) return;
  $(feld).value = pfad;
  if (feld === 'wizSitzungen') W.auto.sitzungen = false;
  if (feld === 'wizAssets') W.auto.assets = false;
  pruefe({ zeigen: SCHRITT[W.step] });
}

$('pickWizSpeicherort').onclick = () => wizPick('wizSpeicherort', 'Speicherort wählen – hier entsteht der Projektordner', $('wizSpeicherort').value.trim());
$('pickWizWikiDir').onclick = () => wizPick('wizWikiDir', 'Ordner des LLM-Wikis wählen', $('wizWikiDir').value.trim() || (S.kontext.neu && S.kontext.neu.speicherort) || '');
$('pickWizSitzungen').onclick = () => wizPick('wizSitzungen', 'Ordner für Sitzungen wählen');
$('pickWizAssets').onclick = () => wizPick('wizAssets', 'Ordner für Bilder im Wiki wählen', $('wizAssets').value.trim() || $('wizWikiDir').value.trim());
$('wizName').oninput = () => {
  if (W.auto.ordnername) $('wizOrdnername').value = slugify($('wizName').value);
  pruefeSpaeter();
};
$('wizOrdnername').oninput = () => { W.auto.ordnername = false; pruefeSpaeter(); };
$('wizSpeicherort').oninput = pruefeSpaeter;
$('wizWikiDir').oninput = pruefeSpaeter;
$('wizSitzungen').oninput = () => { W.auto.sitzungen = false; renderTree({ pfade: W.pfade }); };
$('wizAssets').oninput = () => { W.auto.assets = false; };
for (const radio of document.querySelectorAll('input[name="wizWikiArt"]')) {
  radio.onchange = () => { W.auto.assets = true; W.wikiVorgeschlagen = true; zeigeWikiArt(); pruefe({ zeigen: ['wiki_dir'] }); };
}
$('wizNext').onclick = weiter;
$('wizBack').onclick = () => { W.step -= 1; showStep(); };
$('wizCreate').onclick = anlegen;
$('viewNeu').addEventListener('keydown', (e) => {
  if (e.key !== 'Enter' || e.target.tagName !== 'INPUT' || e.target.type === 'radio' || e.target.type === 'checkbox') return;
  e.preventDefault();
  if (W.step < LETZTER) weiter(); else anlegen();
});
