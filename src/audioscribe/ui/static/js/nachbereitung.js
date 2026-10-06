// Nachbereitung / KI-Analyse: Quelle waehlen, Auftrag an den Agenten, Verlauf. Im Projekt
// dazu die Ablage ins Wiki - der Sitzung selbst und der fertigen Nachbereitung (PRD §21).

import { $, S, api, post, esc, icon, empty, hms, fill, appendLog, poller, modus, projekt, sep, trimSep, basename, toast } from './kern.js';
import { ladeDefaults } from './kontext.js';
import { pickFolder, showTranscript } from './dialoge.js';
import { openWikiDialog, slugify } from './wiki.js';

let anaOffset = 0;
let anaSource = null;     // Pfad der gewaehlten Transkription
let anaDefaults = null;
let anaSources = [];      // letzte Antwort von /api/agent/sources
let anaRunning = false;

const pollAna = poller(pollAnalyse, 1500);
const imProjekt = () => modus() === 'projekt';
const quelle = () => anaSources.find((s) => s.path === anaSource) || null;

let anaSichtbar = false;   // die Ansicht ist betreten und nicht wieder verlassen

export async function enterAna() {
  anaSichtbar = true;
  await ladeDefaults();
  const proj = imProjekt();
  $('anaSourceTitle').textContent = proj ? 'Sitzung' : 'Quelle';
  $('anaSourceHint').textContent = proj ? 'Sitzungen dieses Projekts' : 'fertige Transkriptionen im Speicherort';
  anaDefaults = await api('/api/agent/defaults');
  fill($('anaModel'), anaDefaults.models, anaDefaults.model);
  $('anaBash').checked = anaDefaults.bash !== false;
  $('anaSkillsDir').textContent = anaDefaults.skills_dir;
  $('anaOut').value = S.folders.agent_output_dir || anaDefaults.output_dir;
  $('anaSkills').innerHTML = anaDefaults.skills.length
    ? anaDefaults.skills.map((s) => `<label class="skill">
         <input type="checkbox" value="${esc(s.name)}" ${s.selected ? 'checked' : ''} />
         <span><b>${esc(s.name)}</b><span class="desc">${esc(s.description.slice(0, 220))}${s.description.length > 220 ? '…' : ''}</span></span>
       </label>`).join('')
    : empty('list', 'Keine Skills gefunden (AUDIOSCRIBE_AGENT_SKILLS_DIR).');
  // Vorwahl aus der Live-Ansicht bzw. von "Aufnahme transkribieren"
  if (S.vorwahl) { anaSource = S.vorwahl; S.vorwahl = null; $('anaName').value = ''; }
  await loadSources();
  if (anaSichtbar) pollAna.start();  // waehrend des Ladens verlassen: nicht unsichtbar abfragen
}

export function leaveAna() { anaSichtbar = false; pollAna.stop(); }

export function resetAna() {
  anaOffset = 0; anaSource = null; anaSources = []; anaRunning = false;
  for (const id of ['anaLog', 'anaErr']) $(id).textContent = '';
  for (const id of ['anaResult', 'anaWiki', 'anaHistory', 'anaTodos', 'anaChips', 'anaDocs']) $(id).innerHTML = '';
  delete $('anaResult').dataset.key;
  for (const id of ['anaName', 'anaContext', 'anaFiles']) $(id).value = '';
  $('anaProgress').hidden = true;
  $('anaHistoryCard').hidden = true;
}

// --- Quellen --------------------------------------------------------------------------------

function sourceBadges(s) {
  const b = [`<span class="badge">${s.frames ? s.frames + ' Bilder' : 'ohne Bilder'}</span>`];
  if (s.status === 'unterbrochen' || s.status === 'laeuft') b.push('<span class="badge warn">unterbrochen</span>');
  if (s.ablagen && s.ablagen.length) b.push('<span class="badge ok">im Wiki</span>');
  if (s.analysen && s.analysen.some((a) => a.status === 'fertig')) b.push('<span class="badge fertig">nachbereitet</span>');
  return `<span class="badges">${b.join('')}</span>`;
}

