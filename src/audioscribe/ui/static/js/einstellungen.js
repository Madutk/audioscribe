// Einstellungen: global (KI, Sprache, Umgebung) und je Projekt (Ordner, Wiki-Ablage, KI und
// Sprache mit "globale Einstellung verwenden"). Aenderungen gelten sofort (PRD §21).

import { $, S, api, post, put, esc, icon, empty, projekt, fillOptions, toast, sep, trimSep, dienstHinweis, modelleFuer, passendesModell } from './kern.js';
import { setKontext } from './kontext.js';
import { pickFolder, askConfirm } from './dialoge.js';
import { renderWikiState, loadWikiStatus } from './wiki.js';

// --- Global -----------------------------------------------------------------------------

const G = { ki_dienst: 'gKiDienst', souffleur_model: 'gSouffleurModel', agent_model: 'gAgentModel', sprache: 'gSprache' };
const OPT = { ki_dienst: 'ki_dienste', souffleur_model: 'souffleur_models', agent_model: 'agent_models', sprache: 'sprachen' };
let einst = null;   // letzte Antwort von /api/einstellungen

const MODELLE = ['souffleur_model', 'agent_model'];

function zeigeGlobal() {
  const dienst = einst.werte.ki_dienst;
  for (const [key, id] of Object.entries(G)) {
    // Modelle nur die des gewaehlten Dienstes (Claude-IDs bzw. lokale Tags).
    const liste = MODELLE.includes(key) ? modelleFuer(einst.optionen[OPT[key]], dienst) : einst.optionen[OPT[key]];
    fillOptions($(id), liste, einst.werte[key]);
  }
  $('gKiDienstHint').textContent = dienstHinweis(dienst);
}

/** Beim Dienstwechsel wandern die Modelle mit: ein Claude-Modell passt nicht zur lokalen KI
 *  und umgekehrt - sonst bliebe ein unpassender Wert gespeichert. */
function mitModellen(body, dienst, werte) {
  for (const key of MODELLE) body[key] = passendesModell(einst.optionen[OPT[key]], dienst, werte[key]);
  return body;
}

export async function enterEinstellungen() {
  $('gErr').textContent = '';
  try {
    einst = await api('/api/einstellungen');
    zeigeGlobal();
  } catch (err) {
    $('gErr').textContent = err.message;
  }
  zeigeEingang();
  loadEnvironment();
}

// --- Eingangsordner ("Sofort aufnehmen") ------------------------------------------------

function zeigeEingang() {
  $('gEingangDir').textContent = (S.kontext && S.kontext.eingang_dir) || '';
}

async function speichereEingang(pfad) {
  $('gEingangErr').textContent = '';
  try {
    await post('/api/state', { eingang_dir: pfad });
    setKontext(await api('/api/kontext'));
    zeigeEingang();
    toast('Eingangsordner gespeichert');
  } catch (err) {
    $('gEingangErr').textContent = err.message;
  }
}

$('gEingangWaehlen').onclick = async () => {
  const pfad = await pickFolder({ title: 'Eingangsordner für Aufnahmen ohne Projekt', ok: 'Diesen Ordner verwenden',
    start: (S.kontext && S.kontext.eingang_dir) || '' });
  if (pfad) speichereEingang(pfad);
};
$('gEingangStandard').onclick = () => speichereEingang('');

