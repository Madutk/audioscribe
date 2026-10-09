// Gemeinsame Bausteine aller Ansichten: DOM-Helfer, Server-Aufrufe, geteilter Zustand, Meldungen.

export const $ = (id) => document.getElementById(id);
export const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
export const icon = (name) => `<svg class="ic" aria-hidden="true"><use href="#i-${name}"/></svg>`;
export const empty = (name, text) => `<div class="empty">${icon(name)}${esc(text)}</div>`;
export const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// Ein Zustand fuer alle Module. `kontext` kommt aus /api/kontext (Modus, Projekt, zuletzt
// geoeffnete), `defaults` aus /api/defaults (Auswahllisten, Ordner des Kontexts).
export const S = {
  kontext: null,
  defaults: null,
  // Ordner der Arbeitsansichten. Im Projekt bestimmt sie das Projekt; bei "Aufnahme
  // transkribieren" pflegt sie die Ansicht selbst (Speicherort, Ausgabeordner Analysen).
  folders: { input_dir: '', output_dir: '', agent_output_dir: '' },
  wikiStatus: null,     // /api/wiki/status des Projekt-Wikis - gilt, solange keine Sitzung laeuft
  vorwahl: null,        // Ergebnisordner, den die Nachbereitung als Quelle vorwaehlen soll
  zuordnen: null,       // Aufnahme ohne Projekt, die nach "Neues Projekt" ins neue Projekt wandert
};

export const modus = () => (S.kontext ? S.kontext.modus : 'start');
export const projekt = () => (S.kontext ? S.kontext.projekt : null);

// --- Server ---------------------------------------------------------------------------

let verbunden = true;
function setVerbunden(ok) {
  if (ok === verbunden) return;
  verbunden = ok;
  $('connLost').hidden = ok;
  if (ok) document.dispatchEvent(new CustomEvent('audioscribe:verbunden'));
}

export async function api(path, opts) {
  let res;
  try {
    res = await fetch(path, opts);
  } catch (err) {
    // Der Server antwortet nicht (beendet, abgestuerzt): Hinweis zeigen; das Polling der
    // Ansichten laeuft weiter und meldet die Rueckkehr von selbst.
    setVerbunden(false);
    throw new Error('Keine Verbindung zu AudioScribe.');
  }
  setVerbunden(true);
  let data = null;
  try { data = await res.json(); } catch (e) { /* leer */ }
  if (!res.ok) throw new Error((data && data.detail) || res.statusText);
  return data;
}

const mitJson = (method) => (path, body) => api(path, {
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body === undefined ? {} : body),
});
export const post = mitJson('POST');
export const put = mitJson('PUT');

// --- Zeit, Pfade, Auswahlfelder ----------------------------------------------------------