export async function loadSources() {
  try {
    const data = await api('/api/agent/sources?output_dir=' + encodeURIComponent(S.folders.output_dir));
    anaSources = data.sources;
    $('anaSourceDir').textContent = 'Gesucht in: ' + data.output_dir;
    if (!anaSources.some((s) => s.path === anaSource)) anaSource = anaSources[0]?.path || null;
    $('anaSources').innerHTML = anaSources.length
      ? anaSources.map((s) => `<label class="source">
           <input type="radio" name="anaSrc" value="${esc(s.path)}" ${s.path === anaSource ? 'checked' : ''} />
           <span class="name" title="${esc(s.path)}">${esc(s.titel || s.name)}${s.titel ? `<small>${esc(s.name)}</small>` : ''}</span>
           ${sourceBadges(s)}</label>`).join('')
      : empty('file-audio', imProjekt()
        ? 'Noch keine Sitzung in diesem Projekt – starte eine unter „Live-Sitzung“.'
        : 'Noch keine fertigen Transkriptionen im Speicherort.');
  } catch (err) {
    $('anaSources').innerHTML = `<p class="err">${esc(err.message)}</p>`;
    anaSources = [];
    anaSource = null;
  }
  vorschlagName();
  renderWiki();
  renderHistory();
  updateTarget();
}

/** Den Sitzungstitel bzw. Ordnernamen als Vorschlag fuer den Prozessnamen - nur solange noch leer. */
function vorschlagName() {
  const q = quelle();
  if (q && !$('anaName').value.trim()) $('anaName').value = q.titel || q.name;
}

/** Projekt: liegt die gewaehlte Sitzung schon im Wiki? Sonst der Knopf zum Speichern. */
function renderWiki() {
  const box = $('anaWiki');
  const q = quelle();
  const p = projekt();
  if (!imProjekt() || !p) { box.innerHTML = ''; return; }
  if (!q) { box.innerHTML = '<p class="hint">Sitzung wählen …</p>'; return; }
  const ablagen = (q.ablagen || []).filter((a) => (a.art || 'sitzung') === 'sitzung');
  const liste = ablagen.map((a) => `<div class="row"><span class="badge ok">gespeichert</span>
      <code title="${esc(a.ordner)}">${esc(basename(dirOf(a.ordner)))}/${esc(basename(a.ordner))}</code>
      <span class="hint">${esc((a.zeit || '').slice(0, 16))}${a.bilder ? ` · ${a.bilder} Bilder` : ' · ohne Bilder'}</span>
      <button class="ghost sm" type="button" data-folder="${esc(a.ordner)}">${icon('external')}Öffnen</button></div>`).join('');
  box.innerHTML = `<div class="wikistate">
      ${liste || `<p class="hint">Diese Sitzung liegt noch nicht im Wiki. Gespeichert wird nach <code>${esc(trimSep(p.raw_dir))}</code>, Bilder nach <code>${esc(trimSep(p.assets_dir))}</code>.</p>`}
      <div class="row">
        <button class="${ablagen.length ? 'secondary' : ''} sm" type="button" id="anaWikiSave">${icon('book-plus')}${ablagen.length ? 'Erneut speichern' : 'Ins Wiki speichern'}</button>
        <button class="ghost sm" type="button" data-preview="${esc(q.path)}" data-title="${esc(q.titel || q.name)}">${icon('file-text')}Transkript ansehen</button>
      </div></div>`;
}

const dirOf = (path) => trimSep(path).replace(/[\\/][^\\/]*$/, '');

/** Projekt: bisherige Nachbereitungen der gewaehlten Sitzung, je mit Ablage ins Wiki. */
function renderHistory() {
  const q = quelle();
  const analysen = (imProjekt() && q && q.analysen) || [];
  $('anaHistoryCard').hidden = !analysen.length;
  $('anaHistory').innerHTML = analysen.map((a) => {
    const imWiki = a.ablagen && a.ablagen.length;
    return `<div class="history-item">
      <span class="name">${esc(a.name)}</span>
      <span class="badge ${a.status === 'fertig' ? 'fertig' : a.status === 'fehler' ? 'fehler' : ''}">${esc(a.status)}</span>
      ${imWiki ? '<span class="badge ok">im Wiki</span>' : ''}
      <button class="ghost sm" type="button" data-folder="${esc(a.workspace)}">${icon('external')}Ordner</button>
      ${a.status === 'fertig' ? `<button class="${imWiki ? 'ghost' : 'secondary'} sm" type="button" data-nach-wiki="${esc(a.workspace)}">${icon('book-plus')}${imWiki ? 'Erneut ins Wiki' : 'Ins Wiki speichern'}</button>` : ''}
    </div>`;
  }).join('');
}

