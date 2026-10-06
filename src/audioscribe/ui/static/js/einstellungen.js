// Einstellungen: global (KI, Sprache, Umgebung) und je Projekt (Ordner, Wiki-Ablage, KI und
// Sprache mit "globale Einstellung verwenden"). Aenderungen gelten sofort (PRD §21).

import { $, api, post, put, esc, icon, empty, projekt, fillOptions, toast, sep, trimSep } from './kern.js';
import { setKontext } from './kontext.js';
import { pickFolder } from './dialoge.js';
import { renderWikiState } from './wiki.js';

// --- Global -----------------------------------------------------------------------------

const G = { ki_dienst: 'gKiDienst', souffleur_model: 'gSouffleurModel', agent_model: 'gAgentModel', sprache: 'gSprache' };
const OPT = { ki_dienst: 'ki_dienste', souffleur_model: 'souffleur_models', agent_model: 'agent_models', sprache: 'sprachen' };
let einst = null;   // letzte Antwort von /api/einstellungen

function zeigeGlobal() {
  for (const [key, id] of Object.entries(G)) fillOptions($(id), einst.optionen[OPT[key]], einst.werte[key]);
}

export async function enterEinstellungen() {
  $('gErr').textContent = '';
  try {
    einst = await api('/api/einstellungen');
    zeigeGlobal();
  } catch (err) {
    $('gErr').textContent = err.message;
  }
  loadEnvironment();
}

for (const [key, id] of Object.entries(G)) {
  $(id).onchange = async () => {
    $('gErr').textContent = '';
    try {
      einst = await post('/api/einstellungen', { [key]: $(id).value });
      zeigeGlobal();
      toast('Einstellung gespeichert');
      // Die wirksamen Werte eines geoeffneten Projekts haengen davon ab.
      setKontext(await api('/api/kontext'));
    } catch (err) {
      $('gErr').textContent = err.message;
    }
  };
}

// --- Umgebung ---------------------------------------------------------------------------

let envLoaded = false;

async function loadEnvironment(refresh = false) {
  if (envLoaded && !refresh) return;
  envLoaded = true;
  $('envRefresh').disabled = true;
  $('envChecks').innerHTML = `<p class="hint">${icon('loader')} Prüfe die Umgebung … (ein paar Sekunden)</p>`;
  try {
    const data = await api('/api/environment' + (refresh ? '?refresh=1' : ''));
    $('envStamp').textContent = data.checked_at ? `– Stand ${data.checked_at}` : '';
    $('envChecks').innerHTML = data.checks
      ? data.checks.map((c) => `<div class="env ${esc(c.status.toLowerCase())}">
           <span class="badge ${esc(c.status.toLowerCase())}">${esc(c.status)}</span>
           <span class="name">${esc(c.name)}</span>
           <span class="detail">${esc(c.detail)}</span></div>`).join('')
      : empty('alert', 'Umgebungs-Check nicht ausführbar – „audioscribe doctor“ im Terminal versuchen.');
  } catch (err) {
    envLoaded = false;
    $('envChecks').innerHTML = `<p class="err">${esc(err.message)}</p>`;
  } finally {
    $('envRefresh').disabled = false;
  }
}
$('envRefresh').onclick = () => loadEnvironment(true);

// --- Projekt ----------------------------------------------------------------------------

const P = { ki_dienst: 'pKiDienst', souffleur_model: 'pSouffleurModel', agent_model: 'pAgentModel', sprache: 'pSprache' };

export async function enterProjekt() {
  $('pErr').textContent = '';
  if (!einst) {
    try { einst = await api('/api/einstellungen'); } catch (err) { $('pErr').textContent = err.message; }
  }
  zeigeProjekt();
  if (projekt() && projekt().hinweis) $('pErr').textContent = projekt().hinweis;
  // Das Wiki kann sich seit dem Oeffnen geaendert haben - Zustand frisch lesen.
  try { setKontext(await api('/api/kontext')); } catch (err) { /* Anzeige bleibt beim letzten Stand */ }
}

export function zeigeProjekt() {
  const p = projekt();
  if (!p || p.demo) return;
  $('pName').value = p.name;
  $('pWurzel').textContent = p.wurzel;
  renderWikiState($('setWikiState'), p.wiki, false);
  $('pSitzungen').value = p.sitzungen_dir;
  $('pAssets').value = p.assets_dir;
  $('pRaw').textContent = `${trimSep(p.raw_dir)}${sep()}<Datum>_<Sitzungstitel>${sep()}`;
  const radio = document.querySelector(`input[name="pSpeichern"][value="${p.wiki_speichern}"]`);
  if (radio) radio.checked = true;
  $('pBilder').checked = p.wiki_bilder !== false;
  $('pMarkierungen').checked = p.wiki_markierungen === true;
  if (!einst) return;
  for (const [key, id] of Object.entries(P)) {
    const global = einst.werte[key];
    const eigen = p.eigen[key] || '';
    let liste = einst.optionen[OPT[key]];
    const label = (liste.find((x) => x.id === global) || { label: global }).label;
    // Ein Projektwert ausserhalb der Liste (aelteres Modell) bleibt sichtbar und wirksam.
    if (eigen && !liste.some((x) => x.id === eigen)) liste = [{ id: eigen, label: eigen }, ...liste];
    fillOptions($(id), liste, eigen, `Globale Einstellung (${label})`);
  }
}

async function speichere(felder, meldung = 'Projekteinstellung gespeichert') {
  $('pErr').textContent = '';
  try {
    setKontext(await put('/api/projekt', { felder }));
    toast(meldung);
  } catch (err) {
    $('pErr').textContent = err.message;
  }
  zeigeProjekt();
}

$('pName').onchange = () => { if ($('pName').value.trim()) speichere({ name: $('pName').value.trim() }); else zeigeProjekt(); };
$('pSitzungen').onchange = () => speichere({ sitzungen_dir: $('pSitzungen').value.trim() });
$('pAssets').onchange = () => speichere({ assets_dir: $('pAssets').value.trim() });
$('pickPSitzungen').onclick = async () => {
  const pfad = await pickFolder({ title: 'Ordner für Sitzungen wählen', start: $('pSitzungen').value });
  if (pfad) speichere({ sitzungen_dir: pfad });
};
$('pickPAssets').onclick = async () => {
  const pfad = await pickFolder({ title: 'Ordner für Bilder im Wiki wählen', start: $('pAssets').value });
  if (pfad) speichere({ assets_dir: pfad });
};
for (const radio of document.querySelectorAll('input[name="pSpeichern"]')) {
  radio.onchange = () => speichere({ wiki_speichern: radio.value });
}
$('pBilder').onchange = () => speichere({ wiki_bilder: $('pBilder').checked });
$('pMarkierungen').onchange = () => speichere({ wiki_markierungen: $('pMarkierungen').checked });
for (const [key, id] of Object.entries(P)) {
  // Leerer Wert = wieder die globale Einstellung verwenden
  $(id).onchange = () => speichere({ [key]: $(id).value || null });
}
