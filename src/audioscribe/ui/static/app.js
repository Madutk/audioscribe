const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const icon = (name) => `<svg class="ic" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const empty = (name, text) => `<div class="empty">${icon(name)}${esc(text)}</div>`;


let defaults = null;      // /api/defaults
let scanned = [];         // zuletzt gescannte Dateien
let offset = 0;           // gelesene Log-Zeilen
let dlgTarget = null;     // 'in' | 'out'
let dlgPath = '';         // aktuell im Dialog gezeigter Ordner

async function api(path, opts) {
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (e) { /* leer */ }
  if (!res.ok) throw new Error((data && data.detail) || res.statusText);
  return data;
}

const post = (path, body) => api(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

// --- Design (hell/dunkel) ---------------------------------------------------
// Serverseitig gemerkt wie alle anderen Einstellungen; 'system' folgt dem Betriebssystem.
const THEMES = ['system', 'light', 'dark'];
const THEME_LABEL = { system: 'System', light: 'Hell', dark: 'Dunkel' };
function applyTheme(theme) {
  if (theme === 'system') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  $('themeToggle').dataset.theme = theme;
  $('themeToggle').setAttribute('aria-label', `Design: ${THEME_LABEL[theme]} – klicken zum Wechseln`);
}
applyTheme(THEMES.includes(document.documentElement.dataset.theme) ? document.documentElement.dataset.theme : 'system');
$('themeToggle').onclick = () => {
  const next = THEMES[(THEMES.indexOf($('themeToggle').dataset.theme) + 1) % THEMES.length];
  applyTheme(next);
  post('/api/state', { theme: next }).catch(() => {});
};

/** Protokolle sind eingeklappt; beim Aufklappen ans Ende springen. */
for (const box of document.querySelectorAll('details.log')) {
  box.addEventListener('toggle', () => { const pre = box.querySelector('pre'); if (box.open) pre.scrollTop = pre.scrollHeight; });
}

/** Sekunden -> "1:23:45" bzw. "4:05". */
function hms(seconds) {
  if (!seconds && seconds !== 0) return '–';
  const s = Math.round(seconds), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  const pad = (n) => String(n).padStart(2, '0');
  return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${m}:${pad(s % 60)}`;
}

/** Restzeit bewusst grob: unter 30 min auf Minuten, darueber auf 5 min gerundet. */
function coarse(seconds) {
  const min = Math.max(1, Math.round(seconds / 60));
  if (min < 30) return `${min} min`;
  const rounded = Math.round(min / 5) * 5;
  return rounded < 60 ? `${rounded} min` : `${Math.floor(rounded / 60)} h ${rounded % 60 || ''}`.trim();
}

// --- Start ------------------------------------------------------------------

async function init() {
  defaults = await api('/api/defaults');
  fill($('model'), defaults.models, defaults.model);
  fill($('language'), defaults.languages, defaults.language);
  fill($('device'), defaults.devices, defaults.device);
  if (defaults.cuda === false) {
    const opt = [...$('device').options].find((o) => o.value === 'cuda');
    if (opt) { opt.disabled = true; opt.textContent = 'cuda (nicht verfügbar)'; }
    if ($('device').value === 'cuda') $('device').value = 'auto';
  }
  $('diarize').checked = defaults.diarize !== false;
  fill($('frameSens'), defaults.sensitivities, defaults.frame_sensitivity);
  fill($('frameFmt'), defaults.frame_formats, defaults.frame_format);
  $('frames').checked = defaults.frames === true;
  toggleFrameOpts();
  $('pathHint').innerHTML = defaults.platform === 'windows'
    ? 'Pfade aus dem Explorer können direkt eingefügt werden – <code>C:\\Users\\…</code>. ' +
      'WSL-Pfade (<code>/mnt/c/…</code>) werden mit umgesetzt.'
    : 'Windows-Pfade können direkt eingefügt werden – <code>C:\\Users\\…</code> wird zu <code>/mnt/c/Users/…</code>.';
  $('inDir').value = defaults.input_dir;
  $('outDir').value = defaults.output_dir;
  await scan();
  setInterval(poll, 1000);
  poll();
}

/** Die beiden Auswahlfelder sind nur sinnvoll, wenn die Erkennung ueberhaupt laeuft. */
function toggleFrameOpts() {
  const an = $('frames').checked;
  $('frameOpts').style.display = an ? '' : 'none';
  $('frameHint').style.display = an ? '' : 'none';
}

function fill(sel, values, chosen) {
  const all = values.includes(chosen) ? values : [chosen, ...values];
  sel.innerHTML = all.map((v) => `<option value="${esc(v)}">${esc(v)}</option>`).join('');
  sel.value = chosen;
}

/** Ordner und Optionen serverseitig merken (ueberlebt Neustart und Adresswechsel). */
const remember = () => post('/api/state', {
  frames: $('frames').checked,
  frame_sensitivity: $('frameSens').value,
  frame_format: $('frameFmt').value,
  input_dir: $('inDir').value,
  output_dir: $('outDir').value,
  model: $('model').value,
  language: $('language').value,
  device: $('device').value,
  diarize: $('diarize').checked,
}).catch(() => {});

// --- Dateiliste -------------------------------------------------------------

