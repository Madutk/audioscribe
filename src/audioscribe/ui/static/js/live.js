// Live-Sitzung: Bildquelle, Audio, Optionen, Transkript, Standbilder - im Projekt mit Souffleur,
// Wiederaufnahme nach einem Absturz und dem Schritt danach (ins Wiki, zur KI). Die Demo nutzt
// dieselbe Ansicht ohne Steuerspalte.

import { $, S, api, post, esc, icon, empty, hms, fill, markUnavailable, tc, secs, sep, trimSep, poller, modus, projekt, toast, basename, cloudCompliant } from './kern.js';
import { go, ladeDefaults } from './kontext.js';
import { zuordnenDialog } from './eingang.js';
import { askConfirm, pickFolder } from './dialoge.js';
import { openWikiDialog } from './wiki.js';
import { addHint, markSegment, hintBySeg, renderSouffleur, resetSouffleurView, gotoHint, setSouffleurHidden, renderHandover, zeigeWikiStatus, hinweisZahlen } from './souffleur.js';
import { ladeVorgeschichte, demoZustand, vorspann } from './demo.js';
import { pipStatus, umschalten as souffleurPip, einkoppeln as souffleurEinkoppeln, istAusgekoppelt, pipMoeglich } from './souffleur-pip.js';
import { tr, englisch } from './i18n.js';

const zahl = (v) => v.toLocaleString(englisch ? 'en-US' : 'de-DE');

// --- Live Transcription -----------------------------------------------------

let liveDefaults = null;
let liveOffset = 0;        // gelesene Protokollzeilen
let liveEvOffset = 0;      // gelesene Ereignisse (Segmente, Standbilder)
let liveSource = { kind: 'monitor', id: 1 };  // kind: monitor | window (id = HWND) | none | transcript (Testmodus)
let liveShots = [];        // {id, t, file}
let liveSession = null;
let liveRunning = false;
let liveReplay = false;     // Testmodus laeuft (dort gibt es keine Bildquelle)
let liveQuelle = null;      // vom Aufnahmeprozess gemeldete Bildquelle {monitor, window, label, aktiv}
let switchPending = false;  // Wechsel der Bildquelle unterwegs - der Status soll ihn nicht ueberholen
let lightboxIndex = 0;
let liveDir = null;         // Sitzungsordner der laufenden bzw. letzten Sitzung
let liveAblage = null;      // Wiki-Ablage dieser Sitzung (automatisch oder per Dialog)

