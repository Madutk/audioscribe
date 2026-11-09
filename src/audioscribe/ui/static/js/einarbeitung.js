// Einarbeiten ins Wiki: Warteschlange im Kopf jeder Seite, Dialog je Auftrag (Protokoll des
// Agenten, Rueckfragen, Nachfassen) und die Karte "Ins Wiki einarbeiten" nach einer Sitzung.
// Der Server fuehrt die Auftraege im Hintergrund aus (ui/einarbeitung.py) - unabhaengig davon,
// welches Projekt gerade offen ist, und ueber einen Neustart hinweg.

import { $, api, post, esc, icon, poller, toast, basename, cloudCompliant } from './kern.js';
import { tr } from './i18n.js';

let liste = [];  // letzte Uebersicht (neueste zuerst)
let bekannt = null;  // id -> status beim letzten Abruf (fuer Mitteilungen)
let offen = null;  // id des Auftrags im Dialog
let dlgOffset = 0;
let dlgPoller = null;
let dlgAuftrag = null;
let chatLetzte = null;  // letzte Agenten-Blase (aufeinanderfolgende Zeilen zusammenfassen)

const STATUS = {
  wartet: () => tr('wartet'),
  laeuft: () => tr('läuft'),
  frage: () => tr('Rückfrage'),
  fertig: () => tr('fertig'),
  fehler: () => tr('Fehler'),
  abgebrochen: () => tr('abgebrochen'),
};
const statusText = (s) => (STATUS[s] ? STATUS[s]() : s);
const name = (a) => a.titel || basename(a.rohquelle);
const OFFEN = new Set(['wartet', 'laeuft', 'frage']);

// --- Kopfzeile und Warteschlange --------------------------------------------------------------

function renderKopf(d) {
  const z = d.zaehler;
  const btn = $('wikiJobs');
  btn.hidden = !d.auftraege.length;
  const teile = [];
  if (z.laeuft) teile.push(tr('{n} läuft', { n: z.laeuft }));
  if (z.wartet) teile.push(tr('{n} wartet', { n: z.wartet }));
  if (z.frage) teile.push(z.frage === 1 ? tr('1 Rückfrage') : tr('{n} Rückfragen', { n: z.frage }));
  if (!teile.length) teile.push(tr('Wiki'));
  $('wikiJobsText').textContent = teile.join(' · ');
  btn.classList.toggle('frage', !!z.frage);
  btn.classList.toggle('laeuft', !!z.laeuft);
  btn.setAttribute('aria-label', tr('Einarbeiten ins Wiki: {stand} – Warteschlange anzeigen', { stand: teile.join(', ') }));

  const list = $('wikiJobsList');
  list.dataset.leer = tr('Keine Aufträge.');
  list.innerHTML = d.auftraege.map((a) => {
    const meta = [a.projekt, a.rohquelle].filter(Boolean).map(esc).join(' · ');
    const pos = a.status === 'wartet' && a.position ? ' · ' + tr('Platz {n}', { n: a.position }) : '';
    const schritt = a.fortschritt && a.fortschritt.total
      ? ' · ' + tr('Schritt {i} von {n}', { i: Math.min(a.fortschritt.done + 1, a.fortschritt.total), n: a.fortschritt.total }) : '';
    return `<button class="job-item" type="button" data-auftrag="${esc(a.id)}">
      <span class="name">${esc(name(a))}</span><span class="badge ${esc(a.status)}">${esc(statusText(a.status))}</span>
      <span class="meta">${meta}${pos}${a.status === 'laeuft' ? schritt : ''}${a.hinweis ? ' · ' + esc(a.hinweis) : ''}</span></button>`;
  }).join('');
  $('wikiJobsMitteilung').hidden = !('Notification' in window) || Notification.permission !== 'default';
}