async function scan() {
  $('pathErr').textContent = '';
  try {
    const data = await api(`/api/scan?input_dir=${encodeURIComponent($('inDir').value)}`
      + `&output_dir=${encodeURIComponent($('outDir').value)}`);
    $('inDir').value = data.input_dir;
    $('outDir').value = data.output_dir;
    scanned = data.files;
    $('files').innerHTML = data.count
      ? data.files.map((f) => `<div class="file" data-name="${esc(f.name)}">
           <input type="checkbox" class="sel" ${f.done ? '' : 'checked'} />
           <span class="body">
             <span class="name" title="${esc(f.name)}">${esc(f.name)}</span>
             <span class="meta"><span class="len">${f.seconds ? hms(f.seconds) : '?'}</span><span class="size">${f.mb} MB</span></span>
             <span class="bar"><i></i></span>
           </span>
           <span class="badge">${f.done ? 'bereits transkribiert' : 'offen'}</span></div>`).join('')
      : empty('file-audio', 'Keine Medien-Dateien in diesem Ordner.');
    updateCount();
  } catch (err) {
    $('pathErr').textContent = err.message;
    $('files').innerHTML = empty('folder', 'Eingangsordner wählen …');
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
  $('fileCount').textContent = scanned.length
    ? `– ${names.length} von ${scanned.length} ausgewählt${seconds ? ' · ' + hms(seconds) + ' Audio' : ''}`
    : '';
  $('start').disabled = names.length === 0;
}

function pick(mode) {
  for (const row of $('files').querySelectorAll('.file')) {
    const done = scanned.find((f) => f.name === row.dataset.name)?.done;
    row.querySelector('.sel').checked = mode === 'all' || (mode === 'open' && !done);
  }
  updateCount();
}

// --- Ordner-Dialog ----------------------------------------------------------

async function openDialog(target) {
  dlgTarget = target;
  $('dlgTitle').textContent = { in: 'Eingangsordner wählen', out: 'Ausgangsordner wählen',
                                ana: 'Ausgabeordner der Analyse wählen' }[target];
  $('dlgLinks').innerHTML = defaults.quick_links
    .map((l) => `<a data-path="${esc(l.path)}">${esc(l.label)}</a>`).join('');
  $('overlay').classList.add('open');
  await showDir(dlgInput(target).value);
}

async function showDir(path) {
  try {
    const data = await api('/api/browse?path=' + encodeURIComponent(path));
    dlgPath = data.path;
    const sep = defaults.platform === 'windows' ? '\\' : '/';
    $('dlgCrumbs').innerHTML = data.crumbs
      .map((c) => `<a data-path="${esc(c.path)}">${esc(c.name)}</a>`).join(`<span>${sep}</span>`);
    const up = data.parent ? `<div data-path="${esc(data.parent)}">${icon('arrow-up')}..</div>` : '';
    $('dlgList').innerHTML = up + (data.dirs.length
      ? data.dirs.map((d) => `<div data-path="${esc(d.path)}">${icon('folder')}${esc(d.name)}</div>`).join('')
      : empty('folder', 'Keine Unterordner.'));
    $('dlgInfo').textContent = `${data.path} – ${data.media_count} Medien-Datei(en)`;
  } catch (err) {
    $('dlgInfo').textContent = err.message;
  }
}

// --- Lauf -------------------------------------------------------------------

async function start() {
  $('startErr').textContent = '';
  try {
    await post('/api/start', {
      input_dir: $('inDir').value,
      output_dir: $('outDir').value,
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
    $('log').textContent = '';
    $('summary').innerHTML = '';
    poll();
  } catch (err) {
    $('startErr').textContent = err.message;
  }
}

async function poll() {
  let s;
  try { s = await api('/api/status?offset=' + offset); } catch (e) { return; }
  offset = s.offset;

  if (s.lines.length) {
    const log = $('log');
    const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    log.textContent += s.lines.join('\n') + '\n';
    if (atBottom) log.scrollTop = log.scrollHeight;
  }

  $('start').disabled = s.running || selectedNames().length === 0;
  $('cancel').disabled = !s.running;

  if (s.running && s.current) {
    const stage = s.stage
      ? ` · <span class="stage">Stufe ${s.stage.index}/${s.stage.total}: ${esc(s.stage.name)}</span>` : '';
    $('status').innerHTML = `Datei ${s.current.index} von ${s.total}: <b>${esc(s.current.name)}</b>${stage}`;
  } else if (!s.running) {
    $('status').textContent = '';
  }

  // Die Marken und Balken der Dateiliste bleiben nach dem Lauf stehen; erst ein
  // Ordnerwechsel liest sie ueber /api/scan neu ein.
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
    (e && e.audio_total_s ? Math.round((e.audio_done_s / e.audio_total_s) * 100) : 0) + '%';
  if (e && e.audio_total_s) {
    const rest = e.eta_s === null ? 'Restzeit wird geschätzt …' : `noch ca. ${coarse(e.eta_s)}`;
    const unknown = e.unknown_count ? ` (+${e.unknown_count} ohne bekannte Laenge)` : '';
    $('eta').textContent = `${hms(e.audio_done_s)} von ${hms(e.audio_total_s)} Audio · ${rest}${unknown}`;
  } else {
    $('eta').textContent = s.running ? 'läuft …' : '–';
  }

  $('summary').innerHTML = s.summary ? `<div class="summary">${esc(s.summary)}</div>` : '';
}

// --- Verdrahtung ------------------------------------------------------------

$('pickIn').onclick = () => openDialog('in');
$('pickOut').onclick = () => openDialog('out');
$('dlgCancel').onclick = () => $('overlay').classList.remove('open');
$('overlay').onclick = (e) => { if (e.target === $('overlay')) $('overlay').classList.remove('open'); };
const dlgInput = (target) => $({ in: 'inDir', out: 'outDir', ana: 'anaOut' }[target]);
$('dlgOk').onclick = () => {
  dlgInput(dlgTarget).value = dlgPath;
  $('overlay').classList.remove('open');
  if (dlgTarget === 'ana') updateTarget();
  else scan().then(remember);
};
for (const id of ['dlgList', 'dlgCrumbs', 'dlgLinks']) {
  $(id).onclick = (e) => { const p = e.target.closest('[data-path]')?.dataset.path; if (p) showDir(p); };
}
for (const id of ['inDir', 'outDir']) {
  $(id).onchange = () => scan().then(remember);
}
for (const id of ['model', 'language', 'device', 'diarize', 'frameSens', 'frameFmt']) {
  $(id).onchange = remember;
}
$('frames').onchange = () => { toggleFrameOpts(); remember(); };
$('files').onclick = (e) => {
  if (e.target.classList.contains('sel')) updateCount();
  else if (e.target.classList.contains('name')) {
    const box = e.target.closest('.file').querySelector('.sel');
    box.checked = !box.checked;
    updateCount();
  }
};
for (const btn of document.querySelectorAll('[data-pick]')) {
  btn.onclick = () => pick(btn.dataset.pick);
}
$('start').onclick = start;
$('cancel').onclick = () => api('/api/cancel', { method: 'POST' }).catch(() => {});

// --- KI-Analyse -------------------------------------------------------------

let anaOffset = 0;
let anaSource = null;     // Pfad der gewaehlten Transkription
let anaDefaults = null;

/** Wie audioscribe.agent.material.slugify - nur fuer die Vorschau des Zielordners. */
function slugify(text) {
  let v = text.trim().toLowerCase()
    .replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/ß/g, 'ss');
  v = v.normalize('NFKD').replace(/[^\x00-\x7f]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return v.slice(0, 80).replace(/-+$/, '') || 'analyse';
}

function updateTarget() {
  const sep = defaults && defaults.platform === 'windows' ? '\\' : '/';
  const out = $('anaOut').value.replace(/[\\/]+$/, '');
  $('anaTarget').textContent = $('anaName').value.trim()
    ? `Ergebnisse landen in: ${out}${sep}${slugify($('anaName').value)}` : '';
  $('anaStart').disabled = !anaSource || !$('anaName').value.trim() || anaRunning;
}

async function initAnalyse() {
  anaDefaults = await api('/api/agent/defaults');
  fill($('anaModel'), anaDefaults.models, anaDefaults.model);
  $('anaOut').value = anaDefaults.output_dir;
  $('anaBash').checked = anaDefaults.bash !== false;
  $('anaSkillsDir').textContent = anaDefaults.skills_dir;
  $('anaSkills').innerHTML = anaDefaults.skills.length
    ? anaDefaults.skills.map((s) => `<label class="skill">
         <input type="checkbox" value="${esc(s.name)}" ${s.selected ? 'checked' : ''} />
         <span><b>${esc(s.name)}</b><span class="desc">${esc(s.description.slice(0, 220))}${s.description.length > 220 ? '…' : ''}</span></span>
       </label>`).join('')
    : empty('list', 'Keine Skills gefunden (AUDIOSCRIBE_AGENT_SKILLS_DIR).');
  await loadSources();
  setInterval(pollAnalyse, 1500);
  pollAnalyse();
}

async function loadSources() {
  try {
    const data = await api('/api/agent/sources?output_dir=' + encodeURIComponent($('outDir').value));
    $('anaSourceDir').textContent = 'Gesucht in: ' + data.output_dir;
    if (!data.sources.some((s) => s.path === anaSource)) anaSource = data.sources[0]?.path || null;
    $('anaSources').innerHTML = data.sources.length
      ? data.sources.map((s) => `<label class="source">
           <input type="radio" name="anaSrc" value="${esc(s.path)}" ${s.path === anaSource ? 'checked' : ''} />
           <span class="name" title="${esc(s.path)}">${esc(s.name)}</span>
           <span class="badge">${s.frames ? s.frames + ' Bilder' : 'ohne Bilder'}</span>
           ${s.annotated ? '<span class="badge fertig">annotiert</span>' : ''}</label>`).join('')
      : empty('file-audio', 'Noch keine fertigen Transkriptionen im Ausgangsordner.');
  } catch (err) {
    $('anaSources').innerHTML = `<p class="err">${esc(err.message)}</p>`;
    anaSource = null;
  }
  updateTarget();
}

const rememberAnalyse = () => post('/api/state', {
  agent_output_dir: $('anaOut').value,
  agent_model: $('anaModel').value,
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
      output_dir: $('anaOut').value,
      context_text: $('anaContext').value,
      context_files: $('anaFiles').value.split('\n').map((l) => l.trim()).filter(Boolean),
      skills: selectedSkills(),
      model: $('anaModel').value,
      bash: $('anaBash').checked,
    });
    anaOffset = 0;
    $('anaLog').textContent = '';
    $('anaResult').innerHTML = '';
    pollAnalyse();
  } catch (err) {
    $('anaErr').textContent = err.message;
  }
}

let anaRunning = false;
async function pollAnalyse() {
  let s;
  try { s = await api('/api/agent/status?offset=' + anaOffset); } catch (e) { return; }
  anaOffset = s.offset;
  if (s.lines.length) {
    const log = $('anaLog');
    const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    log.textContent += s.lines.join('\n') + '\n';
    if (atBottom) log.scrollTop = log.scrollHeight;
  }
  anaRunning = !!s.running;
  $('anaCancel').disabled = !s.running;
  $('anaElapsed').textContent = s.running
    ? `– ${esc(s.name)} läuft seit ${hms(s.elapsed_s)}` : '';
  updateTarget();

  renderProgress(s);

  const r = s.result;
  if (!s.running && s.workspace && s.returncode !== null && s.returncode !== undefined) {
    const status = r ? r.status : (s.returncode === 0 ? 'fertig' : 'fehler');
    const index = r && r.index ? `<br>Übersicht: <code>${esc(r.index)}</code>` : '';
    const err = r && r.fehler ? `<br>${esc(r.fehler)}` : '';
    $('anaResult').innerHTML = `<div class="result ${status === 'fertig' ? '' : 'fehler'}">
      <b>${esc(status)}</b><br>Ergebnisordner: <code>${esc(s.workspace)}</code>${index}${err}</div>`;
  }
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

// --- Live Transcription -----------------------------------------------------

let liveDefaults = null;
let liveOffset = 0;        // gelesene Protokollzeilen
let liveEvOffset = 0;      // gelesene Ereignisse (Segmente, Standbilder)
let liveSource = { kind: 'monitor', id: 1 };  // kind: monitor | window (id = HWND) | none
let liveShots = [];        // {id, t, file}
let liveSession = null;
let liveRunning = false;
let lightboxIndex = 0;

const tc = (seconds) => {
  const s = Math.max(0, Math.round(seconds)), pad = (n) => String(n).padStart(2, '0');
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
};
const secs = (v) => (v === null || v === undefined) ? '–' : v.toFixed(1).replace('.', ',') + ' s';

function fillDevices(sel, devices, chosen) {
  const opts = [['default', 'Standardgerät'],
    ...devices.map((d) => [String(d.index), d.name + (d.default ? ' (Standard)' : '')]), ['none', 'aus']];
  sel.innerHTML = opts.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join('');
  // Gemerkt wird der NAME: die Indizes wechseln mit jedem an- oder abgesteckten Geraet.
  const byName = devices.find((d) => d.name === chosen);
  sel.value = byName ? String(byName.index) : (chosen === 'none' ? 'none' : 'default');
}

const deviceName = (sel, devices) => {
  const d = devices.find((x) => String(x.index) === sel.value);
  return d ? d.name : sel.value;
};

async function initLive() {
  await loadLiveDefaults();
  setInterval(pollLive, 500);
  pollLive();
}

async function loadLiveDefaults() {
  const d = liveDefaults = await api('/api/live/defaults');
  fillDevices($('liveMic'), d.mics, d.mic);
  fillDevices($('liveLoop'), d.loopbacks, d.loopback);
  fill($('liveModel'), d.models, d.model);
  fill($('liveRefineModel'), d.refine_models, d.refine_model);
  fill($('liveLang'), defaults.languages, d.language);
  fill($('liveDevice'), defaults.devices, d.device);
  fill($('liveSens'), defaults.sensitivities, d.sensitivity);
  fill($('liveFmt'), defaults.frame_formats, d.format);
  $('livePartials').checked = d.partials !== false;
  $('liveSpeakers').checked = d.speakers !== false;
  $('liveRefine').checked = d.refine !== false;
  $('liveProblems').textContent = d.problems.join(' · ');
  d.windows = d.windows || [];
  liveSource = pickLiveSource(d);
  renderSources();
}

const windowLabel = (w) => `${w.process} – ${w.title}`;

/** Gemerkte Quelle wiederfinden: Fenster ueber "Prozess – Titel" (ersatzweise nur den
 *  Prozess - Titel wechseln mit dem Inhalt), Monitore ueber den Index. */
function pickLiveSource(d) {
  if (d.source === 'window' && d.windows.length) {
    const genau = d.windows.find((w) => windowLabel(w) === d.window);
    const prozess = genau || d.windows.find((w) => d.window.startsWith(`${w.process} – `));
    if (prozess) return { kind: 'window', id: prozess.hwnd };
  }
  if (d.source === 'none') return { kind: 'none', id: 0 };
  if (d.monitors.some((m) => String(m.index) === String(d.monitor))) return { kind: 'monitor', id: Number(d.monitor) };
  if (String(d.monitor) === '0' || !d.monitors.length) return { kind: 'none', id: 0 };
  return { kind: 'monitor', id: d.monitors[0].index };
}

const isActive = (kind, id) => liveSource.kind === kind && liveSource.id === id;

/** Vorschaubild, das bei 404 (Fenster weg oder minimiert) zu einem Platzhalter wird. */
function fallbackOnError(root, text) {
  for (const img of root.querySelectorAll('img[data-fallback]')) {
    img.onerror = () => { img.replaceWith(Object.assign(document.createElement('div'), { className: 'none', textContent: text })); };
  }
}

const sourceTile = (kind, id, inner) =>
  `<div class="monitor ${isActive(kind, id) ? 'active' : ''}" data-kind="${kind}" data-id="${id}" tabindex="0" role="button">${inner}</div>`;

/** Die eine Kachel "Anwendungsfenster" in der Karte: gewaehltes Fenster mit Vorschau oder Platzhalter.
 *  Sie oeffnet den Auswahldialog und traegt darum KEIN data-kind. */
function windowTileHtml(stamp) {
  const chosen = liveSource.kind === 'window' && liveDefaults.windows.find((w) => w.hwnd === liveSource.id);
  if (!chosen && !liveDefaults.windows.length && liveSource.kind !== 'window') return '';  // z. B. ausserhalb von Windows
  const attrs = 'data-winpick="window" tabindex="0" role="button" aria-haspopup="dialog" title="Anwendungsfenster wählen"';
  if (!chosen) {
    return `<div class="monitor pick" ${attrs}><div class="none">${icon('image')}Fenster wählen …</div>Anwendungsfenster</div>`;
  }
  return `<div class="monitor pick active" ${attrs}><img src="/api/live/window/${chosen.hwnd}?t=${stamp}" alt="" data-fallback />`
    + `<span class="title" title="${esc(chosen.title)}">${esc(chosen.title)}</span>`
    + `<span class="sub">${esc(chosen.process)} · ändern</span></div>`;
}

function renderSources() {
  const stamp = Date.now();  // Vorschaubild nie aus dem Browser-Cache
  const monitors = liveDefaults.monitors.map((m) =>
    sourceTile('monitor', m.index, `<img src="/api/live/monitor/${m.index}?t=${stamp}" alt="" />Monitor ${m.index} · ${m.width}×${m.height}`))
    .join('') + sourceTile('none', 0, '<div class="none">ohne Bildschirm</div>nur Ton');
  $('liveMonitors').innerHTML = `<div class="monitors">${monitors}${windowTileHtml(stamp)}</div>`;
  fallbackOnError($('liveMonitors'), 'kein Bild');
  updateSourceHint();
}

/** Nur die Fenster-Kachel neu zeichnen und die Markierung setzen - Monitorbilder bleiben stehen. */
function renderWindowTile() {
  const old = $('liveMonitors').querySelector('[data-winpick]');
  const html = windowTileHtml(Date.now());
  if (old) old.outerHTML = html;
  else if (html) $('liveMonitors').querySelector('.monitors').insertAdjacentHTML('beforeend', html);
  for (const t of $('liveMonitors').querySelectorAll('.monitor[data-kind]')) {
    t.classList.toggle('active', isActive(t.dataset.kind, Number(t.dataset.id)));
  }
  fallbackOnError($('liveMonitors'), 'kein Bild');
  updateSourceHint();
}

function updateSourceHint() {
  $('liveSourceHint').textContent = liveSource.kind === 'window'
    ? 'Nur das gewählte Fenster wird abgetastet – diese Oberfläche darf auf demselben Monitor liegen.'
    : liveSource.kind === 'monitor'
      ? 'Diese Oberfläche gehört nicht auf den überwachten Monitor – neue Thumbnails würden sonst selbst Bildwechsel auslösen.'
      : '';
}

function updateLiveTarget() {
  const sep = defaults && defaults.platform === 'windows' ? '\\' : '/';
  $('liveTarget').textContent = `Gespeichert wird unter: ${$('outDir').value.replace(/[\\/]+$/, '')}${sep}live-JJJJ-MM-TT_hh-mm-ss`;
}

function resetLiveView() {
  liveOffset = 0; liveEvOffset = 0; liveShots = []; liveSession = null; lightboxIndex = 0;
  $('liveText').innerHTML = empty('mic', 'Noch keine Sitzung.');
  $('liveThumbs').innerHTML = empty('image', 'Bildwechsel erscheinen hier.');
  $('liveLog').textContent = '';
  $('liveResult').innerHTML = '';
  $('liveFazit').innerHTML = ''; $('liveFazit').hidden = true;
  $('liveShotCount').textContent = '';
  $('lightbox').classList.remove('open');
}

/** Alles auf Anfang. Laeuft gerade eine Sitzung, wird sie verworfen und sofort neu begonnen. */
async function resetLive() {
  const restart = liveRunning;
  const ok = await askConfirm(restart ? {
    title: 'Laufende Sitzung verwerfen?',
    text: 'Die Aufnahme wird sofort abgebrochen, ohne Nachschärfen. Anschließend beginnt eine neue Sitzung '
      + 'mit denselben Einstellungen. Die bisherigen Dateien bleiben im Sitzungsordner liegen.',
    ok: 'Verwerfen und neu beginnen',
  } : {
    title: 'Ansicht zurücksetzen?',
    text: 'Transkript, Screenshots und Protokoll verschwinden aus der Oberfläche. '
      + 'Der Sitzungsordner auf der Platte bleibt unverändert.',
    ok: 'Zurücksetzen',
  });
  if (!ok) return;
  $('liveErr').textContent = '';
  $('liveReset').disabled = true;
  try {
    const r = await post('/api/live/reset', {});
    resetLiveView();
    if (restart) await startLive();
    else await pollLive();
    if (r.discarded) $('liveLog').textContent = `Verworfene Sitzung liegt noch unter: ${r.discarded}\n` + $('liveLog').textContent;
  } catch (err) {
    $('liveErr').textContent = err.message;
  } finally {
    $('liveReset').disabled = false;
  }
}

async function startLive() {
  $('liveErr').textContent = '';
  try {
    await post('/api/live/start', {
      output_dir: $('outDir').value,
      monitor: liveSource.kind === 'monitor' ? liveSource.id : 0,
      window: liveSource.kind === 'window' ? liveSource.id : 0,
      window_label: liveSource.kind === 'window'
        ? windowLabel(liveDefaults.windows.find((w) => w.hwnd === liveSource.id) || { process: '', title: '' }) : '',
      mic: $('liveMic').value,
      loopback: $('liveLoop').value,
      mic_name: deviceName($('liveMic'), liveDefaults.mics),
      loopback_name: deviceName($('liveLoop'), liveDefaults.loopbacks),
      model: $('liveModel').value,
      language: $('liveLang').value,
      device: $('liveDevice').value,
      sensitivity: $('liveSens').value,
      format: $('liveFmt').value,
      partials: $('livePartials').checked,
      speakers: $('liveSpeakers').checked,
      refine: $('liveRefine').checked,
      refine_model: $('liveRefineModel').value,
    });
    resetLiveView();
    pollLive();
  } catch (err) {
    $('liveErr').textContent = err.message;
  }
}

/** Beide Spuren melden unabhaengig - eingefuegt wird darum nach Zeit, nicht nach Ankunft. */
function insertByTime(el, t) {
  el.dataset.t = t;
  const box = $('liveText');
  let after = null;
  for (const node of [...box.children].reverse()) {
    if (node.classList.contains('partial')) continue;
    if (Number(node.dataset.t) <= t) { after = node; break; }
  }
  if (after) after.after(el);
  else box.prepend(el);
}

function addLiveEvent(ev) {
  const el = document.createElement('p');
  if (ev.type === 'segment') {
    el.className = 'seg ' + (ev.track === 'mic' ? 'mic' : 'system');
    el.innerHTML = `<span class="ts">[${tc(ev.start)}]</span><span class="who">${esc(ev.speaker)}:</span> `
      + `${esc(ev.text)}<span class="lag" title="Verzögerung bis zur Anzeige">${secs(ev.delay)}</span>`;
    insertByTime(el, ev.start);
  } else if (ev.type === 'shot') {
    const index = liveShots.push(ev) - 1;
    const label = `Bild #${String(ev.id).padStart(4, '0')} – ${tc(ev.t)}`;
    el.className = 'shotmark';
    el.dataset.shot = index;
    el.innerHTML = icon('camera') + esc(label);
    insertByTime(el, ev.t);
    if (index === 0) $('liveThumbs').innerHTML = '';
    $('liveThumbs').insertAdjacentHTML('beforeend',
      `<div class="thumb" data-shot="${index}"><img loading="lazy" src="${shotUrl(ev)}" alt="" />${esc(label)}</div>`);
    $('liveShotCount').textContent = `– ${liveShots.length}`;
  }
}

const shotUrl = (shot) => `/api/live/frame/${encodeURIComponent(shot.file)}?s=${encodeURIComponent(liveSession || '')}`;

const PHASES = {
  startet: 'startet …', laden: 'Modell wird geladen …', laeuft: 'Aufnahme läuft', stoppt: 'wird abgeschlossen …',
  fertig: 'gespeichert', nachschaerfen: 'Nachschärfen …', beendet: 'beendet', fehler: 'Fehler',
};

function gauge(boxId, valueId, value, warn, bad) {
  $(valueId).textContent = secs(value);
  $(boxId).className = 'gauge ' + (value === null || value === undefined ? '' : value < warn ? 'ok' : value < bad ? 'warn' : 'err');
}

async function pollLive() {
  let s;
  try { s = await api(`/api/live/status?offset=${liveOffset}&ev_offset=${liveEvOffset}`); } catch (e) { return; }
  if (s.ev_offset < liveEvOffset || s.offset < liveOffset) { resetLiveView(); return; }  // neue Sitzung
  liveSession = s.session || liveSession;
  liveOffset = s.offset;
  liveEvOffset = s.ev_offset;

  const box = $('liveText');
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
  for (const node of box.querySelectorAll('.partial')) node.remove();
  const partials = Object.values(s.partials || {});
  if ((s.events.length || partials.length) && box.querySelector('.empty')) box.innerHTML = '';
  for (const ev of s.events) addLiveEvent(ev);
  for (const p of partials) {
    box.insertAdjacentHTML('beforeend', `<p class="seg partial"><span class="ts">[${tc(p.start)}]</span>${esc(p.text)} …</p>`);
  }
  if (atBottom) box.scrollTop = box.scrollHeight;

  if (s.lines.length) {
    const log = $('liveLog');
    log.textContent += s.lines.join('\n') + '\n';
    log.scrollTop = log.scrollHeight;
  }

  const running = liveRunning = !!s.running;
  $('liveStart').hidden = running;
  $('liveStop').hidden = !running;
  $('liveStopLabel').textContent = s.phase === 'nachschaerfen' ? 'Nachschärfen abbrechen'
    : s.stopping ? 'Sofort abbrechen' : 'Stoppen';
  // Erst sichtbar, wenn es etwas zurueckzusetzen gibt; waehrend der Aufnahme heisst es "Neu beginnen".
  $('liveReset').hidden = !running && !s.dir && !s.phase;
  $('liveResetLabel').textContent = running ? 'Verwerfen und neu beginnen' : 'Zurücksetzen';
  $('livePhase').textContent = PHASES[s.phase] || 'bereit';
  $('livePhase').className = 'badge ' + ({ laeuft: 'laeuft', fehler: 'fehler', beendet: 'fertig' }[s.phase] || '');

  const st = s.stats;
  $('liveElapsed').textContent = st ? hms(st.elapsed) : '–';
  gauge('liveDelayBox', 'liveDelay', st ? st.delay : null, 5, 10);
  gauge('liveBacklogBox', 'liveBacklog', st ? st.backlog : null, 3, 10);
  // Tooltip: gemessenes Tempo (Rechenzeit je Audiosekunde) und was die Sitzung gerade drosselt.
  const hints = [];
  if (st && st.rtf !== null && st.rtf !== undefined) hints.push(`Tempo ${st.rtf.toLocaleString('de-DE')}× Echtzeit`);
  if (st && st.catchup) hints.push('Aufholmodus: Abschnitte zusammengelegt, sparsam dekodiert');
  if (st && st.partials_paused) hints.push('Vorschautext pausiert, bis der Rückstand abgebaut ist');
  $('liveBacklog').title = hints.join(' · ');
  $('liveLevelMic').style.width = Math.min(100, (st && running ? st.level_mic || 0 : 0) * 150) + '%';
  $('liveLevelSys').style.width = Math.min(100, (st && running ? st.level_sys || 0 : 0) * 150) + '%';

  // Beim ersten Start wird das Modell heruntergeladen; aus dem Cache gibt es keine Byte-Meldung.
  const dl = s.download;
  const mb = (bytes) => Math.round(bytes / 1048576);
  $('liveLoadBox').hidden = s.phase !== 'laden';
  $('liveLoadBarBox').classList.toggle('wait', !dl);
  $('liveLoadStep').textContent = dl
    ? `Modell ${dl.model} wird heruntergeladen – ${mb(dl.done)} von ${mb(dl.total)} MB (${Math.floor(dl.done / dl.total * 100)} %)`
    : `Modell ${s.model || ''} wird geladen …${s.step ? ' – ' + s.step : ''}`;
  $('liveLoadBar').style.width = dl ? (dl.done / dl.total * 100) + '%' : '';

  const r = s.refine;
  $('liveRefineBox').hidden = s.phase !== 'nachschaerfen';
  if (r && r.index) {
    $('liveRefineStep').innerHTML = `Nachschärfen – <span class="stage">Stufe ${r.index}/${r.total}: ${esc(r.name)}</span>`;
    $('liveRefineBar').style.width = Math.round(((r.index - 1) + (r.percent || 0) / 100) / r.total * 100) + '%';
  }

  renderFazit(s.fazit);
  $('liveResult').innerHTML = !running && s.dir
    ? `<div class="result ${s.phase === 'fehler' ? 'fehler' : ''}">Sitzungsordner: <code>${esc(s.dir)}</code><br>
       Erscheint im Reiter „KI-Analyse“ als Quelle. Die Live-Fassung liegt als <code>transkript.live.md</code> daneben.</div>` : '';
}

/** Fazit (Rechendauer, Latenz) der Live-Aufnahme und des Nachschaerfens - erscheint,
 *  sobald der jeweilige Teil fertig ist, und bleibt bis zum Zuruecksetzen stehen. */
function renderFazit(f) {
  const box = $('liveFazit');
  if (!f || (!f.live && !f.nachschaerfen)) { box.hidden = true; box.innerHTML = ''; return; }
  const tempo = (v) => (v === null || v === undefined) ? '' : ` (${v.toLocaleString('de-DE')}× Echtzeit)`;
  const rows = [];
  const l = f.live;
  if (l) {
    rows.push(['Aufnahme', `${hms(l.aufnahme_s)} · Modelle geladen in ${secs(l.laden_s)} · Abschluss ${secs(l.abschluss_s)}`]);
    // Tempo = nur Dekodieren; "inkl. Vorschau" zeigt, was die Vorschau obendrauf kostet.
    let rechnen = `${secs(l.rechenzeit_s)}${tempo(l.tempo)} für ${l.abschnitte} Abschnitte`;
    const klammer = [];
    if (l.zusammengelegt) klammer.push(`${l.zusammengelegt} zusammengelegt`);
    if (l.eco_abschnitte) klammer.push(`${l.eco_abschnitte} sparsam dekodiert`);
    if (klammer.length) rechnen += ` (${klammer.join(', ')})`;
    if (l.sprecher_s) rechnen += ` · davon Sprecher ${secs(l.sprecher_s)}`;
    if (l.vorschau_n) rechnen += ` · ${l.vorschau_n} Vorschauen ${secs(l.vorschau_s)}${tempo(l.tempo_inkl_vorschau).replace('× Echtzeit', '× inkl. Vorschau')}`;
    rows.push(['Rechenzeit', rechnen]);
    if (l.abschnitte) {
      let lag = `Ø ${secs(l.verzoegerung_mittel_s)} · Median ${secs(l.verzoegerung_median_s)} · max ${secs(l.verzoegerung_max_s)}`;
      lag += ` · Rückstand max ${secs(l.rueckstand_max_s)}`;
      if (l.aufholmodus_s) {
        lag += ` · Aufholmodus ${secs(l.aufholmodus_s)}`;
        if (l.aufholmodus_anteil) lag += ` (${Math.round(l.aufholmodus_anteil * 100)} %)`;
      }
      rows.push(['Verzögerung', lag]);
    }
  }
  const n = f.nachschaerfen;
  if (n) {
    const stufen = (n.stufen || []).map((st) => `${st.name} ${secs(st.dauer_s)}`).join(' · ');
    rows.push(['Nachschärfen', `${hms(n.gesamt_s)}${tempo(n.tempo)}${stufen ? ' · ' + stufen : ''}`]);
  }
  box.innerHTML = `<div class="result fazit"><b>Fazit</b><dl>${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl></div>`;
  box.hidden = false;
}

function openLightbox(index) {
  if (!liveShots.length) return;
  lightboxIndex = (index + liveShots.length) % liveShots.length;
  const shot = liveShots[lightboxIndex];
  $('lightboxImg').src = shotUrl(shot);
  $('lightboxCap').textContent = `Bild #${String(shot.id).padStart(4, '0')} – ${tc(shot.t)} (${lightboxIndex + 1} von ${liveShots.length})`;
  $('lightbox').classList.add('open');
}

$('liveStart').onclick = startLive;
$('liveStop').onclick = () => api('/api/live/stop', { method: 'POST' }).catch(() => {});
$('liveReset').onclick = resetLive;
// Erst nach init(): vorher ist 'defaults' noch null (der CUDA-Test kann auf CPU-Rechnern dauern).
$('liveRefresh').onclick = () => ready.then(loadLiveDefaults)
  .then(() => { $('liveErr').textContent = ''; })
  .catch((err) => { $('liveErr').textContent = err.message; });
$('liveMonitors').onclick = (e) => {
  const tile = e.target.closest('.monitor');
  if (!tile) return;
  if (tile.dataset.winpick) { openWinPick(tile); return; }
  liveSource = { kind: tile.dataset.kind, id: Number(tile.dataset.id) };
  renderWindowTile();
};
// Kacheln sind fokussierbar: Enter/Leertaste wirken wie ein Klick.
const clickOnKey = (e) => {
  if (e.key !== 'Enter' && e.key !== ' ') return;
  const tile = e.target.closest('.monitor');
  if (tile) { e.preventDefault(); tile.click(); }
};
$('liveMonitors').onkeydown = clickOnKey;
for (const id of ['liveThumbs', 'liveText']) {
  $(id).onclick = (e) => {
    const el = e.target.closest('[data-shot]');
    if (el) openLightbox(Number(el.dataset.shot));
  };
}
$('lightbox').onclick = (e) => { if (e.target === $('lightbox')) $('lightbox').classList.remove('open'); };
$('lightboxPrev').onclick = () => openLightbox(lightboxIndex - 1);
$('lightboxNext').onclick = () => openLightbox(lightboxIndex + 1);
// --- Fensterwahl-Dialog -----------------------------------------------------
// Die Fensterliste wird erst beim Oeffnen gezeichnet (frische Vorschaubilder, und ein
// Aktualisieren der Karte zieht nicht fuer jedes offene Fenster einen Screenshot).

let winOpener = null;  // Kachel, die den Dialog geoeffnet hat - bekommt den Fokus zurueck
let winGen = 0;        // Generationszaehler gegen verspaetete Antworten von "Aktualisieren"

const winTile = (w, stamp) =>
  `<div class="monitor ${isActive('window', w.hwnd) ? 'active' : ''}" data-kind="window" data-id="${w.hwnd}" data-search="${esc(`${w.process} ${w.title}`.toLowerCase())}"`
  + ` tabindex="0" role="button"><img src="/api/live/window/${w.hwnd}?t=${stamp}" alt="" loading="lazy" data-fallback />`
  + `<span class="title" title="${esc(w.title)}">${esc(w.title)}</span></div>`;

function renderWinList() {
  const stamp = Date.now();
  // Nach Anwendung gebuendelt; Reihenfolge = Z-Order, also zuletzt benutzte zuerst.
  const groups = new Map();
  for (const w of liveDefaults.windows) (groups.get(w.process) || groups.set(w.process, []).get(w.process)).push(w);
  $('winList').innerHTML = groups.size
    ? [...groups].map(([process, ws]) =>
      `<div class="source-group"><div class="source-title">${esc(process)}<span class="count">${ws.length}</span></div>`
      + `<div class="monitors">${ws.map((w) => winTile(w, stamp)).join('')}</div></div>`).join('')
      + `<div class="empty" id="winNoMatch" hidden>${icon('monitor')}Kein Fenster passt zum Filter.</div>`
    : empty('monitor', 'Keine Anwendungsfenster gefunden.');
  fallbackOnError($('winList'), 'kein Bild');
  applyWinFilter();
}

function applyWinFilter() {
  const q = $('winFilter').value.trim().toLowerCase();
  const tiles = [...$('winList').querySelectorAll('.monitor')];
  let shown = 0;
  for (const tile of tiles) {
    tile.hidden = !!q && !tile.dataset.search.includes(q);
    if (!tile.hidden) shown++;
  }
  for (const group of $('winList').querySelectorAll('.source-group')) {
    group.hidden = ![...group.querySelectorAll('.monitor')].some((t) => !t.hidden);
  }
  const noMatch = $('winNoMatch');
  if (noMatch) noMatch.hidden = shown > 0;
  $('winCount').textContent = tiles.length
    ? (q ? `${shown} von ${tiles.length} Fenstern` : `${tiles.length} Fenster`) : '';
}

function openWinPick(opener) {
  winOpener = opener || null;
  $('winFilter').value = '';
  renderWinList();
  $('winPick').classList.add('open');
  $('winFilter').focus();
}

function closeWinPick() {
  $('winPick').classList.remove('open');
  $('winList').innerHTML = '';  // keine weiteren Bildanfragen, keine veralteten Vorschauen
  winGen++;
  const back = (winOpener && winOpener.isConnected) ? winOpener : $('liveMonitors').querySelector('[data-winpick]');
  winOpener = null;
  if (back) back.focus();
}

function chooseWindow(hwnd) {
  liveSource = { kind: 'window', id: hwnd };
  closeWinPick();
  renderWindowTile();  // ersetzt die Kachel, die eben noch den Fokus hatte
  const tile = $('liveMonitors').querySelector('[data-winpick]');
  if (tile) tile.focus();
}

/** Nur die Fensterliste neu holen. NICHT loadLiveDefaults(): das setzt Quelle und
 *  alle Auswahlfelder auf den gespeicherten Stand zurueck. */
async function refreshWindows() {
  const gen = ++winGen;
  $('winRefresh').disabled = true;
  try {
    const d = await api('/api/live/windows');
    if (gen !== winGen || !$('winPick').classList.contains('open')) return;
    liveDefaults.windows = d.windows || [];
    renderWinList();
    if (liveSource.kind === 'window' && !liveDefaults.windows.some((w) => w.hwnd === liveSource.id)) renderWindowTile();
  } catch (err) {
    $('winCount').textContent = err.message;
  } finally {
    $('winRefresh').disabled = false;
  }
}

$('winList').onclick = (e) => {
  const tile = e.target.closest('.monitor[data-kind="window"]');
  if (tile) chooseWindow(Number(tile.dataset.id));
};
$('winList').onkeydown = clickOnKey;
$('winFilter').oninput = applyWinFilter;  // auch das native "x" des Suchfelds feuert nur input
$('winFilter').onkeydown = (e) => {
  if (e.key !== 'Enter') return;
  const visible = [...$('winList').querySelectorAll('.monitor')].filter((t) => !t.hidden);
  if (visible.length === 1) { e.preventDefault(); visible[0].click(); }
};
$('winRefresh').onclick = refreshWindows;
$('winCancel').onclick = closeWinPick;
$('winPick').onclick = (e) => { if (e.target === $('winPick')) closeWinPick(); };

// --- Bestaetigungsdialog ----------------------------------------------------

let confirmResolve = null;

/** Modale Rueckfrage; loest mit true (bestaetigt) oder false (abgebrochen) auf. */
function askConfirm({ title, text, ok }) {
  $('confirmTitle').lastElementChild.textContent = title;
  $('confirmText').textContent = text;
  $('confirmOk').textContent = ok;
  $('confirm').classList.add('open');
  $('confirmCancel').focus();  // Enter allein loest also nichts Unwiderrufliches aus
  return new Promise((resolve) => { confirmResolve = resolve; });
}

function closeConfirm(answer) {
  $('confirm').classList.remove('open');
  const resolve = confirmResolve;
  confirmResolve = null;
  if (resolve) resolve(answer);
}

$('confirmOk').onclick = () => closeConfirm(true);
$('confirmCancel').onclick = () => closeConfirm(false);
$('confirm').onclick = (e) => { if (e.target === $('confirm')) closeConfirm(false); };

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && $('confirm').classList.contains('open')) { closeConfirm(false); return; }
  if (e.key === 'Escape' && $('winPick').classList.contains('open')) { closeWinPick(); return; }
  if (e.key === 'Escape' && $('overlay').classList.contains('open')) { $('overlay').classList.remove('open'); return; }
  if (!$('lightbox').classList.contains('open')) return;
  if (e.key === 'Escape') $('lightbox').classList.remove('open');
  if (e.key === 'ArrowLeft') openLightbox(lightboxIndex - 1);
  if (e.key === 'ArrowRight') openLightbox(lightboxIndex + 1);
});

