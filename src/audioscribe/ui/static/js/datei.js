// "Aufnahme transkribieren" (ohne Projekt): Dateien waehlen, Speicherort, Optionen, Fortschritt -
// und nach dem Lauf das Ergebnis mit dem Weg weiter zur KI-Analyse.

import { $, S, api, post, esc, icon, empty, hms, coarse, fill, markUnavailable, appendLog, poller, dirname, sep, trimSep, toast } from './kern.js';
import { go, ladeDefaults } from './kontext.js';
import { pickFiles, pickFolder, showTranscript } from './dialoge.js';

let scanned = [];            // zuletzt gescannte Dateien des gewaehlten Ordners
let gewaehlt = new Set();    // Dateinamen, die der Nutzer im Dialog angekreuzt hat
let offset = 0;              // gelesene Log-Zeilen
let bereit = false;          // Auswahlfelder gefuellt
let letzterLauf = null;      // Schluessel der zuletzt gezeigten Ergebniskarten

const pollStatus = poller(poll, 1000);

let dateiSichtbar = false;   // die Ansicht ist betreten und nicht wieder verlassen

export async function enterDatei() {
  dateiSichtbar = true;
  const d = await ladeDefaults();
  if (!dateiSichtbar) return;  // waehrend des Ladens verlassen: nicht unsichtbar abfragen
  if (!bereit) {
    bereit = true;
    fill($('model'), d.models, d.model);
    fill($('device'), d.devices, d.device);
    markUnavailable($('device'));
    $('diarize').checked = d.diarize !== false;
    fill($('frameSens'), d.sensitivities, d.frame_sensitivity);
    fill($('frameFmt'), d.frame_formats, d.frame_format);
    $('frames').checked = d.frames === true;
    toggleFrameOpts();
    $('pathHint').innerHTML = d.platform === 'windows'
      ? 'Pfade aus dem Explorer können direkt eingefügt werden – <code>C:\\Users\\…</code>.'
      : d.platform === 'mac'
        ? 'Pfade aus dem Finder können direkt eingefügt werden (<kbd>⌥</kbd> + „… als Pfadname kopieren“).'
        : 'Windows-Pfade können direkt eingefügt werden – <code>C:\\Users\\…</code> wird zu <code>/mnt/c/Users/…</code>.';
  }
  // Die Sprache ist eine Einstellung (global) - bei jedem Betreten frisch vorbelegen.
  fill($('language'), d.languages, d.language);
  $('outDir').value = S.folders.output_dir;
  pollStatus.start();
}

export function leaveDatei() { dateiSichtbar = false; pollStatus.stop(); }

export function resetDatei() {
  scanned = []; gewaehlt = new Set(); offset = 0; letzterLauf = null;
  $('files').innerHTML = empty('film', 'Noch keine Aufnahme gewählt.');
  $('log').textContent = '';
  $('summary').innerHTML = '';
  $('transResult').innerHTML = '';
  $('transTarget').textContent = '';
  for (const id of ['pathErr', 'startErr']) $(id).textContent = '';
  updateCount();
}

/** Die beiden Auswahlfelder sind nur sinnvoll, wenn die Erkennung ueberhaupt laeuft. */
function toggleFrameOpts() {
  const an = $('frames').checked;
  $('frameOpts').style.display = an ? '' : 'none';
  $('frameHint').style.display = an ? '' : 'none';
}

/** Zuletzt benutzte Optionen serverseitig merken (ueberlebt Neustart und Adresswechsel). */
const remember = () => post('/api/state', {
  frames: $('frames').checked,
  frame_sensitivity: $('frameSens').value,
  frame_format: $('frameFmt').value,
  model: $('model').value,
  device: $('device').value,
  diarize: $('diarize').checked,
}).catch(() => {});

// --- Dateien ------------------------------------------------------------------------------

async function waehleDateien() {
  const wahl = await pickFiles({ title: 'Aufnahme wählen', start: S.folders.input_dir });
  if (!wahl) return;
  S.folders.input_dir = wahl.dir;
  gewaehlt = new Set(wahl.names);
  post('/api/state', { input_dir: wahl.dir }).catch(() => {});
  await scan();
}