function melde(d) {
  const jetzt = Object.fromEntries(d.auftraege.map((a) => [a.id, a.status]));
  if (bekannt) {
    for (const a of d.auftraege) {
      const vorher = bekannt[a.id];
      if (vorher === a.status || (vorher === undefined && !OFFEN.has(a.status))) continue;
      if (a.status === 'fertig') mitteilung(tr('Ins Wiki eingearbeitet'), name(a), a.id);
      else if (a.status === 'fehler') mitteilung(tr('Einarbeiten fehlgeschlagen'), name(a), a.id);
      else if (a.status === 'frage') mitteilung(tr('Rückfrage beim Einarbeiten'), tr('{name}: Der Agent wartet auf deine Antwort.', { name: name(a) }), a.id);
    }
  }
  bekannt = jetzt;
}

/** Systemmitteilung (macOS: Mitteilungszentrale) - nur, wenn erlaubt; sonst reicht die Kopfzeile. */
function mitteilung(titel, text, id) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  try {
    const n = new Notification(titel, { body: text, tag: `wiki-${id}` });
    n.onclick = () => { window.focus(); oeffneAuftrag(id); n.close(); };
  } catch (err) { /* manche Browser erlauben Mitteilungen nur ueber einen Service Worker */ }
}

export function mitteilungenErfragen() {
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission().then(() => { $('wikiJobsMitteilung').hidden = Notification.permission !== 'default'; }).catch(() => {});
  }
}

async function hole() {
  try {
    const d = await api('/api/wiki/einarbeitung');
    liste = d.auftraege;
    renderKopf(d);
    melde(d);
    aktualisiereKarten();
  } catch (err) { /* Anzeige bleibt beim letzten Stand */ }
}

/** Laeuft unabhaengig von der Ansicht - die Warteschlange steht im Kopf jeder Seite. */
export function starteEinarbeitung() {
  if (cloudCompliant()) return;
  poller(hole, 3000).start();
}

/** Juengster Auftrag zu einer Ablage (Pfad der Rohquelle), sonst null. */
export function auftragFuer(pfad) {
  return liste.find((a) => a.pfad === pfad) || null;
}

// --- Karte nach der Sitzung -------------------------------------------------------------------

/** Platzhalter fuer die Karte; aktualisiereKarten() fuellt ihn mit dem Stand der Warteschlange. */
export function karte(ablage, sitzung) {
  return `<div class="next-item" data-einarbeitung-pfad="${esc(ablage.ordner)}" data-einarbeitung-sitzung="${esc(sitzung)}">${karteInhalt(ablage.ordner)}</div>`;
}

function karteInhalt(pfad) {
  const a = auftragFuer(pfad);
  if (!a) {
    return `<b>${icon('sparkles')}${tr('Ins Wiki einarbeiten')}</b>
      <span>${tr('Der KI-Agent arbeitet die Sitzung nach den Regeln des Wikis ({datei}) in die Seiten ein – im Hintergrund, mit Rückfragen an dich.', { datei: '<code>CLAUDE.md</code>' })}</span>
      <button type="button" data-einarbeiten>${icon('sparkles')}${tr('Einarbeiten')}</button>`;
  }
  const text = {
    wartet: tr('In der Warteschlange – du kannst weiterarbeiten oder ein anderes Projekt öffnen.'),
    laeuft: tr('Der Agent arbeitet die Sitzung gerade ein.'),
    frage: tr('Der Agent hat eine Rückfrage und wartet auf deine Antwort.'),
    fertig: tr('Fertig eingearbeitet. Du kannst nachfassen, wenn etwas nicht passt.'),
    fehler: a.fehler ? esc(a.fehler) : tr('Mit Fehler beendet.'),
    abgebrochen: tr('Abgebrochen.'),
  }[a.status] || '';
  return `<b>${icon(a.status === 'fertig' ? 'check' : 'sparkles')}${tr('Ins Wiki einarbeiten')}
      <span class="badge ${esc(a.status)}">${esc(statusText(a.status))}</span></b>
    <span>${text}</span>
    <button class="${a.status === 'frage' ? '' : 'secondary'}" type="button" data-auftrag="${esc(a.id)}">${a.status === 'frage' ? tr('Antworten') : tr('Ansehen')}${icon('arrow-right')}</button>`;
}

