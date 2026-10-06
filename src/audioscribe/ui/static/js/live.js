// Live-Sitzung: Bildquelle, Audio, Optionen, Transkript, Standbilder - im Projekt mit Souffleur,
// Wiederaufnahme nach einem Absturz und dem Schritt danach (ins Wiki, zur KI). Die Demo nutzt
// dieselbe Ansicht ohne Steuerspalte.

import { $, S, api, post, esc, icon, empty, hms, fill, markUnavailable, tc, secs, sep, trimSep, poller, modus, projekt, toast, basename } from './kern.js';
import { go, ladeDefaults } from './kontext.js';
import { askConfirm, pickFolder } from './dialoge.js';
import { openWikiDialog } from './wiki.js';
import { addHint, markSegment, hintBySeg, renderSouffleur, resetSouffleurView, gotoHint, setSouffleurHidden, renderHandover, zeigeWikiStatus, hinweisZahlen } from './souffleur.js';
import { ladeVorgeschichte, demoZustand, vorspann } from './demo.js';

// --- Live Transcription -----------------------------------------------------

let liveDefaults = null;
let liveOffset = 0;        // gelesene Protokollzeilen
let liveEvOffset = 0;      // gelesene Ereignisse (Segmente, Standbilder)
let liveSource = { kind: 'monitor', id: 1 };  // kind: monitor | window (id = HWND) | none | transcript (Testmodus)
let liveShots = [];        // {id, t, file}
let liveSession = null;
let liveRunning = false;
let lightboxIndex = 0;
let liveDir = null;         // Sitzungsordner der laufenden bzw. letzten Sitzung
let liveAblage = null;      // Wiki-Ablage dieser Sitzung (automatisch oder per Dialog)

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


async function loadLiveDefaults() {
  const d = liveDefaults = await api('/api/live/defaults');
  fillDevices($('liveMic'), d.mics, d.mic);
  fillDevices($('liveLoop'), d.loopbacks, d.loopback);
  fill($('liveModel'), d.models, d.model);
  fill($('liveRefineModel'), d.refine_models, d.refine_model);
  fill($('liveLang'), S.defaults.languages, d.language);
  fill($('liveDevice'), S.defaults.devices, d.device);
  markUnavailable($('liveDevice'));
  fill($('liveSens'), S.defaults.sensitivities, d.sensitivity);
  fill($('liveFmt'), S.defaults.frame_formats, d.format);
  $('livePartials').checked = d.partials !== false;
  $('liveSpeakers').checked = d.speakers !== false;
  $('liveRefine').checked = d.refine !== false;
  $('liveProblems').textContent = d.problems.join(' · ');
  if (d.loopback_label) $('liveLoopLabel').textContent = d.loopback_label;
  $('livePermHint').textContent = d.permission_hint || '';
  $('livePermHint').hidden = !d.permission_hint;
  const mlx = S.defaults.backend === 'mlx';
  $('liveBackendHint').textContent = mlx
    ? 'Apple Silicon: Live-Transkription über MLX (Metal-GPU), Sprecher und Nachschärfen über PyTorch/MPS.'
    : '';
  $('liveBackendHint').hidden = !mlx;
  d.windows = d.windows || [];
  // Testmodus (FR-64): zuletzt abgespieltes Transkript und Tempo
  $('liveTestFile').value = d.replay_transcript || '';
  const speeds = (d.replay_speeds && d.replay_speeds.length ? d.replay_speeds : [1, 2, 5, 10, 20]).map(Number);
  const speed = speeds.includes(Number(d.replay_speed)) ? Number(d.replay_speed) : speeds[0];
  $('liveTestSpeed').innerHTML = speeds.map((v) =>
    `<label><input type="radio" name="liveSpeed" value="${v}" ${v === speed ? 'checked' : ''} />${v}×</label>`).join('');
  liveSource = pickLiveSource(d);
  renderSources();
}

const replaySpeed = () => Number(($('liveTestSpeed').querySelector('input:checked') || {}).value || 1);

/** Testdatei und Tempo serverseitig merken (wie die uebrigen Live-Einstellungen). */
const rememberReplay = () => post('/api/state', {
  replay_transcript: $('liveTestFile').value.trim(), replay_speed: String(replaySpeed()),
}).catch(() => {});

const windowLabel = (w) => `${w.process} – ${w.title}`;

/** Gemerkte Quelle wiederfinden: Fenster ueber "Prozess – Titel" (ersatzweise nur den
 *  Prozess - Titel wechseln mit dem Inhalt), Monitore ueber den Index. */