/** Sekunden -> "1:23:45" bzw. "4:05". */
export function hms(seconds) {
  if (!seconds && seconds !== 0) return '–';
  const s = Math.round(seconds), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  const pad = (n) => String(n).padStart(2, '0');
  return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${m}:${pad(s % 60)}`;
}

/** Restzeit bewusst grob: unter 30 min auf Minuten, darueber auf 5 min gerundet. */
export function coarse(seconds) {
  const min = Math.max(1, Math.round(seconds / 60));
  if (min < 30) return `${min} min`;
  const rounded = Math.round(min / 5) * 5;
  return rounded < 60 ? `${rounded} min` : `${Math.floor(rounded / 60)} h ${rounded % 60 || ''}`.trim();
}

export const tc = (seconds) => {
  const s = Math.max(0, Math.round(seconds)), pad = (n) => String(n).padStart(2, '0');
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
};
export const secs = (v) => (v === null || v === undefined) ? '–' : v.toFixed(1).replace('.', ',') + ' s';

export const sep = () => (S.kontext && S.kontext.platform === 'windows' ? '\\' : '/');
export const trimSep = (path) => String(path || '').replace(/[\\/]+$/, '');
export const basename = (path) => trimSep(path).split(/[\\/]/).pop() || '';
export const dirname = (path) => trimSep(path).replace(/[\\/][^\\/]*$/, '');

export function fill(sel, values, chosen) {
  const all = values.includes(chosen) ? values : [chosen, ...values];
  sel.innerHTML = all.map((v) => `<option value="${esc(v)}">${esc(v)}</option>`).join('');
  sel.value = chosen;
}

/** Hinweistext je KI-Dienst (Einstellungen, Projekt, Assistent). */
const DIENST_HINWEIS = {
  'claude-agent': 'Der Dienst hinter Souffleur und KI-Analyse. Er nutzt die Anmeldung von Claude Code auf diesem Rechner.',
  ollama: 'Lokales Modell über Ollama auf diesem Rechner: nichts verlässt den Rechner, der Verbrauch zählt nicht. '
    + 'Das Modell vorher mit „ollama pull“ laden („Umgebung prüfen“ zeigt den Stand). Die KI-Analyse lokal ist experimentell.',
  attrappe: 'Regelbasierter Ersatz ohne Netz – nur für Tests.',
};
export function dienstHinweis(dienst) {
  return DIENST_HINWEIS[dienst] || 'Dieser Dienst ist über die Umgebung eingestellt.';
}

/** Modelle, die zu einem Dienst gehoeren (Eintraege ohne `dienst` passen immer). */
export function modelleFuer(liste, dienst) {
  const passend = (liste || []).filter((m) => !m.dienst || m.dienst === dienst);
  return passend.length ? passend : (liste || []);
}

/** `wert`, wenn er zum Dienst passt, sonst das erste passende Modell. */
export function passendesModell(liste, dienst, wert) {
  const passend = modelleFuer(liste, dienst);
  return passend.some((m) => m.id === wert) ? wert : (passend[0] ? passend[0].id : wert);
}

/** Auswahlfeld aus [{id, label}]; `leer` setzt einen ersten Eintrag mit leerem Wert davor. */
export function fillOptions(sel, eintraege, chosen, leer) {
  const liste = leer ? [{ id: '', label: leer }, ...eintraege] : eintraege;
  sel.innerHTML = liste.map((e) => `<option value="${esc(e.id)}">${esc(e.label)}</option>`).join('');
  sel.value = chosen || '';
  if (sel.selectedIndex < 0) sel.selectedIndex = 0;
}

/** Geraete, die die Probe als nicht verfuegbar meldet (cuda ohne NVIDIA, mps ausserhalb
 *  von Apple Silicon), bleiben sichtbar, aber ausgegraut; eine gemerkte Wahl faellt auf auto. */
export function markUnavailable(select) {
  for (const dev of ['cuda', 'mps']) {
    if (!S.defaults || S.defaults[dev] !== false) continue;
    const opt = [...select.options].find((o) => o.value === dev);
    if (opt) { opt.disabled = true; opt.textContent = `${dev} (nicht verfügbar)`; }
    if (select.value === dev) select.value = 'auto';
  }
}

/** Protokolle sind eingeklappt; beim Aufklappen ans Ende springen. */
export function wireLogs() {
  for (const box of document.querySelectorAll('details.log')) {
    box.addEventListener('toggle', () => { const pre = box.querySelector('pre'); if (box.open) pre.scrollTop = pre.scrollHeight; });
  }
}

export function appendLog(pre, lines) {
  if (!lines.length) return;
  const atBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 40;
  pre.textContent += lines.join('\n') + '\n';
  if (atBottom) pre.scrollTop = pre.scrollHeight;
}

// --- Meldungen ---------------------------------------------------------------------------

/** Kurze Bestaetigung unten rechts (aria-live); Fehler bleiben laenger stehen. */
export function toast(text, art = 'ok') {
  const el = document.createElement('div');
  el.className = `toast ${art === 'fehler' ? 'fehler' : ''}`;
  el.innerHTML = `${icon(art === 'fehler' ? 'alert' : 'check')}<span>${esc(text)}</span>`;
  $('toasts').append(el);
  setTimeout(() => {
    el.classList.add('geht');
    setTimeout(() => el.remove(), 200);
  }, art === 'fehler' ? 7000 : 3200);
}

/** Wiederkehrende Abfrage, die nur laeuft, solange ihre Ansicht sichtbar ist. */
export function poller(fn, ms) {
  let timer = null;
  return {
    start() { if (timer === null) { timer = setInterval(fn, ms); fn(); } },
    stop() { if (timer !== null) { clearInterval(timer); timer = null; } },
  };
}
