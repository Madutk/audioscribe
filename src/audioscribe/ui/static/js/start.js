// Startseite (vier Einstiege, zuletzt geoeffnete Projekte, unterbrochene Sitzungen) und der
// Assistent "Neues Projekt" (PRD §21).

import { $, S, api, post, esc, icon, hms, toast, fillOptions, sep, trimSep } from './kern.js';
import { go, HOME, setKontext, wechsle, oeffneProjekt, ladeKontext } from './kontext.js';
import { pickFolder } from './dialoge.js';
import { renderWikiState } from './wiki.js';

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
      const pfad = await pickFolder({ title: 'Projekt öffnen – Ordner des LLM-Wikis wählen', ok: 'Projekt in diesem Ordner öffnen',
        start: (S.kontext.zuletzt[0] && S.kontext.zuletzt[0].pfad) || '' });
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

const W = { step: 1, auto: { sitzungen: true, assets: true }, timer: null, gen: 0, optionen: null };
const wizWikiArt = () => document.querySelector('input[name="wizWikiArt"]:checked').value;
const wizBody = () => ({
  name: $('wizName').value.trim(),
  wurzel: $('wizWurzel').value.trim(),
  sitzungen_dir: $('wizSitzungen').value.trim(),
  assets_dir: $('wizAssets').value.trim(),
  neues_wiki: wizWikiArt() === 'neu',
});
const FELD = { name: 'wizErrName', wurzel: 'wizErrWurzel', sitzungen_dir: 'wizErrSitzungen', assets_dir: 'wizErrAssets' };
const SCHRITT = { 1: ['name', 'wurzel'], 2: ['sitzungen_dir', 'assets_dir'], 3: [] };

export async function enterNeu() {
  W.step = 1; W.auto = { sitzungen: true, assets: true };
  for (const id of ['wizName', 'wizSitzungen', 'wizAssets']) $(id).value = '';
  // Uebernahme einer Installation von vor den Projekten: das bisherige Wiki vorschlagen.
  $('wizWurzel').value = (S.kontext.alt && S.kontext.alt.wiki_dir) || '';
  document.querySelector('input[name="wizWikiArt"][value="vorhanden"]').checked = true;
  document.querySelector('input[name="wizSpeichern"][value="fragen"]').checked = true;
  $('wizBilder').checked = true;
  $('wizMarkierungen').checked = false;
  for (const id of [...Object.values(FELD), 'wizErr']) $(id).textContent = '';
  $('wizWikiState').hidden = true;
  showStep();
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
  if ($('wizWurzel').value) pruefe();
}

function showStep() {
  for (const n of [1, 2, 3]) $('wiz' + n).hidden = n !== W.step;
  for (const li of $('wizSteps').children) {
    const n = Number(li.dataset.step);
    li.classList.toggle('active', n === W.step);
    li.classList.toggle('done', n < W.step);
    if (n === W.step) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
  }
  $('wizBack').hidden = W.step === 1;
  $('wizNext').hidden = W.step === 3;
  $('wizCreate').hidden = W.step !== 3;
  $('wizErr').textContent = '';
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
  // Ordner vorschlagen, solange der Nutzer sie nicht selbst gesetzt hat
  if (r.vorschlag && r.vorschlag.sitzungen_dir) {
    if (W.auto.sitzungen) $('wizSitzungen').value = r.vorschlag.sitzungen_dir;
    if (W.auto.assets) $('wizAssets').value = r.vorschlag.assets_dir;
  }
  const neu = wizWikiArt() === 'neu';
  $('wizWikiState').hidden = neu || !$('wizWurzel').value.trim();
  // Wo das Transkript im Wiki landet - fest unter raw/, damit es der Ingest des Wikis findet.
  $('wizRaw').textContent = r.pfade.wurzel
    ? `${trimSep(r.pfade.wurzel)}${sep()}raw${sep()}<Datum>_<Sitzungstitel>${sep()}` : '–';
  if (r.wiki) renderWikiState($('wizWikiState'), r.wiki, false);
  // Neue Meldungen nur fuer die verlangten Felder; behobene verschwinden ueberall sofort.
  for (const feld of Object.keys(FELD)) {
    if (!r.fehler[feld]) $(FELD[feld]).textContent = '';
    else if (zeigen.includes(feld)) $(FELD[feld]).textContent = r.fehler[feld];
  }
  return r;
}

function pruefeSpaeter() {
  clearTimeout(W.timer);
  W.timer = setTimeout(() => pruefe(), 350);
}

async function weiter() {
  clearTimeout(W.timer);  // eine noch wartende Pruefung der Eingabe wuerde diese hier ueberholen
  // Die Vorschlaege haengen vom Wiki-Ordner ab - nach Schritt 1 einmal mit Vorschlag pruefen.
  let r = await pruefe({ zeigen: SCHRITT[W.step] });
  if (r && W.step === 1 && !r.fehler.name && !r.fehler.wurzel) r = await pruefe({ zeigen: SCHRITT[1] });
  if (!r || SCHRITT[W.step].some((f) => r.fehler[f])) return;
  W.step += 1;
  showStep();
  ($('wiz' + W.step).querySelector('input, select') || $('wizNext')).focus();
}

async function anlegen() {
  $('wizErr').textContent = '';
  $('wizCreate').disabled = true;
  try {
    const k = await post('/api/projekt/neu', {
      ...wizBody(),
      ki_dienst: $('wizKiDienst').value || null,
      souffleur_model: $('wizSouffleurModel').value || null,
      agent_model: $('wizAgentModel').value || null,
      sprache: $('wizSprache').value || null,
      wiki_speichern: document.querySelector('input[name="wizSpeichern"]:checked').value,
      wiki_bilder: $('wizBilder').checked,
      wiki_markierungen: $('wizMarkierungen').checked,
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

async function wizPick(feld, titel) {
  const pfad = await pickFolder({ title: titel, start: $(feld).value.trim() || $('wizWurzel').value.trim() });
  if (!pfad) return;
  $(feld).value = pfad;
  if (feld === 'wizSitzungen') W.auto.sitzungen = false;
  if (feld === 'wizAssets') W.auto.assets = false;
  pruefe({ zeigen: SCHRITT[W.step] });
}

$('pickWizWurzel').onclick = () => wizPick('wizWurzel', wizWikiArt() === 'neu' ? 'Ordner für das neue LLM-Wiki wählen' : 'Ordner des LLM-Wikis wählen');
$('pickWizSitzungen').onclick = () => wizPick('wizSitzungen', 'Ordner für Sitzungen wählen');
$('pickWizAssets').onclick = () => wizPick('wizAssets', 'Ordner für Bilder im Wiki wählen');
$('wizWurzel').oninput = pruefeSpaeter;
$('wizSitzungen').oninput = () => { W.auto.sitzungen = false; };
$('wizAssets').oninput = () => { W.auto.assets = false; };
for (const radio of document.querySelectorAll('input[name="wizWikiArt"]')) radio.onchange = () => pruefe({ zeigen: ['wurzel'] });
$('wizNext').onclick = weiter;
$('wizBack').onclick = () => { W.step -= 1; showStep(); };
$('wizCreate').onclick = anlegen;
$('viewNeu').addEventListener('keydown', (e) => {
  if (e.key !== 'Enter' || e.target.tagName !== 'INPUT' || e.target.type === 'radio' || e.target.type === 'checkbox') return;
  e.preventDefault();
  if (W.step < 3) weiter(); else anlegen();
});