function pickLiveSource(d) {
  if (d.source === 'transcript') return { kind: 'transcript', id: 0 };
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
  if (!chosen && !liveDefaults.windows.length && liveSource.kind !== 'window') return '';  // z. B. ausserhalb von Windows/macOS
  const attrs = 'data-winpick="window" tabindex="0" role="button" aria-haspopup="dialog" title="Anwendungsfenster wählen"';
  if (!chosen) {
    return `<div class="monitor pick" ${attrs}><div class="none">${icon('image')}Fenster wählen …</div>Anwendungsfenster</div>`;
  }
  return `<div class="monitor pick active" ${attrs}><img src="/api/live/window/${chosen.hwnd}?t=${stamp}" alt="" data-fallback />`
    + `<span class="title" title="${esc(chosen.title)}">${esc(chosen.title)}</span>`
    + `<span class="sub">${esc(chosen.process)} · ändern</span></div>`;
}

/** Kachel "Testmodus": spielt ein gespeichertes Transkript ab statt aufzunehmen (FR-64). */
const testTileHtml = () =>
  `<div class="monitor test ${isActive('transcript', 0) ? 'active' : ''}" id="liveTestTile" data-kind="transcript" data-id="0"`
  + ` tabindex="0" role="button" aria-pressed="${isActive('transcript', 0)}" title="Gespeichertes Transkript abspielen – zum Prüfen des Souffleurs">`
  + `<div class="none">${icon('fast-forward')}Transkript abspielen</div>Testmodus</div>`;

function renderSources() {
  const stamp = Date.now();  // Vorschaubild nie aus dem Browser-Cache
  const monitors = liveDefaults.monitors.map((m) =>
    sourceTile('monitor', m.index, `<img src="/api/live/monitor/${m.index}?t=${stamp}" alt="" />Monitor ${m.index} · ${m.width}×${m.height}`))
    .join('') + sourceTile('none', 0, '<div class="none">ohne Bildschirm</div>nur Ton');
  $('liveMonitors').innerHTML = `<div class="monitors">${monitors}${windowTileHtml(stamp)}${testTileHtml()}</div>`;
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
  updateTestMode();
}

/** Testmodus-Unteroptionen und Startknopf folgen der gewaehlten Kachel. */
function updateTestMode() {
  const test = liveSource.kind === 'transcript';
  $('liveTestOpts').hidden = !test;
  const tile = $('liveTestTile');
  if (tile) tile.setAttribute('aria-pressed', String(test));
  $('liveStartLabel').textContent = test ? 'Abspielen starten' : 'Aufnahme starten';
  $('liveStartIcon').setAttribute('href', test ? '#i-play' : '#i-record');
}

function updateLiveTarget() {
  const ziel = `${trimSep(S.folders.output_dir)}${sep()}live-JJJJ-MM-TT_hh-mm-ss`;
  const link = projekt() && !projekt().demo ? ' <a class="goto" href="#/projekt/einstellungen">ändern</a>' : '';
  $('liveTarget').innerHTML = `Gespeichert wird unter: <code>${esc(ziel)}</code>${link}`;
}