/** Medien des gewaehlten Ordners zeigen; angekreuzt ist, was der Nutzer gewaehlt hat. */
async function scan() {
  $('pathErr').textContent = '';
  if (!S.folders.input_dir || !gewaehlt.size) { updateCount(); return; }
  try {
    const data = await api(`/api/scan?input_dir=${encodeURIComponent(S.folders.input_dir)}`
      + `&output_dir=${encodeURIComponent(S.folders.output_dir)}`);
    S.folders.input_dir = data.input_dir;
    S.folders.output_dir = data.output_dir;
    $('outDir').value = data.output_dir;
    scanned = data.files;
    $('files').innerHTML = data.count
      ? data.files.map((f) => `<div class="file" data-name="${esc(f.name)}">
           <input type="checkbox" class="sel" ${gewaehlt.has(f.name) ? 'checked' : ''} aria-label="${esc(f.name)}" />
           <span class="body">
             <span class="name" title="${esc(f.name)}">${esc(f.name)}</span>
             <span class="meta"><span class="len">${f.seconds ? hms(f.seconds) : '?'}</span><span class="size">${f.mb} MB</span></span>
             <span class="bar"><i></i></span>
           </span>
           <span class="badge">${f.done ? 'bereits transkribiert' : 'offen'}</span></div>`).join('')
      : empty('file-audio', 'Keine Medien-Dateien in diesem Ordner.');
    $('transTarget').innerHTML = `Ordner: <code>${esc(data.input_dir)}</code> – weitere Dateien daraus lassen sich ankreuzen.`;
    updateCount();
  } catch (err) {
    $('pathErr').textContent = err.message;
    $('files').innerHTML = empty('film', 'Aufnahme wählen …');
    scanned = [];
    updateCount();
  }
}

const selectedNames = () => [...$('files').querySelectorAll('.file')]
  .filter((row) => row.querySelector('.sel').checked)
  .map((row) => row.dataset.name);

function updateCount() {
  const names = selectedNames();
  const seconds = scanned
    .filter((f) => names.includes(f.name))
    .reduce((sum, f) => sum + (f.seconds || 0), 0);
  $('fileCount').textContent = scanned.length && names.length
    ? `– ${names.length} gewählt${seconds ? ' · ' + hms(seconds) + ' Audio' : ''}`
    : '';
  $('start').disabled = names.length === 0;
}

async function setOutDir(pfad) {
  S.folders.output_dir = pfad;
  $('outDir').value = pfad;
  post('/api/state', { output_dir: pfad }).catch(() => {});
  await scan();
}

// --- Lauf ---------------------------------------------------------------------------------

async function start() {
  $('startErr').textContent = '';
  try {
    await post('/api/start', {
      input_dir: S.folders.input_dir,
      output_dir: $('outDir').value.trim() || S.folders.output_dir,
      files: selectedNames(),
      model: $('model').value,
      language: $('language').value,
      device: $('device').value,
      diarize: $('diarize').checked,
      frames: $('frames').checked,
      frame_sensitivity: $('frameSens').value,
      frame_format: $('frameFmt').value,
    });
    offset = 0;
    letzterLauf = null;
    $('log').textContent = '';
    $('summary').innerHTML = '';
    $('transResult').innerHTML = '';
    poll();
  } catch (err) {
    $('startErr').textContent = err.message;
  }
}

async function poll() {
  let s;
  try { s = await api('/api/status?offset=' + offset); } catch (e) { return; }
  offset = s.offset;

  // Nach einem Neuladen der Seite laeuft der Stapel weiter - seine Dateien wieder zeigen.
  if (s.files.length && !$('files').querySelector('.file')) {
    S.folders.input_dir = dirname(s.files[0].path);
    gewaehlt = new Set(s.files.map((f) => f.name));
    await scan();
  }

  appendLog($('log'), s.lines);
  $('start').disabled = s.running || selectedNames().length === 0;
  $('pickFiles').disabled = s.running;
  $('cancel').disabled = !s.running;

  if (s.running && s.current) {
    const stage = s.stage
      ? ` · <span class="stage">Stufe ${s.stage.index}/${s.stage.total}: ${esc(s.stage.name)}</span>` : '';
    $('status').innerHTML = `Datei ${s.current.index} von ${s.total}: <b>${esc(s.current.name)}</b>${stage}`;
  } else if (!s.running) {
    $('status').textContent = '';
  }

  // Die Marken und Balken der Dateiliste bleiben nach dem Lauf stehen.
  for (const f of s.files) {
    const row = $('files').querySelector(`.file[data-name="${CSS.escape(f.name)}"]`);
    if (!row) continue;
    const badge = row.querySelector('.badge');
    if (f.state === 'fehler' && !badge.classList.contains('fehler')) $('logBox').open = true;
    badge.textContent = f.state;
    badge.className = 'badge ' + f.state;
    row.querySelector('.bar > i').style.width = Math.round((f.fraction || 0) * 100) + '%';
  }

  const e = s.eta;
  $('overallBar').style.width =
    (e && e.audio_total_s ? Math.round((e.audio_done_s / e.audio_total_s) * 100) : (!s.running && s.summary ? 100 : 0)) + '%';
  if (e && e.audio_total_s) {
    const rest = e.eta_s === null ? 'Restzeit wird geschätzt …' : `noch ca. ${coarse(e.eta_s)}`;
    const unknown = e.unknown_count ? ` (+${e.unknown_count} ohne bekannte Laenge)` : '';
    $('eta').textContent = `${hms(e.audio_done_s)} von ${hms(e.audio_total_s)} Audio · ${rest}${unknown}`;
  } else {
    $('eta').textContent = s.running ? 'läuft …' : '–';
  }

  $('summary').innerHTML = s.summary ? `<div class="summary">${esc(s.summary)}</div>` : '';
  renderResults(s);
}