const TAB_META = {
  Trans: 'Stapelverarbeitung: Ordner wählen, Dateien ankreuzen, transkribieren',
  Live: 'Monitor, System-Audio und Mikrofon mitschneiden – Transkript und Screenshots entstehen live',
  Ana: 'Claude-Agent: Transkription + Standbilder auswerten, Dokumente im Ausgabeordner ablegen',
};

function showTab(name) {
  for (const btn of document.querySelectorAll('.tabs button')) {
    btn.classList.toggle('active', btn.dataset.tab === name);
    btn.setAttribute('aria-selected', String(btn.dataset.tab === name));
  }
  for (const tab of Object.keys(TAB_META)) $('tab' + tab).hidden = tab !== name;
  $('tabMeta').textContent = TAB_META[name];
  if (name === 'Ana') loadSources();
  if (name === 'Live') updateLiveTarget();
}

for (const btn of document.querySelectorAll('.tabs button')) {
  btn.onclick = () => { history.replaceState(null, '', '#' + btn.dataset.tab.toLowerCase()); showTab(btn.dataset.tab); };
}
// Reiter per Adresse aufrufbar (#trans, #live, #ana) - auch nach einem Neuladen bleibt er offen.
{
  const wanted = Object.keys(TAB_META).find((t) => '#' + t.toLowerCase() === location.hash.toLowerCase());
  if (wanted && wanted !== 'Trans') showTab(wanted);
}
$('anaSources').onchange = (e) => {
  if (e.target.name === 'anaSrc') {
    anaSource = e.target.value;
    // Den Ordnernamen als Vorschlag fuer den Prozessnamen - nur solange noch leer.
    if (!$('anaName').value.trim()) $('anaName').value = e.target.closest('.source').querySelector('.name').textContent;
    updateTarget();
  }
};
$('anaRefresh').onclick = loadSources;
$('pickAna').onclick = () => openDialog('ana');
$('anaName').oninput = updateTarget;
$('anaOut').onchange = () => { updateTarget(); rememberAnalyse(); };
$('anaModel').onchange = rememberAnalyse;
$('anaBash').onchange = rememberAnalyse;
$('anaSkills').onchange = rememberAnalyse;
$('anaStart').onclick = startAnalyse;
$('anaCancel').onclick = () => api('/api/agent/cancel', { method: 'POST' }).catch(() => {});

const ready = init();
ready.then(initAnalyse).then(initLive).catch((err) => { $('liveErr').textContent = err.message; });