function resetLiveView() {
  liveOffset = 0; liveEvOffset = 0; liveShots = []; liveSession = null; lightboxIndex = 0;
  liveDir = null; liveAblage = null;
  $('liveNext').hidden = true; $('liveNext').innerHTML = ''; delete $('liveNext').dataset.key;
  $('liveText').innerHTML = empty('mic', 'Noch keine Sitzung.');
  $('liveThumbs').innerHTML = empty('image', 'Bildwechsel erscheinen hier.');
  $('liveLog').textContent = '';
  $('liveResult').innerHTML = '';
  $('liveFazit').innerHTML = ''; $('liveFazit').hidden = true;
  $('liveShotCount').textContent = '';
  $('liveTestBadge').hidden = true;
  $('lightbox').classList.remove('open');
  resetSouffleurView();
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

async function startLive(resume) {
  $('liveErr').textContent = '';
  $('liveResume').innerHTML = '';
  // Testmodus: Transkript abspielen - der Server ignoriert Geraete und Bildquelle und schaltet das Nachschaerfen ab.
  const test = liveSource.kind === 'transcript';
  const replay = test ? $('liveTestFile').value.trim() : '';
  if (test && !replay) {
    $('liveErr').textContent = 'Testmodus: bitte einen Sitzungsordner oder eine Transkriptdatei (transkript.md, transcript.json) angeben.';
    return;
  }
  if (test && resume) {
    $('liveErr').textContent = 'Zum Fortsetzen bitte links eine Bildquelle bzw. Audio wählen – der Testmodus nimmt nichts auf.';
    loadUnterbrochen();
    return;
  }
  try {
    await post('/api/live/start', {
      output_dir: S.folders.output_dir,
      titel: $('liveTitle').value.trim(),
      resume: resume || '',
      replay_transcript: replay,
      replay_speed: replaySpeed(),
      monitor: liveSource.kind === 'monitor' ? liveSource.id : 0,
      window: liveSource.kind === 'window' ? liveSource.id : 0,
      window_label: liveSource.kind === 'window'
        ? windowLabel(liveDefaults.windows.find((w) => w.hwnd === liveSource.id) || { process: '', title: '' }) : '',
      mic: test ? 'none' : $('liveMic').value,
      loopback: test ? 'none' : $('liveLoop').value,
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
  if (ev.type === 'hinweis') { addHint(ev); return; }
  const el = document.createElement('p');
  if (ev.type === 'segment') {
    el.className = 'seg ' + (ev.track === 'mic' ? 'mic' : 'system');
    el.dataset.id = ev.id;  // Anker fuer die Souffleur-Markierung (hinweis.segment_id)
    el.innerHTML = `<span class="ts">[${tc(ev.start)}]</span><span class="who">${esc(ev.speaker)}:</span> `
      + `${esc(ev.text)}<span class="lag" title="Verzögerung bis zur Anzeige">${secs(ev.delay)}</span>`;
    insertByTime(el, ev.start);
    // Der Hinweis kann vor seiner Zeile angekommen sein (Sortierung nach Zeit): Markierung nachziehen.
    const hint = hintBySeg.get(ev.id);
    if (hint) markSegment(hint);
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
  abschluss: 'Souffleur schließt ab …', fertig: 'gespeichert', nachschaerfen: 'Nachschärfen …', beendet: 'beendet',
  fehler: 'Fehler',
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

  const warLaufend = liveRunning;
  const running = liveRunning = !!s.running;
  if (running && $('liveResume').firstChild) $('liveResume').innerHTML = '';
  $('liveStart').hidden = running;
  $('liveStop').hidden = !running;
  $('liveStopLabel').textContent = s.phase === 'nachschaerfen' ? 'Nachschärfen abbrechen'
    : s.stopping ? 'Sofort abbrechen' : 'Stoppen';
  // Erst sichtbar, wenn es etwas zurueckzusetzen gibt; waehrend der Aufnahme heisst es "Neu beginnen".
  $('liveReset').hidden = !running && !s.dir && !s.phase;
  $('liveResetLabel').textContent = running ? 'Verwerfen und neu beginnen' : 'Zurücksetzen';
  $('livePhase').textContent = (s.replay && s.phase === 'laeuft'
    ? (s.pausiert ? 'angehalten' : 'Abspielen läuft') : PHASES[s.phase]) || 'bereit';
  $('livePhase').className = 'badge ' + (s.pausiert ? 'warn'
    : ({ laeuft: 'laeuft', abschluss: 'laeuft', fehler: 'fehler', beendet: 'fertig' }[s.phase] || ''));
  $('liveTestBadge').hidden = !s.replay;
  // Das Tempo gilt ab dem Start; ein Wechsel mitten im Abspielen haette keine Wirkung.
  $('liveTestSpeed').querySelectorAll('input').forEach((i) => { i.disabled = running; });
  if (s.replay) $('liveTestBadge').textContent = `Testmodus ${s.replay_speed || replaySpeed()}×`;

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
  renderSouffleur(s);
  // Im Fehlerfall zuerst der Grund; der Sitzungsordner nur, wenn er angelegt wurde.
  const demo = modus() === 'demo';
  const fehler = s.phase === 'fehler' && s.error ? `${esc(s.error)}` : '';
  const ordner = s.dir && !demo ? `Sitzungsordner: <code>${esc(s.dir)}</code><br>
       Die Live-Fassung liegt als <code>transkript.live.md</code> daneben.` : '';
  $('liveResult').innerHTML = !running && (fehler || ordner)
    ? `<div class="result ${s.phase === 'fehler' ? 'fehler' : ''}">${[fehler, ordner].filter(Boolean).join('<br>')}</div>` : '';
  liveDir = s.dir || null;
  // Automatisch gespeichert (Nachlauf) oder frueher per Dialog - der Server kennt den Vermerk.
  if (s.nachlauf && s.nachlauf.wiki_ablage) liveAblage = s.nachlauf.wiki_ablage;
  else if (s.wiki_ablage && !liveAblage) liveAblage = s.wiki_ablage;
  renderHandover(liveAblage);
  renderNext(s);
  renderDemo(s);
  // Eine eben beendete Sitzung kann eine unterbrochene gewesen sein - Banner nachziehen.
  if (warLaufend && !running) loadUnterbrochen();
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

// Screenshots-Karte: zu, solange der Souffleur den Platz braucht; der Zustand bleibt im Browser.
try { $('liveShots').open = localStorage.getItem('liveShotsOpen') === '1'; } catch (e) { /* privat / gesperrt */ }
$('liveShots').addEventListener('toggle', () => {
  try { localStorage.setItem('liveShotsOpen', $('liveShots').open ? '1' : '0'); } catch (e) { /* egal */ }
});
$('liveTestSpeed').onchange = rememberReplay;
$('liveTestFile').onchange = rememberReplay;

$('liveStart').onclick = () => startLive();
$('liveStop').onclick = () => api('/api/live/stop', { method: 'POST' }).catch(() => {});
$('liveReset').onclick = resetLive;
// Erst mit den Defaults: der CUDA-Test kann auf CPU-Rechnern dauern.
$('liveRefresh').onclick = () => ladeDefaults().then(loadLiveDefaults)
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
    const chip = e.target.closest('[data-goto-hint]');
    if (chip) { gotoHint(chip.dataset.gotoHint); return; }
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

document.addEventListener('keydown', (e) => {
  if (document.querySelector('dialog[open]')) return;  // native Dialoge behandeln ihre Tasten selbst
  // Alt+S: Souffleur aus- und einblenden (global, auch bei Fokus im Transkript).
  if (e.altKey && !e.ctrlKey && !e.metaKey && e.key.toLowerCase() === 's' && !$('tabLive').hidden) {
    e.preventDefault();
    setSouffleurHidden(!$('liveAside').classList.contains('collapsed'));
    return;
  }
  if (e.key === 'Escape' && $('winPick').classList.contains('open')) { closeWinPick(); return; }
  if (e.key === 'Escape' && !$('lightbox').classList.contains('open') && !$('liveAside').classList.contains('collapsed')
      && $('liveAside').contains(document.activeElement)) { setSouffleurHidden(true); return; }
  if (!$('lightbox').classList.contains('open')) return;
  if (e.key === 'Escape') $('lightbox').classList.remove('open');
  if (e.key === 'ArrowLeft') openLightbox(lightboxIndex - 1);
  if (e.key === 'ArrowRight') openLightbox(lightboxIndex + 1);
});

// --- Ansicht betreten und verlassen ------------------------------------------------------

const pollStatus = poller(pollLive, 500);
let liveBereit = false;    // Geraete und Auswahlfelder fuer diesen Kontext geladen
let liveSichtbar = false;  // die Ansicht ist betreten und nicht wieder verlassen

export async function enterLive() {
  liveSichtbar = true;
  // Die Demo zeigt zu jedem Beleg das Meeting, aus dem er stammt - gleich holen, vor dem ersten Hinweis da.
  const vorgeschichte = modus() === 'demo' ? ladeVorgeschichte() : null;
  await ladeDefaults();
  if (modus() !== 'demo' && !liveBereit) {
    liveBereit = true;
    try {
      await loadLiveDefaults();
      $('liveErr').textContent = '';
    } catch (err) {
      liveBereit = false;
      $('liveErr').textContent = err.message;
    }
  }
  await vorgeschichte;
  // Waehrend des Ladens verlassen (die Geraete-Probe dauert): nicht unsichtbar weiter abfragen.
  if (!liveSichtbar) return;
  updateLiveTarget();
  renderHandover(liveAblage);
  if (modus() === 'projekt') loadUnterbrochen();
  pollStatus.start();
}

export function leaveLive() { liveSichtbar = false; pollStatus.stop(); }

/** Kontextwechsel: die Ansicht beginnt leer, Geraete und Vorgaben werden neu geholt. */
export function leereLive() {
  liveBereit = false;
  liveRunning = false;
  resetLiveView();
  $('liveTitle').value = '';
  $('liveResume').innerHTML = '';
  $('liveErr').textContent = '';
  $('demoErr').textContent = '';
}

/** Einstellungen geaendert: nur die Sprache nachziehen - Geraete- und Quellenwahl bleiben stehen. */
export function aktualisiereLiveSprache(d) {
  if (liveBereit && !liveRunning && d && d.languages) fill($('liveLang'), d.languages, d.language);
}

// --- Nach der Sitzung: ins Wiki, zur KI (PRD §21) ---------------------------------------------

function renderNext(s) {
  const box = $('liveNext');
  const p = projekt();
  const zeigen = modus() === 'projekt' && !!p && !s.running && !!s.dir && s.phase === 'beendet';
  const fehler = (s.nachlauf && (s.nachlauf.wiki_fehler || s.nachlauf.fehler)) || '';
  const key = JSON.stringify([zeigen, s.dir, liveAblage, p && p.wiki_speichern, fehler, liveShots.length]);
  if (box.dataset.key === key) return;
  box.dataset.key = key;
  box.hidden = !zeigen;
  if (!zeigen) { box.innerHTML = ''; return; }
  const bilder = liveShots.length;
  let wiki = '';
  if (liveAblage) {
    wiki = `<div class="next-item done"><b>${icon('check')}Im Wiki gespeichert</b>
      <span><code>${esc(liveAblage.ordner)}</code>${liveAblage.bilder ? ` · ${liveAblage.bilder} Bilder im Assets-Ordner` : ''}${liveAblage.markierungen ? ` · ${liveAblage.markierungen} Markierungen` : ''}</span>
      <button class="ghost sm" type="button" data-folder="${esc(liveAblage.ordner)}">${icon('external')}Ordner öffnen</button></div>`;
  } else if (p.wiki_speichern !== 'nie' || fehler) {
    wiki = `<div class="next-item"><b>${icon('book-plus')}Ins Wiki speichern</b>
      <span>${fehler ? `<span class="err">${esc(fehler)}</span>` : ''}Transkript${bilder ? ` und ${bilder} Bilder` : ''}
        als neue Quelle unter <code>raw/</code> ablegen – die Markierungen des Souffleurs nur auf Wunsch.</span>
      <button type="button" id="liveWikiSave">${icon('book-plus')}Ins Wiki speichern</button></div>`;
  }
  const ki = `<div class="next-item"><b>${icon('sparkles')}Mit KI nachbereiten</b>
      <span>Die KI wertet Transkript und Bilder aus. Das Ergebnis kann danach ebenfalls ins Wiki.</span>
      <button class="secondary" type="button" id="liveToKi">Zur Nachbereitung${icon('arrow-right')}</button></div>`;
  box.innerHTML = `<h3>Wie geht es weiter?</h3>
    <p>Die Sitzung ist im Sitzungsordner gesichert. Beides ist möglich – in beliebiger Reihenfolge.</p>
    <div class="next-grid">${wiki}${ki}</div>`;
}

$('liveNext').addEventListener('click', async (e) => {
  const folder = e.target.closest('[data-folder]');
  if (folder) { post('/api/oeffnen', { pfad: folder.dataset.folder }).catch((err) => toast(err.message, 'fehler')); return; }
  if (e.target.closest('#liveWikiSave') && liveDir) {
    const ablage = await openWikiDialog({
      path: liveDir, name: basename(liveDir), titel: $('liveTitle').value.trim(), frames: liveShots.length,
    });
    if (ablage) { liveAblage = ablage; delete $('liveNext').dataset.key; pollLive(); }
    return;
  }
  if (e.target.closest('#liveToKi') && liveDir) {
    S.vorwahl = liveDir;
    go('#/projekt/nachbereitung');
  }
});

// --- Wiederaufnahme nach einem Absturz (PRD §21) ----------------------------------------------

async function loadUnterbrochen() {
  const box = $('liveResume');
  const p = projekt();
  if (modus() !== 'projekt' || !p || liveRunning) { box.innerHTML = ''; return; }
  let liste = [];
  try {
    liste = (await api('/api/live/unterbrochen')).sitzungen.filter((s) => s.projekt === p.wurzel);
  } catch (e) { return; }
  box.innerHTML = liste.map((s) => `
    <div class="banner" role="status">
      ${icon('triangle')}
      <div class="text"><b>Unterbrochene Sitzung${s.titel ? ` „${esc(s.titel)}“` : ''}</b>
        <small>${esc(s.gestartet ? s.gestartet.replace('T', ' ').slice(0, 16) : s.name)} · ${hms(s.dauer_s || 0)} aufgezeichnet ·
          ${s.segmente || 0} Abschnitte gesichert. Fortsetzen nimmt mit den links gewählten Geräten weiter auf.</small></div>
      <div class="actions">
        <button type="button" data-resume="${esc(s.dir)}" data-titel="${esc(s.titel || '')}">${icon('record')}Fortsetzen</button>
        <button class="secondary" type="button" data-finalize="${esc(s.dir)}">${icon('check')}Abschließen</button>
        <button class="ghost" type="button" data-discard="${esc(s.dir)}">Verwerfen</button>
      </div>
    </div>`).join('');
}

$('liveResume').addEventListener('click', async (e) => {
  const resume = e.target.closest('[data-resume]');
  const finalize = e.target.closest('[data-finalize]');
  const discard = e.target.closest('[data-discard]');
  $('liveErr').textContent = '';
  try {
    if (resume) {
      if (resume.dataset.titel) $('liveTitle').value = resume.dataset.titel;
      $('liveResume').innerHTML = '';
      await startLive(resume.dataset.resume);
    } else if (finalize) {
      await post('/api/live/abschliessen', { sitzung: finalize.dataset.finalize });
      $('liveResume').innerHTML = '';
      resetLiveView();
      pollLive();
    } else if (discard) {
      const ok = await askConfirm({
        title: 'Unterbrochene Sitzung verwerfen?',
        text: 'Die Sitzung wird nicht mehr zum Fortsetzen angeboten. Mitschnitt und bisheriges Transkript bleiben im Sitzungsordner liegen.',
        ok: 'Verwerfen',
      });
      if (ok) { await post('/api/live/verwerfen', { sitzung: discard.dataset.discard }); loadUnterbrochen(); }
    }
  } catch (err) {
    $('liveErr').textContent = err.message;
    loadUnterbrochen();
  }
});

// --- Demo: ein Knopf, sonst nichts ----------------------------------------------------------

function renderDemo(s) {
  if (modus() !== 'demo') return;
  $('demoStart').hidden = !!s.running;
  $('demoStop').hidden = !s.running;
  // Pause nur, solange abgespielt wird (nicht beim Laden oder Abschliessen).
  const pausiert = !!s.pausiert;
  $('demoPause').hidden = !(s.running && s.phase === 'laeuft');
  $('demoPause').setAttribute('aria-pressed', String(pausiert));
  $('demoPauseLabel').textContent = pausiert ? 'Weiter' : 'Pause';
  $('demoPauseIcon').setAttribute('href', pausiert ? '#i-play' : '#i-pause');
  $('demoStart').lastChild.textContent = s.phase === 'beendet' || s.phase === 'fehler' ? 'Demo erneut starten' : 'Demo starten';
  demoZustand(s, hinweisZahlen());
}

$('demoStart').onclick = async () => {
  $('demoErr').textContent = '';
  $('demoStart').disabled = true;
  try {
    await post('/api/demo/start');
    resetLiveView();
    vorspann();
    pollLive();
  } catch (err) {
    $('demoErr').textContent = err.message;
  } finally {
    $('demoStart').disabled = false;
  }
};
$('demoStop').onclick = () => api('/api/live/stop', { method: 'POST' }).catch(() => {});
$('demoPause').onclick = async () => {
  $('demoErr').textContent = '';
  try {
    await post('/api/live/pause', { pausiert: $('demoPause').getAttribute('aria-pressed') !== 'true' });
    pollLive();
  } catch (err) {
    $('demoErr').textContent = err.message;
  }
};

// --- Testmodus: Sitzungsordner waehlen --------------------------------------------------------

$('pickLiveTestFile').onclick = async () => {
  let start = $('liveTestFile').value;
  // Im Testfeld darf eine Datei stehen (transkript.md) - der Dialog zeigt dann ihren Ordner.
  if (/\.(md|json)\s*$/i.test(start)) start = start.replace(/[\\/][^\\/]*$/, '');
  const pfad = await pickFolder({ title: 'Sitzungsordner zum Abspielen wählen', start: start.trim() || S.folders.output_dir });
  if (pfad) { $('liveTestFile').value = pfad; rememberReplay(); }
};

// Der Wiki-Zustand des Projekts steht in der Souffleur-Karte, solange keine Sitzung laeuft.
document.addEventListener('audioscribe:wiki', zeigeWikiStatus);