function fillDevices(sel, devices, chosen) {
  const opts = [['default', tr('Standardgerät')],
    ...devices.map((d) => [String(d.index), d.default ? tr('{name} (Standard)', { name: d.name }) : d.name]), ['none', tr('aus')]];
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
    ? tr('Apple Silicon: Live-Transkription über MLX (Metal-GPU), Sprecher und Nachschärfen über PyTorch/MPS.')
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

// --- Bevorzugte Anwendung (Teams): eigene Kachel direkt hinter den Monitoren ----------------
// Der Server stellt bevorzugte Fenster voran und markiert sie (live/fenster.py: BEVORZUGT);
// hier zaehlt das vorderste davon, also das zuletzt benutzte Teams-Fenster.

const prioFenster = () => liveDefaults.windows.find((w) => w.bevorzugt) || null;
const prioTag = (w) => (/teams/i.test(w.process) ? 'Teams' : w.process);

/** Kachel der bevorzugten Anwendung: waehlt das Fenster direkt (data-kind wie ein Monitor). */
function prioTileHtml(stamp) {
  const w = prioFenster();
  if (!w) return '';
  const inner = `<span class="tag">${esc(prioTag(w))}</span><img src="/api/live/window/${w.hwnd}?t=${stamp}" alt="" data-fallback />`
    + `<span class="title" title="${esc(w.title)}">${esc(w.title)}</span><span class="sub">${esc(w.process)}</span>`;
  return `<div class="monitor prio ${isActive('window', w.hwnd) ? 'active' : ''}" data-prio="1" data-kind="window" data-id="${w.hwnd}"`
    + ` tabindex="0" role="button" title="${esc(w.process)} – ${esc(w.title)}">${inner}</div>`;
}

/** Die eine Kachel "Anwendungsfenster" in der Karte: gewaehltes Fenster mit Vorschau oder Platzhalter.
 *  Sie oeffnet den Auswahldialog und traegt darum KEIN data-kind. ``ausser``: das Fenster der
 *  bevorzugten Kachel - es erscheint dort, nicht hier noch einmal. */
function windowTileHtml(stamp, ausser = null) {
  let chosen = liveSource.kind === 'window' && liveSource.id !== ausser && liveDefaults.windows.find((w) => w.hwnd === liveSource.id);
  // Nach einem Neuladen der Seite kennt die Fensterliste das Fenster der laufenden Aufnahme
  // vielleicht nicht mehr - der Aufnahmeprozess hat seinen Titel gemeldet.
  if (!chosen && liveSource.kind === 'window' && liveQuelle && liveQuelle.window === liveSource.id) {
    chosen = { hwnd: liveSource.id, title: liveQuelle.label.replace(/^(?:Fenster|Window) '(.*)'$/, '$1'), process: tr('laufende Aufnahme') };
  }
  if (!chosen && !liveDefaults.windows.length && liveSource.kind !== 'window') return '';  // z. B. ausserhalb von Windows/macOS
  const attrs = `data-winpick="window" tabindex="0" role="button" aria-haspopup="dialog" title="${tr('Anwendungsfenster wählen')}"`;
  if (!chosen) {
    const text = ausser !== null && liveSource.kind === 'window' && liveSource.id === ausser ? tr('Anderes Fenster wählen …') : tr('Fenster wählen …');
    return `<div class="monitor pick" ${attrs}><div class="none">${icon('image')}${text}</div>${tr('Anwendungsfenster')}</div>`;
  }
  return `<div class="monitor pick active" ${attrs}><img src="/api/live/window/${chosen.hwnd}?t=${stamp}" alt="" data-fallback />`
    + `<span class="title" title="${esc(chosen.title)}">${esc(chosen.title)}</span>`
    + `<span class="sub">${esc(chosen.process)} · ${tr('ändern')}</span></div>`;
}

/** Kachel "Testmodus": spielt ein gespeichertes Transkript ab statt aufzunehmen (FR-64). */
const testTileHtml = () =>
  `<div class="monitor test ${isActive('transcript', 0) ? 'active' : ''}" id="liveTestTile" data-kind="transcript" data-id="0"`
  + ` tabindex="0" role="button" aria-pressed="${isActive('transcript', 0)}" title="${tr('Gespeichertes Transkript abspielen – zum Prüfen des Souffleurs')}">`
  + `<div class="none">${icon('fast-forward')}${tr('Transkript abspielen')}</div>${tr('Testmodus')}</div>`;

function renderSources() {
  const stamp = Date.now();  // Vorschaubild nie aus dem Browser-Cache
  const monitors = liveDefaults.monitors.map((m) =>
    sourceTile('monitor', m.index, `<img src="/api/live/monitor/${m.index}?t=${stamp}" alt="" />Monitor ${m.index} · ${m.width}×${m.height}`))
    .join('') + sourceTile('none', 0, `<div class="none">${tr('ohne Bildschirm')}</div>${tr('nur Ton')}`);
  const prio = prioFenster();
  $('liveMonitors').innerHTML = `<div class="monitors">${monitors}${prioTileHtml(stamp)}${windowTileHtml(stamp, prio ? prio.hwnd : null)}${testTileHtml()}</div>`;
  fallbackOnError($('liveMonitors'), tr('kein Bild'));
  updateSourceTiles();
  updateSourceHint();
}

/** Waehrend einer Aufnahme ist der Testmodus tabu, im Testmodus jede Bildquelle (FR-37). */
function updateSourceTiles() {
  for (const t of $('liveMonitors').querySelectorAll('.monitor')) {
    const test = t.dataset.kind === 'transcript';
    const aus = liveRunning && (liveReplay || test);
    t.classList.toggle('disabled', aus);
    t.setAttribute('aria-disabled', String(aus));
    t.tabIndex = aus ? -1 : 0;
  }
}

/** Nur die Fenster-Kacheln (bevorzugte Anwendung, "Anwendungsfenster") neu zeichnen und die
 *  Markierung setzen - Monitorbilder bleiben stehen. */
function renderWindowTile() {
  const stamp = Date.now();
  const prio = prioFenster();
  const box = $('liveMonitors').querySelector('.monitors');
  const old = box.querySelector('[data-winpick]');
  const html = windowTileHtml(stamp, prio ? prio.hwnd : null);
  if (old) old.outerHTML = html;
  else if (html) box.insertAdjacentHTML('beforeend', html);
  const altePrio = box.querySelector('[data-prio]');
  const prioHtml = prioTileHtml(stamp);
  if (altePrio) { if (prioHtml) altePrio.outerHTML = prioHtml; else altePrio.remove(); }
  else if (prioHtml) {
    const vor = box.querySelector('[data-winpick]') || box.querySelector('#liveTestTile');
    if (vor) vor.insertAdjacentHTML('beforebegin', prioHtml); else box.insertAdjacentHTML('beforeend', prioHtml);
  }
  for (const t of $('liveMonitors').querySelectorAll('.monitor[data-kind]')) {
    t.classList.toggle('active', isActive(t.dataset.kind, Number(t.dataset.id)));
  }
  fallbackOnError($('liveMonitors'), tr('kein Bild'));
  updateSourceTiles();
  updateSourceHint();
}

function updateSourceHint() {
  const quelle = liveSource.kind === 'window'
    ? tr('Nur das gewählte Fenster wird abgetastet – diese Oberfläche darf auf demselben Monitor liegen.')
    : liveSource.kind === 'monitor'
      ? tr('Diese Oberfläche gehört nicht auf den überwachten Monitor – neue Thumbnails würden sonst selbst Bildwechsel auslösen.')
      : '';
  const wechsel = liveRunning && !liveReplay
    ? tr('Ein Wechsel gilt sofort – das erste Bild der neuen Quelle wird gesichert.') : '';
  $('liveSourceHint').textContent = [quelle, wechsel].filter(Boolean).join(' ');
  updateTestMode();
}

/** Quelle uebernehmen - und waehrend einer Aufnahme sofort an den Aufnahmeprozess geben (FR-37).
 *  Schlaegt das fehl, bleibt die bisherige Quelle markiert. */
async function switchSource(next) {
  const vorher = liveSource;
  liveSource = next;
  renderWindowTile();
  if (!liveRunning || liveReplay) return;
  switchPending = true;
  $('liveErr').textContent = '';
  try {
    await post('/api/live/bildquelle', {
      monitor: next.kind === 'monitor' ? next.id : 0,
      window: next.kind === 'window' ? next.id : 0,
      window_label: next.kind === 'window'
        ? windowLabel(liveDefaults.windows.find((w) => w.hwnd === next.id) || { process: '', title: '' }) : '',
    });
  } catch (err) {
    liveSource = vorher;
    renderWindowTile();
    $('liveErr').textContent = err.message;
    toast(err.message, 'fehler');
  } finally {
    switchPending = false;
  }
}

/** Die vom Aufnahmeprozess gemeldete Quelle als Kachel markieren - nach einem Neuladen der
 *  Seite oder einem Wechsel von der Konsole (``bild monitor 2`` auf stdin). */
function syncSourceFromStatus(q) {
  liveQuelle = q || null;
  if (!q || switchPending || liveSource.kind === 'transcript') return;
  const next = q.window ? { kind: 'window', id: q.window }
    : q.monitor ? { kind: 'monitor', id: q.monitor } : { kind: 'none', id: 0 };
  if (isActive(next.kind, next.id)) return;
  liveSource = next;
  renderWindowTile();
}

/** Testmodus-Unteroptionen und Startknopf folgen der gewaehlten Kachel. */
function updateTestMode() {
  const test = liveSource.kind === 'transcript';
  $('liveTestOpts').hidden = !test;
  const tile = $('liveTestTile');
  if (tile) tile.setAttribute('aria-pressed', String(test));
  $('liveStartLabel').textContent = test ? tr('Abspielen starten') : tr('Aufnahme starten');
  $('liveStartIcon').setAttribute('href', test ? '#i-play' : '#i-record');
}

function updateLiveTarget() {
  const ziel = `${trimSep(S.folders.output_dir)}${sep()}live-${tr('JJJJ-MM-TT')}_hh-mm-ss`;
  const link = projekt() && !projekt().demo ? ` <a class="goto" href="#/projekt/einstellungen">${tr('ändern')}</a>`
    : modus() === 'aufnahme' ? ` <a class="goto" href="#/einstellungen">${tr('ändern')}</a>` : '';
  $('liveTarget').innerHTML = tr('Gespeichert wird unter: {pfad}', { pfad: `<code>${esc(ziel)}</code>` }) + link;
}

function resetLiveView() {
  liveOffset = 0; liveEvOffset = 0; liveShots = []; liveSession = null; lightboxIndex = 0;
  liveDir = null; liveAblage = null;
  $('liveNext').hidden = true; $('liveNext').innerHTML = ''; delete $('liveNext').dataset.key;
  $('liveText').innerHTML = empty('mic', tr('Noch keine Sitzung.'));
  $('liveThumbs').innerHTML = empty('image', tr('Bildwechsel erscheinen hier.'));
  $('liveLog').textContent = '';
  $('liveResult').innerHTML = ''; delete $('liveResult').dataset.key;
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
    title: tr('Laufende Sitzung verwerfen?'),
    text: tr('Die Aufnahme wird sofort abgebrochen, ohne Nachschärfen. Anschließend beginnt eine neue Sitzung mit denselben Einstellungen. Die bisherigen Dateien bleiben im Sitzungsordner liegen.'),
    ok: tr('Verwerfen und neu beginnen'),
  } : {
    title: tr('Ansicht zurücksetzen?'),
    text: tr('Transkript, Screenshots und Protokoll verschwinden aus der Oberfläche. Der Sitzungsordner auf der Platte bleibt unverändert.'),
    ok: tr('Zurücksetzen'),
  });
  if (!ok) return;
  $('liveErr').textContent = '';
  $('liveReset').disabled = true;
  try {
    const r = await post('/api/live/reset', {});
    resetLiveView();
    if (!restart) souffleurEinkoppeln();  // beim Neubeginnen bleibt das Mini-Fenster offen
    if (restart) await startLive();
    else await pollLive();
    if (r.discarded) $('liveLog').textContent = tr('Verworfene Sitzung liegt noch unter: {pfad}', { pfad: r.discarded }) + '\n' + $('liveLog').textContent;
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
    $('liveErr').textContent = tr('Testmodus: bitte einen Sitzungsordner oder eine Transkriptdatei (transkript.md, transcript.json) angeben.');
    return;
  }
  if (test && resume) {
    $('liveErr').textContent = tr('Zum Fortsetzen bitte links eine Bildquelle bzw. Audio wählen – der Testmodus nimmt nichts auf.');
    loadUnterbrochen();
    return;
  }
  try {
    await post('/api/live/start', {
      output_dir: S.folders.output_dir,
      titel: $('liveTitle').value.trim(),
      art: $('liveArt').value,
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
      + `${esc(ev.text)}<span class="lag" title="${tr('Verzögerung bis zur Anzeige')}">${secs(ev.delay)}</span>`;
    insertByTime(el, ev.start);
    // Der Hinweis kann vor seiner Zeile angekommen sein (Sortierung nach Zeit): Markierung nachziehen.
    const hint = hintBySeg.get(ev.id);
    if (hint) markSegment(hint);
  } else if (ev.type === 'shot') {
    const index = liveShots.push(ev) - 1;
    const label = tr('Bild #{nr} – {zeit}', { nr: String(ev.id).padStart(4, '0'), zeit: tc(ev.t) });
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

// Deutsche Schluessel - uebersetzt erst bei der Anzeige (tr(PHASES[...]), en/module-b.js).
const PHASES = {
  startet: 'startet …', laden: 'Modell wird geladen …', laeuft: 'Aufnahme läuft', stoppt: 'wird abgeschlossen …',
  abschluss: 'Souffleur schließt ab …', fertig: 'gespeichert', nachschaerfen: 'Nachschärfen …', beendet: 'beendet',
  fehler: 'Fehler',
};

function gauge(boxId, valueId, value, warn, bad) {
  $(valueId).textContent = secs(value);
  $(boxId).className = 'gauge ' + (value === null || value === undefined ? '' : value < warn ? 'ok' : value < bad ? 'warn' : 'err');
}

/** Verknuepfung "Sofort aufnehmen": Stand des automatischen Starts (laeuft | gestartet | fehler). */
function renderSofort(q) {
  const box = $('liveSofort');
  const key = JSON.stringify(q || null);
  if (box.dataset.key === key) return;
  box.dataset.key = key;
  if (!q || !q.status) { box.hidden = true; box.textContent = ''; box.className = 'hint'; return; }
  box.hidden = false;
  box.className = q.status === 'fehler' ? 'err' : 'hint';
  box.textContent = q.status === 'laeuft' ? tr('Automatischer Start über die Verknüpfung – Geräte werden ermittelt …')
    : q.status === 'gestartet' ? tr('Automatisch gestartet (Verknüpfung „Sofort aufnehmen“) – mit den zuletzt benutzten Geräten.')
      : tr('Automatischer Start fehlgeschlagen: {fehler} – Geräte prüfen und „Aufnahme starten“ drücken.', { fehler: q.fehler });
}

async function pollLive() {
  let s;
  try { s = await api(`/api/live/status?offset=${liveOffset}&ev_offset=${liveEvOffset}`); } catch (e) { return; }
  renderSofort(s.sofort);
  if (s.ev_offset < liveEvOffset || s.offset < liveOffset) { resetLiveView(); return; }  // neue Sitzung
  liveSession = s.session || liveSession;
  // Fortgesetzte Sitzung: die beim ersten Start gewaehlte Art steht in sitzung.json.
  if (s.art && !$('liveArt').value) $('liveArt').value = s.art;
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
  liveReplay = !!s.replay;
  if (running && !s.replay) syncSourceFromStatus(s.bildquelle);
  if (warLaufend !== running) { updateSourceTiles(); updateSourceHint(); }
  if (running && $('liveResume').firstChild) $('liveResume').innerHTML = '';
  $('liveStart').hidden = running;
  $('liveStop').hidden = !running;
  $('liveStopLabel').textContent = s.phase === 'nachschaerfen' ? tr('Nachschärfen abbrechen')
    : s.stopping ? tr('Sofort abbrechen') : tr('Stoppen');
  // Erst sichtbar, wenn es etwas zurueckzusetzen gibt; waehrend der Aufnahme heisst es "Neu beginnen".
  $('liveReset').hidden = !running && !s.dir && !s.phase;
  $('liveResetLabel').textContent = running ? tr('Verwerfen und neu beginnen') : tr('Zurücksetzen');
  $('livePhase').textContent = s.replay && s.phase === 'laeuft'
    ? (s.pausiert ? tr('angehalten') : tr('Abspielen läuft')) : PHASES[s.phase] ? tr(PHASES[s.phase]) : tr('bereit');
  $('livePhase').className = 'badge ' + (s.pausiert ? 'warn'
    : ({ laeuft: 'laeuft', abschluss: 'laeuft', fehler: 'fehler', beendet: 'fertig' }[s.phase] || ''));
  $('liveTestBadge').hidden = !s.replay;
  // Das Tempo gilt ab dem Start; ein Wechsel mitten im Abspielen haette keine Wirkung.
  $('liveTestSpeed').querySelectorAll('input').forEach((i) => { i.disabled = running; });
  if (s.replay) $('liveTestBadge').textContent = tr('Testmodus {tempo}×', { tempo: s.replay_speed || replaySpeed() });

  const st = s.stats;
  $('liveElapsed').textContent = st ? hms(st.elapsed) : '–';
  pipStatus(s, $('livePhase').textContent);
  gauge('liveDelayBox', 'liveDelay', st ? st.delay : null, 5, 10);
  gauge('liveBacklogBox', 'liveBacklog', st ? st.backlog : null, 3, 10);
  // Tooltip: gemessenes Tempo (Rechenzeit je Audiosekunde) und was die Sitzung gerade drosselt.
  const hints = [];
  if (st && st.rtf !== null && st.rtf !== undefined) hints.push(tr('Tempo {x}× Echtzeit', { x: zahl(st.rtf) }));
  if (st && st.catchup) hints.push(tr('Aufholmodus: Abschnitte zusammengelegt, sparsam dekodiert'));
  if (st && st.partials_paused) hints.push(tr('Vorschautext pausiert, bis der Rückstand abgebaut ist'));
  $('liveBacklog').title = hints.join(' · ');
  $('liveLevelMic').style.width = Math.min(100, (st && running ? st.level_mic || 0 : 0) * 150) + '%';
  $('liveLevelSys').style.width = Math.min(100, (st && running ? st.level_sys || 0 : 0) * 150) + '%';

  // Beim ersten Start wird das Modell heruntergeladen; aus dem Cache gibt es keine Byte-Meldung.
  const dl = s.download;
  const mb = (bytes) => Math.round(bytes / 1048576);
  $('liveLoadBox').hidden = s.phase !== 'laden';
  $('liveLoadBarBox').classList.toggle('wait', !dl);
  $('liveLoadStep').textContent = dl
    ? tr('Modell {modell} wird heruntergeladen – {fertig} von {gesamt} MB ({prozent} %)', {
      modell: dl.model, fertig: mb(dl.done), gesamt: mb(dl.total), prozent: Math.floor(dl.done / dl.total * 100) })
    : tr('Modell {modell} wird geladen …', { modell: s.model || '' }) + (s.step ? ' – ' + s.step : '');
  $('liveLoadBar').style.width = dl ? (dl.done / dl.total * 100) + '%' : '';

  const r = s.refine;
  $('liveRefineBox').hidden = s.phase !== 'nachschaerfen';
  if (r && r.index) {
    $('liveRefineStep').innerHTML = `${tr('Nachschärfen')} – <span class="stage">${tr('Stufe {i}/{n}: {name}', { i: r.index, n: r.total, name: esc(r.name) })}</span>`;
    $('liveRefineBar').style.width = Math.round(((r.index - 1) + (r.percent || 0) / 100) / r.total * 100) + '%';
  }

  renderFazit(s.fazit);
  renderSouffleur(s);
  liveDir = s.dir || null;
  // Automatisch gespeichert (Nachlauf) oder frueher per Dialog - der Server kennt den Vermerk.
  if (s.nachlauf && s.nachlauf.wiki_ablage) liveAblage = s.nachlauf.wiki_ablage;
  else if (s.wiki_ablage && !liveAblage) liveAblage = s.wiki_ablage;
  renderResult(s, running);
  renderHandover(liveAblage);
  renderNext(s);
  renderDemo(s);
  // Eine eben beendete Sitzung kann eine unterbrochene gewesen sein - Banner nachziehen.
  if (warLaufend && !running) loadUnterbrochen();
}

/**
 * Infobox nach dem Ende: Fehler zuerst, dann der Sitzungsordner - und von dort aus
 * "Speichern unter ..." (Transkript und Bilder an zwei Ziele, mit dem Wiki vorbelegt) bzw. wo
 * die Sitzung schon liegt. In beiden Modi: Projekt und "Sofort aufnehmen".
 */
function renderResult(s, running) {
  const box = $('liveResult');
  const demo = modus() === 'demo';
  const fehler = s.phase === 'fehler' && s.error ? `${esc(s.error)}` : '';
  const beendet = !running && s.phase === 'beendet' && !!s.dir && !demo;
  const key = JSON.stringify([running, fehler, s.dir, demo, beendet, liveAblage && liveAblage.ordner, liveAblage && liveAblage.frei]);
  if (box.dataset.key === key) return;  // Poll alle 500 ms - nur bei Aenderung neu zeichnen
  box.dataset.key = key;
  const ordner = s.dir && !demo ? tr('Sitzungsordner: {pfad}', { pfad: `<code>${esc(s.dir)}</code>` }) + '<br>'
    + tr('Die Live-Fassung liegt als {datei} daneben.', { datei: '<code>transkript.live.md</code>' }) : '';
  let ablage = '';
  if (beendet && liveAblage) {
    const pfad = `<code>${esc(liveAblage.ordner)}</code>`;
    ablage = `${liveAblage.frei ? tr('Gespeichert: {ordner}', { ordner: pfad }) : tr('Im Wiki gespeichert: {ordner}', { ordner: pfad })}
      <button class="ghost sm" type="button" data-folder="${esc(liveAblage.ordner)}">${icon('external')}${tr('Ordner öffnen')}</button>`;
  } else if (beendet) {
    ablage = `<button class="secondary sm" type="button" data-speichern-unter>${icon('book-plus')}${tr('Speichern unter …')}</button>`;
  }
  box.innerHTML = !running && (fehler || ordner)
    ? `<div class="result ${s.phase === 'fehler' ? 'fehler' : ''}">${[fehler, ordner, ablage].filter(Boolean).join('<br>')}</div>` : '';
}

/** Fazit (Rechendauer, Latenz) der Live-Aufnahme und des Nachschaerfens - erscheint,
 *  sobald der jeweilige Teil fertig ist, und bleibt bis zum Zuruecksetzen stehen. */
function renderFazit(f) {
  const box = $('liveFazit');
  if (!f || (!f.live && !f.nachschaerfen)) { box.hidden = true; box.innerHTML = ''; return; }
  const tempo = (v) => (v === null || v === undefined) ? '' : ` (${tr('{x}× Echtzeit', { x: zahl(v) })})`;
  const tempoVorschau = (v) => (v === null || v === undefined) ? '' : ` (${tr('{x}× inkl. Vorschau', { x: zahl(v) })})`;
  const rows = [];
  const l = f.live;
  if (l) {
    rows.push([tr('Aufnahme'), tr('{dauer} · Modelle geladen in {laden} · Abschluss {abschluss}', {
      dauer: hms(l.aufnahme_s), laden: secs(l.laden_s), abschluss: secs(l.abschluss_s) })]);
    // Tempo = nur Dekodieren; "inkl. Vorschau" zeigt, was die Vorschau obendrauf kostet.
    let rechnen = tr('{zeit}{tempo} für {n} Abschnitte', { zeit: secs(l.rechenzeit_s), tempo: tempo(l.tempo), n: l.abschnitte });
    const klammer = [];
    if (l.zusammengelegt) klammer.push(tr('{n} zusammengelegt', { n: l.zusammengelegt }));
    if (l.eco_abschnitte) klammer.push(tr('{n} sparsam dekodiert', { n: l.eco_abschnitte }));
    if (l.uebersprechen_verworfen) klammer.push(tr('{n} als Übersprechen verworfen', { n: l.uebersprechen_verworfen }));
    if (klammer.length) rechnen += ` (${klammer.join(', ')})`;
    if (l.sprecher_s) rechnen += ' · ' + tr('davon Sprecher {dauer}', { dauer: secs(l.sprecher_s) });
    if (l.vorschau_n) {
      rechnen += ' · ' + tr('{n} Vorschauen {dauer}', { n: l.vorschau_n, dauer: secs(l.vorschau_s) }) + tempoVorschau(l.tempo_inkl_vorschau);
    }
    rows.push([tr('Rechenzeit'), rechnen]);
    if (l.abschnitte) {
      let lag = tr('Ø {mittel} · Median {median} · max {max}', {
        mittel: secs(l.verzoegerung_mittel_s), median: secs(l.verzoegerung_median_s), max: secs(l.verzoegerung_max_s) });
      lag += ' · ' + tr('Rückstand max {dauer}', { dauer: secs(l.rueckstand_max_s) });
      if (l.aufholmodus_s) {
        lag += ' · ' + tr('Aufholmodus {dauer}', { dauer: secs(l.aufholmodus_s) });
        if (l.aufholmodus_anteil) lag += ` (${Math.round(l.aufholmodus_anteil * 100)} %)`;
      }
      rows.push([tr('Verzögerung'), lag]);
    }
  }
  const n = f.nachschaerfen;
  if (n) {
    const stufen = (n.stufen || []).map((st) => `${st.name} ${secs(st.dauer_s)}`).join(' · ');
    rows.push([tr('Nachschärfen'), `${hms(n.gesamt_s)}${tempo(n.tempo)}${stufen ? ' · ' + stufen : ''}`]);
    // Übersprechen: Mikrofon-Segmente, die nur das Lautsprecher-Echo der Gegenseite waren,
    // und der Abgleich mit den Live-Entscheidungen (zurückgeholt = live zu Unrecht verworfen).
    const u = n.uebersprechen;
    if (u && u.geprueft) {
      const abgleich = [];
      if (u.bestaetigt) abgleich.push(tr('live bestätigt {n}', { n: u.bestaetigt }));
      if (u.zurueckgeholt) abgleich.push(tr('zurückgeholt {n}', { n: u.zurueckgeholt }));
      if (u.nachtraeglich_entfernt) abgleich.push(tr('nachträglich entfernt {n}', { n: u.nachtraeglich_entfernt }));
      let text = tr('{verworfen} von {geprueft} Mikrofon-Segmenten verworfen', { verworfen: u.verworfen, geprueft: u.geprueft });
      if (abgleich.length) text += ` (${abgleich.join(', ')})`;
      if (u.lag_s !== undefined && u.lag_s !== null) text += ' · ' + tr('Zeitversatz {s} s', { s: zahl(u.lag_s) });
      rows.push([tr('Übersprechen'), text]);
    }
  }
  box.innerHTML = `<div class="result fazit"><b>${tr('Fazit')}</b><dl>${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl></div>`;
  box.hidden = false;
}

function openLightbox(index) {
  if (!liveShots.length) return;
  lightboxIndex = (index + liveShots.length) % liveShots.length;
  const shot = liveShots[lightboxIndex];
  $('lightboxImg').src = shotUrl(shot);
  $('lightboxCap').textContent = tr('Bild #{nr} – {zeit} ({i} von {n})', {
    nr: String(shot.id).padStart(4, '0'), zeit: tc(shot.t), i: lightboxIndex + 1, n: liveShots.length });
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
  if (!tile || tile.classList.contains('disabled')) return;
  if (tile.dataset.winpick) { openWinPick(tile); return; }
  switchSource({ kind: tile.dataset.kind, id: Number(tile.dataset.id) });
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
  // Bevorzugte Anwendungen (Teams) stehen vorn - der Server sortiert so - und sind markiert.
  $('winList').innerHTML = groups.size
    ? [...groups].map(([process, ws]) =>
      `<div class="source-group${ws[0].bevorzugt ? ' prio' : ''}"><div class="source-title">${esc(process)}<span class="count">${ws.length}</span>`
      + `${ws[0].bevorzugt ? `<span class="tag">${tr('bevorzugt')}</span>` : ''}</div>`
      + `<div class="monitors">${ws.map((w) => winTile(w, stamp)).join('')}</div></div>`).join('')
      + `<div class="empty" id="winNoMatch" hidden>${icon('monitor')}${tr('Kein Fenster passt zum Filter.')}</div>`
    : empty('monitor', tr('Keine Anwendungsfenster gefunden.'));
  fallbackOnError($('winList'), tr('kein Bild'));
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
    ? (q ? tr('{n} von {gesamt} Fenstern', { n: shown, gesamt: tiles.length })
      : tiles.length === 1 ? tr('1 Fenster') : tr('{n} Fenster', { n: tiles.length })) : '';
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
  closeWinPick();
  switchSource({ kind: 'window', id: hwnd });  // ersetzt die Kachel, die eben noch den Fokus hatte
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
    renderWindowTile();  // Teams-Kachel und gewaehltes Fenster folgen der frischen Liste
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
    if (!istAusgekoppelt()) setSouffleurHidden(!$('liveAside').classList.contains('collapsed'));
    return;
  }
  // Alt+P: Souffleur als kleines Fenster aus- und wieder einkoppeln (e.code: Alt+P liefert auf dem Mac "π").
  if (e.altKey && !e.ctrlKey && !e.metaKey && e.code === 'KeyP' && !$('tabLive').hidden && pipMoeglich) {
    e.preventDefault();
    souffleurPip();
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
  if (modus() === 'projekt' || modus() === 'aufnahme') loadUnterbrochen();
  pollStatus.start();
}

// Ein ausgekoppelter Souffleur zeigt weiter, was die Sitzung tut - auch wenn das Hauptfenster woanders ist.
export function leaveLive() { liveSichtbar = false; if (!istAusgekoppelt()) pollStatus.stop(); }
document.addEventListener('audioscribe:souffleur-zurueck', () => { if (!liveSichtbar) pollStatus.stop(); });
// Start aus dem ausgekoppelten Souffleur-Fenster: dieselbe Sitzung wie der Knopf in der
// Live-Ansicht. Eine Fehlermeldung landet sonst nur im Hauptfenster - darum auch im Souffleur.
document.addEventListener('audioscribe:live-start', async () => {
  if (liveRunning) return;
  await startLive();
  const fehler = $('liveErr').textContent;
  $('pipStart').disabled = false;
  if (fehler) $('souffleurErr').textContent = fehler;
});

/** Kontextwechsel: die Ansicht beginnt leer, Geraete und Vorgaben werden neu geholt. */
export function leereLive() {
  liveBereit = false;
  liveRunning = false;
  souffleurEinkoppeln();
  resetLiveView();
  renderSofort(null);
  $('liveTitle').value = '';
  $('liveArt').value = '';
  $('liveResume').innerHTML = '';
  $('liveErr').textContent = '';
  $('demoErr').textContent = '';
}

/** Einstellungen geaendert: nur die Sprache nachziehen - Geraete- und Quellenwahl bleiben stehen. */
export function aktualisiereLiveSprache(d) {
  if (liveBereit && !liveRunning && d && d.languages) fill($('liveLang'), d.languages, d.language);
}

// --- Nach der Sitzung: ins Wiki, zur KI (PRD §21) ---------------------------------------------

/** "Transkript" bzw. "Transkript und n Bilder" - steht in den Karten jeweils am Satzanfang. */
const transkriptUnd = (bilder) => (bilder ? tr('Transkript und {n} Bilder', { n: bilder }) : tr('Transkript'));
const ordnerOeffnen = (pfad, cls) =>
  `<button class="${cls}" type="button" data-folder="${esc(pfad)}">${icon('external')}${tr('Ordner öffnen')}</button>`;

/** "Sofort aufnehmen": nach dem Stopp die Sitzung einem Projekt zuordnen. */
function renderAblegen(s) {
  const box = $('liveNext');
  const zeigen = !s.running && !!s.dir && s.phase === 'beendet';
  const key = JSON.stringify(['aufnahme', zeigen, s.dir, liveAblage, liveShots.length]);
  if (box.dataset.key === key) return;
  box.dataset.key = key;
  box.hidden = !zeigen;
  if (!zeigen) { box.innerHTML = ''; return; }
  const bilder = liveShots.length;
  const speichern = liveAblage
    ? `<div class="next-item done"><b>${icon('check')}${tr('Gespeichert')}</b>
        <span><code>${esc(liveAblage.ordner)}</code>${liveAblage.bilder ? ' · ' + tr('{n} Bilder', { n: liveAblage.bilder }) : ''}</span>
        ${ordnerOeffnen(liveAblage.ordner, 'ghost sm')}</div>`
    : `<div class="next-item"><b>${icon('book-plus')}${tr('Speichern unter …')}</b>
        <span>${tr('{was} in Ordner deiner Wahl – vorbelegt mit {raw} des Wikis aus den Einstellungen, falls eins verknüpft ist.', { was: transkriptUnd(bilder), raw: '<code>raw/</code>' })}</span>
        <button type="button" data-speichern-unter>${icon('book-plus')}${tr('Speichern unter …')}</button></div>`;
  box.innerHTML = `<h3>${tr('Sitzung ablegen')}</h3>
    <p>${tr('Die Sitzung liegt im Eingangsordner: {pfad}', { pfad: `<code>${esc(s.dir)}</code>` })}</p>
    <div class="next-grid">
      ${speichern}
      <div class="next-item"><b>${icon('folder-open')}${tr('Einem Projekt zuordnen')}</b>
        <span>${tr('In ein vorhandenes Projekt verschieben oder dafür ein neues anlegen – danach geht es dort ins Wiki oder zur KI.')}</span>
        <button class="secondary" type="button" id="liveZuordnen">${icon('folder-open')}${tr('Projekt zuordnen …')}</button></div>
      <div class="next-item"><b>${icon('history')}${tr('Später entscheiden')}</b>
        <span>${tr('Die Sitzung wartet auf der Startseite unter „Aufnahmen ohne Projekt“.')}</span>
        ${ordnerOeffnen(s.dir, 'secondary')}</div>
    </div>`;
}

function renderNext(s) {
  if (modus() === 'aufnahme') { renderAblegen(s); return; }
  const box = $('liveNext');
  const p = projekt();
  const zeigen = modus() === 'projekt' && !!p && !s.running && !!s.dir && s.phase === 'beendet';
  const fehler = (s.nachlauf && (s.nachlauf.wiki_fehler || s.nachlauf.fehler)) || '';
  const key = JSON.stringify([zeigen, s.dir, liveAblage, p && p.wiki_speichern, p && p.hat_wiki, fehler, liveShots.length]);
  if (box.dataset.key === key) return;
  box.dataset.key = key;
  box.hidden = !zeigen;
  if (!zeigen) { box.innerHTML = ''; return; }
  const bilder = liveShots.length;
  let wiki = '';
  if (liveAblage) {
    const a = liveAblage;
    const zusatz = (a.bilder ? ' · ' + (a.frei ? tr('{n} Bilder', { n: a.bilder }) : tr('{n} Bilder im Assets-Ordner', { n: a.bilder })) : '')
      + (a.markierungen ? ' · ' + tr('{n} Markierungen', { n: a.markierungen }) : '');
    wiki = `<div class="next-item done"><b>${icon('check')}${a.frei ? tr('Gespeichert') : tr('Im Wiki gespeichert')}</b>
      <span><code>${esc(a.ordner)}</code>${zusatz}</span>
      ${ordnerOeffnen(a.ordner, 'ghost sm')}</div>`;
  } else if (!p.hat_wiki) {
    const link = `<a class="goto" href="#/projekt/einstellungen">${tr('Wiki anlegen oder verknüpfen')}</a>`;
    wiki = `<div class="next-item"><b>${icon('book-plus')}${tr('Speichern unter …')}</b>
      <span>${tr('Dieses Projekt hat kein Wiki – {was} lassen sich in Ordner deiner Wahl kopieren.', { was: transkriptUnd(bilder) })}
        ${tr('Mit einem Wiki ginge die Sitzung als neue Quelle hinein: {link}.', { link })}</span>
      <button class="secondary" type="button" data-speichern-unter>${icon('book-plus')}${tr('Speichern unter …')}</button></div>`;
  } else if (p.wiki_speichern !== 'nie' || fehler) {
    wiki = `<div class="next-item"><b>${icon('book-plus')}${tr('Ins Wiki speichern')}</b>
      <span>${fehler ? `<span class="err">${esc(fehler)}</span>` : ''}${tr('{was} als neue Quelle unter {raw} ablegen – oder unter einem anderen Ort; die Markierungen des Souffleurs nur auf Wunsch.', { was: transkriptUnd(bilder), raw: '<code>raw/</code>' })}</span>
      <button type="button" id="liveWikiSave" data-speichern-unter>${icon('book-plus')}${tr('Ins Wiki speichern …')}</button></div>`;
  } else {
    wiki = `<div class="next-item"><b>${icon('book-plus')}${tr('Speichern unter …')}</b>
      <span>${tr('{was} ins Wiki oder in Ordner deiner Wahl kopieren.', { was: transkriptUnd(bilder) })}</span>
      <button class="secondary" type="button" data-speichern-unter>${icon('book-plus')}${tr('Speichern unter …')}</button></div>`;
  }
  const ki = cloudCompliant() ? '' : `<div class="next-item"><b>${icon('sparkles')}${tr('Mit KI nachbereiten')}</b>
      <span>${tr('Die KI wertet Transkript und Bilder aus. Das Ergebnis kann danach ebenfalls ins Wiki.')}</span>
      <button class="secondary" type="button" id="liveToKi">${tr('Zur Nachbereitung')}${icon('arrow-right')}</button></div>`;
  box.innerHTML = `<h3>${tr('Wie geht es weiter?')}</h3>
    <p>${tr('Die Sitzung ist im Sitzungsordner gesichert.')}${ki ? ' ' + tr('Beides ist möglich – in beliebiger Reihenfolge.') : ''}</p>
    <div class="next-grid">${wiki}${ki}</div>`;
}

/** "Speichern unter ..." bzw. "Ins Wiki speichern": derselbe Dialog, danach Karten nachziehen. */
async function speichernUnter() {
  if (!liveDir) return;
  const ablage = await openWikiDialog({
    path: liveDir, name: basename(liveDir), titel: $('liveTitle').value.trim(), art: $('liveArt').value,
    frames: liveShots.length,
  });
  if (ablage) {
    liveAblage = ablage;
    delete $('liveNext').dataset.key; delete $('liveResult').dataset.key;
    pollLive();
  }
}

async function nachSitzungKlick(e) {
  const folder = e.target.closest('[data-folder]');
  if (folder) { post('/api/oeffnen', { pfad: folder.dataset.folder }).catch((err) => toast(err.message, 'fehler')); return; }
  if (e.target.closest('#liveZuordnen') && liveDir) {
    zuordnenDialog(liveDir, $('liveTitle').value.trim());
    return;
  }
  if (e.target.closest('[data-speichern-unter]')) { speichernUnter(); return; }
  if (e.target.closest('#liveToKi') && liveDir) {
    S.vorwahl = liveDir;
    go('#/projekt/nachbereitung');
  }
}

$('liveNext').addEventListener('click', nachSitzungKlick);
$('liveResult').addEventListener('click', nachSitzungKlick);

// --- Wiederaufnahme nach einem Absturz (PRD §21) ----------------------------------------------

async function loadUnterbrochen() {
  const box = $('liveResume');
  const p = projekt();
  // Im Projekt dessen Sitzungen, bei "Sofort aufnehmen" die ohne Projekt (projekt == "").
  const wurzel = modus() === 'projekt' && p ? p.wurzel : modus() === 'aufnahme' ? '' : null;
  if (wurzel === null || liveRunning) { box.innerHTML = ''; return; }
  let liste = [];
  try {
    liste = (await api('/api/live/unterbrochen')).sitzungen.filter((s) => s.projekt === wurzel);
  } catch (e) { return; }
  box.innerHTML = liste.map((s) => `
    <div class="banner" role="status">
      ${icon('triangle')}
      <div class="text"><b>${s.titel ? tr('Unterbrochene Sitzung „{titel}“', { titel: esc(s.titel) }) : tr('Unterbrochene Sitzung')}</b>
        <small>${esc(s.gestartet ? s.gestartet.replace('T', ' ').slice(0, 16) : s.name)} · ${tr('{dauer} aufgezeichnet', { dauer: hms(s.dauer_s || 0) })} ·
          ${tr('{n} Abschnitte gesichert.', { n: s.segmente || 0 })} ${tr('Fortsetzen nimmt mit den links gewählten Geräten weiter auf.')}</small></div>
      <div class="actions">
        <button type="button" data-resume="${esc(s.dir)}" data-titel="${esc(s.titel || '')}">${icon('record')}${tr('Fortsetzen')}</button>
        <button class="secondary" type="button" data-finalize="${esc(s.dir)}">${icon('check')}${tr('Abschließen')}</button>
        <button class="ghost" type="button" data-discard="${esc(s.dir)}">${tr('Verwerfen')}</button>
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
        title: tr('Unterbrochene Sitzung verwerfen?'),
        text: tr('Die Sitzung wird nicht mehr zum Fortsetzen angeboten. Mitschnitt und bisheriges Transkript bleiben im Sitzungsordner liegen.'),
        ok: tr('Verwerfen'),
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
  // "Weiter" heisst im Assistenten "Next" (en/seite.js) - hier ist es Fortsetzen nach der Pause.
  $('demoPauseLabel').textContent = englisch ? (pausiert ? tr('Fortsetzen') : tr('Pause')) : (pausiert ? 'Weiter' : 'Pause');
  $('demoPauseIcon').setAttribute('href', pausiert ? '#i-play' : '#i-pause');
  $('demoStart').lastChild.textContent = s.phase === 'beendet' || s.phase === 'fehler' ? tr('Demo erneut starten') : tr('Demo starten');
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
  const pfad = await pickFolder({ title: tr('Sitzungsordner zum Abspielen wählen'), start: start.trim() || S.folders.output_dir });
  if (pfad) { $('liveTestFile').value = pfad; rememberReplay(); }
};

// Der Wiki-Zustand des Projekts steht in der Souffleur-Karte, solange keine Sitzung laeuft.
document.addEventListener('audioscribe:wiki', zeigeWikiStatus);