/** Je fertiger Aufnahme eine Karte: wo das Transkript liegt, Vorschau - und weiter zur KI. */
function renderResults(s) {
  // Fertig aus diesem Lauf - oder schon frueher transkribiert und jetzt wieder gewaehlt:
  // auch dann fuehrt der Weg ohne neuen Lauf weiter zur KI.
  const gewaehlteNamen = selectedNames();
  const namen = [...new Set([
    ...s.files.filter((f) => f.state === 'fertig').map((f) => f.name),
    ...scanned.filter((f) => f.done && gewaehlteNamen.includes(f.name)).map((f) => f.name),
  ])];
  const fertig = namen.map((name) => ({ name }));
  const outDir = s.output_dir || S.folders.output_dir;
  const key = JSON.stringify([outDir, namen, s.running]);
  if (key === letzterLauf) return;
  letzterLauf = key;
  if (!fertig.length) { $('transResult').innerHTML = ''; return; }
  const ordner = (f) => `${trimSep(outDir)}${sep()}${f.name.replace(/\.[^.]+$/, '')}`;
  const karten = fertig.map((f) => `
    <div class="card result-card">
      <h2 class="card-title">${icon('check')}<span class="name">${esc(f.name)}</span><span class="spacer"></span><span class="badge fertig">transkribiert</span></h2>
      <p class="hint path">Gespeichert unter <code>${esc(ordner(f))}</code></p>
      <div class="row">
        <button class="secondary sm" type="button" data-preview="${esc(ordner(f))}" data-title="${esc(f.name)}">${icon('file-text')}Transkript ansehen</button>
        <button class="secondary sm" type="button" data-folder="${esc(ordner(f))}">${icon('external')}Ordner öffnen</button>
      </div>
    </div>`).join('');
  const weiter = s.running ? '' : `
    <div class="next" id="transNext">
      <h3>Wie geht es weiter?</h3>
      <p>Das Transkript ist gespeichert. Du kannst hier aufhören – oder die KI Transkript und Bilder auswerten lassen.</p>
      <div class="next-grid">
        <div class="next-item"><b>${icon('sparkles')}Mit KI weiterverarbeiten</b>
          <span>Der Agent liest das Transkript${fertig.length > 1 ? ' einer Aufnahme' : ''} samt Standbildern und erstellt daraus
            Dokumente, z. B. eine Prozessbeschreibung.</span>
          <button type="button" data-ki="${esc(ordner(fertig[0]))}">Zur KI-Analyse${icon('arrow-right')}</button></div>
      </div>
    </div>`;
  $('transResult').innerHTML = karten + weiter;
}

// --- Verdrahtung ----------------------------------------------------------------------------

$('pickFiles').onclick = () => waehleDateien().catch((err) => { $('pathErr').textContent = err.message; });
$('pickOutDir').onclick = async () => {
  const pfad = await pickFolder({ title: 'Speicherort für Transkripte wählen', start: $('outDir').value });
  if (pfad) setOutDir(pfad);
};
$('outDir').onchange = () => setOutDir($('outDir').value.trim());
for (const id of ['model', 'device', 'diarize', 'frameSens', 'frameFmt']) $(id).onchange = remember;
$('frames').onchange = () => { toggleFrameOpts(); remember(); };
$('files').onclick = (e) => {
  if (e.target.classList.contains('sel')) updateCount();
  else if (e.target.classList.contains('name')) {
    const box = e.target.closest('.file').querySelector('.sel');
    box.checked = !box.checked;
    updateCount();
  }
};
$('start').onclick = start;
$('cancel').onclick = () => api('/api/cancel', { method: 'POST' }).catch(() => {});
$('transResult').onclick = (e) => {
  const preview = e.target.closest('[data-preview]');
  if (preview) { showTranscript(preview.dataset.preview, preview.dataset.title); return; }
  const folder = e.target.closest('[data-folder]');
  if (folder) { post('/api/oeffnen', { pfad: folder.dataset.folder }).catch((err) => toast(err.message, 'fehler')); return; }
  const ki = e.target.closest('[data-ki]');
  if (ki) {
    // Die KI-Analyse waehlt diese Aufnahme als Quelle vor.
    S.vorwahl = ki.dataset.ki;
    go('#/datei/ki');
  }
};