function aktualisiereKarten() {
  for (const el of document.querySelectorAll('[data-einarbeitung-pfad]')) {
    const a = auftragFuer(el.dataset.einarbeitungPfad);
    const key = a ? `${a.id}:${a.status}:${a.fehler || ''}` : '-';
    if (el.dataset.key === key) continue;
    el.dataset.key = key;
    el.innerHTML = karteInhalt(el.dataset.einarbeitungPfad);
    el.classList.toggle('done', !!a && a.status === 'fertig');
  }
}

export async function einarbeiten(sitzung) {
  mitteilungenErfragen();
  try {
    const a = await post('/api/wiki/einarbeiten', { sitzung });
    toast(tr('Zum Einarbeiten eingereiht'));
    await hole();
    oeffneAuftrag(a.id);
  } catch (err) {
    toast(err.message, 'fehler');
  }
}

// --- Dialog je Auftrag ------------------------------------------------------------------------

export function oeffneAuftrag(id) {
  if ($('wikiJobsPop').matches(':popover-open')) $('wikiJobsPop').hidePopover();
  offen = id;
  dlgOffset = 0;
  dlgAuftrag = null;
  chatLetzte = null;
  $('wikiJobChat').innerHTML = '';
  $('wikiJobFrage').hidden = true;
  $('wikiJobFrage').dataset.frage = '';
  $('wikiJobErr').textContent = '';
  if (!$('wikiJobDlg').open) $('wikiJobDlg').showModal();
  if (dlgPoller) dlgPoller.stop();
  dlgPoller = poller(holeAuftrag, 1500);
  dlgPoller.start();
}

function schliesse() {
  if (dlgPoller) dlgPoller.stop();
  dlgPoller = null;
  offen = null;
  if ($('wikiJobDlg').open) $('wikiJobDlg').close();
}

async function holeAuftrag() {
  if (!offen) return;
  const id = offen;
  let d;
  try {
    d = await api(`/api/wiki/einarbeitung/${encodeURIComponent(id)}?offset=${dlgOffset}`);
  } catch (err) {
    if (err.status === 404) { schliesse(); toast(tr('Auftrag nicht gefunden.'), 'fehler'); }
    return;
  }
  if (offen !== id) return;
  dlgOffset = d.offset;
  dlgAuftrag = d;
  chat(d.lines);
  renderKopfDialog(d);
  renderFrage(d);
}

function renderKopfDialog(d) {
  $('wikiJobName').textContent = name(d);
  $('wikiJobStatus').className = `badge ${d.status}`;
  $('wikiJobStatus').textContent = statusText(d.status);
  const meta = [d.projekt, `${d.rohquelle} → ${d.wiki_dir}`].filter(Boolean).join(' · ');
  $('wikiJobMeta').textContent = meta;
  const p = d.fortschritt;
  const plan = [];
  if (p && p.total) plan.push(`<span class="badge laeuft">${tr('Schritt {i} von {n}', { i: Math.min(p.done + (p.current ? 1 : 0), p.total), n: p.total })}</span>`);
  if (p && p.current && OFFEN.has(d.status)) plan.push(`<span>${esc(p.current)}</span>`);
  if (p && p.skill) plan.push(`<span class="badge">${tr('Skill: {name}', { name: esc(p.skill) })}</span>`);
  if (p && p.docs && p.docs.length) plan.push(`<span>${tr('{n} Seiten geschrieben', { n: p.docs.length })}</span>`);
  $('wikiJobPlan').innerHTML = plan.join(' ');
  const hinweis = d.status === 'wartet' && d.position ? tr('Platz {n} in der Warteschlange.', { n: d.position })
    : d.status === 'wartet' ? tr('Wartet in der Warteschlange.') : '';
  $('wikiJobHint').textContent = [d.hinweis, hinweis].filter(Boolean).join(' ');
  $('wikiJobCancel').hidden = !OFFEN.has(d.status);
  $('wikiJobRetry').hidden = !['fehler', 'abgebrochen'].includes(d.status);
  $('wikiJobRemove').hidden = OFFEN.has(d.status);
  $('wikiJobSeite').hidden = !d.quellseite;
  // Nachfassen erst nach dem Lauf - in dieselbe Claude-Sitzung.
  $('wikiJobSend').hidden = OFFEN.has(d.status) || !d.session_id;
}