for (const [key, id] of Object.entries(G)) {
  $(id).onchange = async () => {
    $('gErr').textContent = '';
    try {
      let body = { [key]: $(id).value };
      if (key === 'ki_dienst') body = mitModellen(body, $(id).value, einst.werte);
      einst = await post('/api/einstellungen', body);
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
  // Wiki: Pfad und Zustand mit Wiki, sonst Hinweis mit den Wegen zu einem Wiki.
  const mit = !!p.hat_wiki;
  $('pWikiDir').hidden = !mit;
  $('pWikiDir').textContent = p.wiki_dir || '';
  renderWikiState($('setWikiState'), p.wiki, false);
  $('pWikiHintMit').hidden = !mit;
  $('pWikiHintOhne').hidden = mit;
  $('pWikiNeu').hidden = mit;
  $('pWikiVerknuepfen').textContent = mit ? 'Anderes Wiki verknüpfen' : 'Vorhandenes Wiki verknüpfen';
  $('pWikiVerknuepfen').prepend(iconNode('folder'));
  $('pWikiLoesen').hidden = !mit;
  $('pWikiOrdner').hidden = !mit;
  $('pAblageCard').hidden = !mit;
  $('pSitzungen').value = p.sitzungen_dir;
  $('pAssets').value = p.assets_dir || '';
  $('pRaw').textContent = mit ? `${trimSep(p.raw_dir)}${sep()}<Datum>_<Sitzungstitel>${sep()}` : '–';
  const radio = document.querySelector(`input[name="pSpeichern"][value="${p.wiki_speichern}"]`);
  if (radio) radio.checked = true;
  $('pBilder').checked = p.wiki_bilder !== false;
  $('pMarkierungen').checked = p.wiki_markierungen === true;
  if (!einst) return;
  const dienst = p.eigen.ki_dienst || einst.werte.ki_dienst;  // der im Projekt wirksame Dienst
  $('pKiDienstHint').textContent = dienstHinweis(dienst);
  for (const [key, id] of Object.entries(P)) {
    const global = einst.werte[key];
    const eigen = p.eigen[key] || '';
    let liste = MODELLE.includes(key) ? modelleFuer(einst.optionen[OPT[key]], dienst) : einst.optionen[OPT[key]];
    const label = (liste.find((x) => x.id === global) || { label: global }).label;
    // Ein Projektwert ausserhalb der Liste (aelteres Modell) bleibt sichtbar und wirksam.
    if (eigen && !liste.some((x) => x.id === eigen)) liste = [{ id: eigen, label: eigen }, ...liste];
    fillOptions($(id), liste, eigen, `Globale Einstellung (${label})`);
  }
}

/** Ein Icon als Knoten (fuer Knoepfe, deren Text wechselt). */
function iconNode(name) {
  const tpl = document.createElement('template');
  tpl.innerHTML = icon(name);
  return tpl.content.firstElementChild;
}

async function speichere(felder, meldung = 'Projekteinstellung gespeichert') {
  $('pErr').textContent = '';
  try {
    setKontext(await put('/api/projekt', { felder }));
    toast(meldung);
    // Das Wiki hat gewechselt: die Live-Ansicht soll den neuen Zustand kennen.
    if ('wiki_art' in felder || 'wiki_dir' in felder) loadWikiStatus().catch(() => {});
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
$('pWikiNeu').onclick = () => speichere({ wiki_art: 'neu' }, 'Wiki angelegt');
$('pWikiVerknuepfen').onclick = async () => {
  const p = projekt();
  const pfad = await pickFolder({ title: 'Ordner des LLM-Wikis wählen', ok: 'Dieses Wiki verknüpfen', start: (p && (p.wiki_dir || p.wurzel)) || '' });
  if (pfad) speichere({ wiki_art: 'vorhanden', wiki_dir: pfad }, 'Wiki verknüpft');
};
$('pWikiLoesen').onclick = async () => {
  const ok = await askConfirm({
    title: 'Verknüpfung zum Wiki lösen?',
    text: 'Das Projekt arbeitet danach ohne Wiki: keine Belege im Souffleur, keine Ablage ins Wiki. Die Dateien des Wikis bleiben unverändert liegen.',
    ok: 'Verknüpfung lösen',
  });
  if (ok) speichere({ wiki_art: 'keins' }, 'Verknüpfung gelöst');
};
for (const radio of document.querySelectorAll('input[name="pSpeichern"]')) {
  radio.onchange = () => speichere({ wiki_speichern: radio.value });
}
$('pBilder').onchange = () => speichere({ wiki_bilder: $('pBilder').checked });
$('pMarkierungen').onchange = () => speichere({ wiki_markierungen: $('pMarkierungen').checked });
for (const [key, id] of Object.entries(P)) {
  // Leerer Wert = wieder die globale Einstellung verwenden
  $(id).onchange = () => {
    const wert = $(id).value || null;
    if (key !== 'ki_dienst') return speichere({ [key]: wert });
    // Dienstwechsel im Projekt: Modelle passend dazu festlegen, zurueck zu global = alles global.
    const p = projekt();
    const felder = wert
      ? mitModellen({ ki_dienst: wert }, wert, { ...einst.werte, ...(p ? p.eigen : {}) })
      : { ki_dienst: null, souffleur_model: null, agent_model: null };
    return speichere(felder);
  };
}