function updateTarget() {
  const name = $('anaName').value.trim();
  const ziel = `${trimSep(S.folders.agent_output_dir)}${sep()}${name ? slugify(name) : '<prozessname>'}`;
  $('anaTarget').innerHTML = `Ergebnisse landen in: <code>${esc(ziel)}</code>`;
  $('anaStart').disabled = !anaSource || !name || anaRunning;
}

// --- Lauf -----------------------------------------------------------------------------------

const rememberAnalyse = () => post('/api/state', {
  agent_bash: $('anaBash').checked,
  agent_skills: selectedSkills(),
}).catch(() => {});

const selectedSkills = () => [...$('anaSkills').querySelectorAll('input:checked')].map((i) => i.value);

async function startAnalyse() {
  $('anaErr').textContent = '';
  try {
    await post('/api/agent/start', {
      source: anaSource,
      name: $('anaName').value,
      output_dir: S.folders.agent_output_dir,
      context_text: $('anaContext').value,
      context_files: $('anaFiles').value.split('\n').map((l) => l.trim()).filter(Boolean),
      skills: selectedSkills(),
      model: $('anaModel').value,
      bash: $('anaBash').checked,
    });
    anaOffset = 0;
    $('anaLog').textContent = '';
    $('anaResult').innerHTML = '';
    delete $('anaResult').dataset.key;  // gleicher Name = gleicher Ordner: das neue Ergebnis trotzdem zeigen
    pollAnalyse();
  } catch (err) {
    $('anaErr').textContent = err.message;
  }
}

async function pollAnalyse() {
  let s;
  try { s = await api('/api/agent/status?offset=' + anaOffset); } catch (e) { return; }
  anaOffset = s.offset;
  appendLog($('anaLog'), s.lines);
  const lief = anaRunning;
  anaRunning = !!s.running;
  $('anaCancel').disabled = !s.running;
  $('anaElapsed').textContent = s.running
    ? `– ${s.name} läuft seit ${hms(s.elapsed_s)}` : '';
  updateTarget();
  renderProgress(s);

  const r = s.result;
  if (!s.running && s.workspace && s.returncode !== null && s.returncode !== undefined) {
    const status = r ? r.status : (s.returncode === 0 ? 'fertig' : 'fehler');
    const index = r && r.index ? `<br>Übersicht: <code>${esc(r.index)}</code>` : '';
    const err = r && r.fehler ? `<br>${esc(r.fehler)}` : '';
    const key = JSON.stringify([s.workspace, status, imProjekt()]);
    if ($('anaResult').dataset.key !== key) {
      $('anaResult').dataset.key = key;
      const knoepfe = status === 'fertig'
        ? `<div class="row" style="margin-top:8px"><button class="secondary sm" type="button" data-folder="${esc(s.workspace)}">${icon('external')}Ergebnisordner öffnen</button>`
          + (imProjekt() ? `<button class="sm" type="button" data-nach-wiki="${esc(s.workspace)}">${icon('book-plus')}Nachbereitung ins Wiki speichern</button>` : '')
          + '</div>'
        : '';
      $('anaResult').innerHTML = `<div class="result ${status === 'fertig' ? '' : 'fehler'}">
        <b>${esc(status)}</b><br>Ergebnisordner: <code>${esc(s.workspace)}</code>${index}${err}${knoepfe}</div>`;
    }
  }
  // Eine eben beendete Analyse erscheint in der Liste der Nachbereitungen.
  if (lief && !anaRunning) loadSources();
}

/**
 * Fortschritt aus dem Plan des Agenten (TodoWrite) - einen echten Prozentwert kennt er
 * nicht. Ohne Plan laeuft ein unbestimmter Balken; der Agent kann Schritte nachtragen,
 * dann darf der Balken auch zuruecklaufen.
 */