const KENNUNG = {
  You: 'Du', Question: 'Frage', Answer: 'Antwort', Tool: 'Werkzeug', 'Tool error': 'Werkzeug-Fehler',
  Denied: 'Verweigert', Result: 'Ergebnis', Usage: 'Verbrauch',
};

/** Protokollzeilen als Dialog: Agent links, du rechts, Werkzeuge klein dazwischen. */
function chat(lines) {
  if (!lines.length) return;
  const box = $('wikiJobChat');
  const unten = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
  for (const line of lines) {
    // Die Kennungen der Protokollzeilen folgen der Sprache der Oberflaeche (agent/runner.py).
    const m = /^\[(Agent|Du|You|Frage|Question|Antwort|Answer|Werkzeug|Tool|Werkzeug-Fehler|Tool error|Verweigert|Denied|Plan|Ergebnis|Result|Verbrauch|Usage|claude)\] ?(.*)$/.exec(line);
    const art = m ? (KENNUNG[m[1]] || m[1]) : null;
    const text = m ? m[2] : line;
    if (art === 'Agent') {
      if (chatLetzte) { chatLetzte.textContent += '\n' + text; continue; }
      chatLetzte = blase('agent', text, tr('Agent'));
      box.append(chatLetzte);
      continue;
    }
    chatLetzte = null;
    if (art === 'claude') continue;  // stderr von Claude Code: steht in agent-log.txt
    if (art === 'Du') box.append(blase('du', text, tr('Du')));
    else if (art === 'Frage') box.append(blase('frage', text, tr('Rückfrage')));
    else if (art === 'Antwort') box.append(blase('antwort', text, tr('Deine Antwort')));
    else if (art === 'Werkzeug' || art === 'Plan') box.append(zeile('tool', text));
    else if (art === 'Werkzeug-Fehler' || art === 'Verweigert') box.append(zeile('tool fehler', text));
    else if (line.trim()) box.append(zeile('sys', text));
  }
  if (unten) box.scrollTop = box.scrollHeight;
}

function blase(cls, text, wer) {
  const el = document.createElement('div');
  el.className = `msg ${cls}`;
  const b = document.createElement('b');
  b.textContent = wer;
  el.append(b, document.createTextNode(text));
  return el;
}

function zeile(cls, text) {
  const el = document.createElement('div');
  el.className = cls;
  el.textContent = text;
  return el;
}

/** Offene Rueckfrage als Formular: je Frage Optionen (einfach/mehrfach) und ein Freitext. */
function renderFrage(d) {
  const box = $('wikiJobFrage');
  const f = d.status === 'frage' ? d.frage : null;
  if (!f) { box.hidden = true; box.dataset.frage = ''; box.innerHTML = ''; return; }
  if (box.dataset.frage === f.id) return;  // Eingaben nicht beim Abruf ueberschreiben
  box.dataset.frage = f.id;
  box.hidden = false;
  box.innerHTML = f.questions.map((q, i) => {
    const typ = q.multiSelect ? 'checkbox' : 'radio';
    const opts = (q.options || []).map((o) => `<label class="option"><input type="${typ}" name="wf${i}" value="${esc(o.label)}" />
        <span>${esc(o.label)}${o.description ? `<small>${esc(o.description)}</small>` : ''}</span></label>`).join('');
    return `<fieldset data-frage="${i}">
      ${q.header ? `<div class="hdr">${esc(q.header)}</div>` : ''}<legend>${esc(q.question)}</legend>
      ${opts}<textarea rows="2" data-frei="${i}" placeholder="${esc(tr('Eigene Antwort (optional) …'))}" aria-label="${esc(tr('Eigene Antwort'))}"></textarea></fieldset>`;
  }).join('') + `<div class="row">
      <button class="ghost sm" type="button" id="wikiJobSkip">${tr('Nicht beantworten')}</button>
      <button type="button" id="wikiJobAnswer">${icon('check')}${tr('Antwort senden')}</button></div>`;
  box.querySelector('input, textarea').focus();
}

async function sendeAntwort(ablehnen) {
  const d = dlgAuftrag;
  if (!d || !d.frage) return;
  let antworten = null;
  if (!ablehnen) {
    antworten = {};
    for (const [i, q] of d.frage.questions.entries()) {
      const gewaehlt = [...$('wikiJobFrage').querySelectorAll(`input[name="wf${i}"]:checked`)].map((x) => x.value);
      const frei = $('wikiJobFrage').querySelector(`[data-frei="${i}"]`).value.trim();
      const wert = [...gewaehlt, ...(frei ? [frei] : [])].join(', ');
      if (!wert) { $('wikiJobErr').textContent = tr('Bitte jede Frage beantworten – oder „Nicht beantworten“ wählen.'); return; }
      antworten[q.question] = wert;
    }
  }
  $('wikiJobErr').textContent = '';
  try {
    await post(`/api/wiki/einarbeitung/${encodeURIComponent(d.id)}/antwort`, { frage_id: d.frage.id, antworten });
    $('wikiJobFrage').hidden = true;
    holeAuftrag();
  } catch (err) {
    $('wikiJobErr').textContent = err.message;
  }
}

/** Aktion auf den Auftrag im Dialog; ``body === null`` heisst Entfernen (DELETE). */
async function aktion(pfad, body = {}) {
  if (!offen) return null;
  $('wikiJobErr').textContent = '';
  const url = `/api/wiki/einarbeitung/${encodeURIComponent(offen)}${pfad}`;
  try {
    const r = body === null ? await api(url, { method: 'DELETE' }) : await post(url, body);
    hole();
    if (body !== null) holeAuftrag();
    return r;
  } catch (err) {
    $('wikiJobErr').textContent = err.message;
    return null;
  }
}

// --- Verdrahtung ------------------------------------------------------------------------------

document.addEventListener('click', (e) => {
  const auftrag = e.target.closest('[data-auftrag]');
  if (auftrag) { oeffneAuftrag(auftrag.dataset.auftrag); return; }
  const neu = e.target.closest('[data-einarbeiten]');
  if (neu) {
    const karteEl = neu.closest('[data-einarbeitung-sitzung]');
    if (karteEl) { neu.disabled = true; einarbeiten(karteEl.dataset.einarbeitungSitzung).finally(() => { neu.disabled = false; }); }
  }
});
$('wikiJobsErlauben').onclick = mitteilungenErfragen;
$('wikiJobClose').onclick = schliesse;
$('wikiJobDlg').addEventListener('close', () => { if (dlgPoller) dlgPoller.stop(); dlgPoller = null; offen = null; });
$('wikiJobFrage').addEventListener('click', (e) => {
  if (e.target.closest('#wikiJobAnswer')) sendeAntwort(false);
  else if (e.target.closest('#wikiJobSkip')) sendeAntwort(true);
});
$('wikiJobSend').onsubmit = async (e) => {
  e.preventDefault();
  const text = $('wikiJobText').value.trim();
  if (!text) return;
  $('wikiJobSendBtn').disabled = true;
  if (await aktion('/nachricht', { text })) $('wikiJobText').value = '';
  $('wikiJobSendBtn').disabled = false;
};
$('wikiJobCancel').onclick = () => aktion('/abbrechen');
$('wikiJobRetry').onclick = () => aktion('/wiederholen');
$('wikiJobRemove').onclick = async () => { if (await aktion('', null)) schliesse(); };
$('wikiJobSeite').onclick = () => {
  if (dlgAuftrag && dlgAuftrag.quellseite) post('/api/oeffnen', { pfad: dlgAuftrag.quellseite }).catch((err) => toast(err.message, 'fehler'));
};