function renderProgress(s) {
  const p = s.progress;
  $('anaProgress').hidden = !p && !s.running;
  if ($('anaProgress').hidden) return;
  const total = p ? p.total : 0, done = p ? p.done : 0;
  const finished = !s.running && s.returncode === 0;

  if (total) {
    const now = p.current ? ` · jetzt: <span class="stage">${esc(p.current)}</span>` : '';
    $('anaStep').innerHTML = `Schritt ${Math.min(done + (p.current ? 1 : 0), total)} von ${total}${now}`;
  } else {
    $('anaStep').textContent = s.running ? 'Agent liest sich ein und plant …' : '';
  }
  $('anaBarWrap').classList.toggle('wait', s.running && !total);
  $('anaBar').style.width = (finished ? 100 : total ? Math.round((done / total) * 100) : 0) + '%';

  const chips = [];
  if (p && p.skill) chips.push(`<span class="badge laeuft">Skill: ${esc(p.skill)}</span>`);
  if (p && p.frames_total) chips.push(`<span class="badge">Standbilder angesehen: ${p.frames_seen} von ${p.frames_total}</span>`);
  $('anaChips').innerHTML = chips.join('');

  const mark = { completed: icon('check'), in_progress: icon('loader'), pending: icon('circle') };
  $('anaTodos').innerHTML = (p ? p.todos : []).map((t) =>
    `<li class="${esc(t.status)}"><span class="mark">${mark[t.status] || mark.pending}</span><span>${esc(t.content)}</span></li>`).join('');

  const docs = p ? p.docs : [];
  $('anaDocs').innerHTML = docs.length
    ? 'Dokumente: ' + docs.map((d) => `<code>${esc(d)}</code>`).join(', ') : '';
}

// --- Wiki-Ablage ----------------------------------------------------------------------------

async function speichereSitzung() {
  const q = quelle();
  if (!q) return;
  const ablage = await openWikiDialog({ path: q.path, name: q.name, titel: q.titel, frames: q.frames, ohneImmer: true });
  if (ablage) loadSources();
}

/** Dokumente einer fertigen Analyse ins Wiki legen - als KI-erzeugt, getrennt von der Quelle. */
async function speichereNachbereitung(workspace, btn) {
  const p = projekt();
  if (btn) btn.disabled = true;
  try {
    const ablage = await post('/api/wiki/speichern-nachbereitung', { workspace, bilder: !p || p.wiki_bilder !== false });
    toast(`Nachbereitung im Wiki: ${basename(ablage.ordner)}`);
    await loadSources();
  } catch (err) {
    toast(err.message, 'fehler');
  } finally {
    if (btn) btn.disabled = false;
  }
}

// --- Verdrahtung ----------------------------------------------------------------------------

$('anaSources').onchange = (e) => {
  if (e.target.name !== 'anaSrc') return;
  anaSource = e.target.value;
  $('anaName').value = '';
  vorschlagName();
  renderWiki();
  renderHistory();
  updateTarget();
};
$('tabAna').addEventListener('click', (e) => {
  if (e.target.closest('#anaWikiSave')) { speichereSitzung(); return; }
  const folder = e.target.closest('[data-folder]');
  if (folder) { post('/api/oeffnen', { pfad: folder.dataset.folder }).catch((err) => toast(err.message, 'fehler')); return; }
  const preview = e.target.closest('[data-preview]');
  if (preview) { showTranscript(preview.dataset.preview, preview.dataset.title); return; }
  const nach = e.target.closest('[data-nach-wiki]');
  if (nach) speichereNachbereitung(nach.dataset.nachWiki, nach);
});
$('anaRefresh').onclick = loadSources;
$('anaName').oninput = updateTarget;
$('anaBash').onchange = rememberAnalyse;
$('anaSkills').onchange = rememberAnalyse;
$('anaStart').onclick = startAnalyse;
$('anaCancel').onclick = () => api('/api/agent/cancel', { method: 'POST' }).catch(() => {});
$('pickAnaOut').onclick = async () => {
  const pfad = await pickFolder({ title: 'Ausgabeordner Analysen wählen', start: $('anaOut').value });
  if (pfad) setAnaOut(pfad);
};
$('anaOut').onchange = () => setAnaOut($('anaOut').value.trim());
function setAnaOut(pfad) {
  S.folders.agent_output_dir = pfad;
  $('anaOut').value = pfad;
  post('/api/state', { agent_output_dir: pfad }).catch(() => {});
  updateTarget();
}
