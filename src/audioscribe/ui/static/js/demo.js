// Demo (PRD §21, Wegwerfware): zeigt, was vor dem abgespielten Meeting war. Die Meetings, die
// schon im Demo-Wiki stehen, erscheinen als Zeitstrahl in der Demo-Leiste; ein Hinweis nennt das
// Meeting, aus dem sein Beleg stammt, statt der Datei im Wiki.

import { $, api, esc, icon, modus, reducedMotion } from './kern.js';

let vor = null;     // Antwort von /api/demo/vorgeschichte: meetings, heute, wiki, seiten
let laedt = null;   // laufende bzw. erledigte Abfrage - die Vorgeschichte aendert sich nicht

/** "2026-09-08" -> "08.09." */
const tag = (iso) => { const m = /^\d{4}-(\d\d)-(\d\d)/.exec(iso || ''); return m ? `${m[2]}.${m[1]}.` : ''; };
const mehrzahl = (n, eins, viele) => `${n} ${n === 1 ? eins : viele}`;

/** Erst mit geladener Vorgeschichte gilt die Demo-Darstellung der Hinweise. */
export const demoAktiv = () => !!vor && modus() === 'demo';

function zeichne() {
  const n = vor.meetings.length;
  const box = $('demoZeit');
  box.style.setProperty('--n', n);
  const punkt = (cls, i, q, nr, wann, thema) =>
    `<li${cls ? ` class="${cls}"` : ''}${q ? ` data-q="${esc(q)}"` : ''} style="--i:${i}">`
    + `<span class="nr">${nr}</span><b>${esc(wann)}</b><span class="thema">${esc(thema)}</span></li>`;
  box.innerHTML = `<ol aria-label="${n} Meetings stehen im Wiki, heute läuft Meeting ${vor.heute.nr}">`
    + vor.meetings.map((m, i) => punkt('', i, m.id, m.nr, tag(m.datum), m.titel)).join('')
    + punkt('heute', n + 1, '', vor.heute.nr, 'heute', vor.heute.titel) + '</ol>'
    + `<div class="im-wiki" style="--i:${n}">${icon('book')}im Wiki: `
    + `${mehrzahl(vor.wiki.anforderungen, 'Anforderung', 'Anforderungen')} · `
    + `${mehrzahl(vor.wiki.offene_punkte, 'offener Punkt', 'offene Punkte')}</div>`;
}

/** Vorgeschichte einmal holen und den Zeitstrahl zeichnen; ohne sie bleibt die Demo wie bisher. */
export function ladeVorgeschichte() {
  if (!laedt) {
    laedt = api('/api/demo/vorgeschichte')
      .then((v) => { vor = v; zeichne(); })
      .catch(() => { laedt = null; });
  }
  return laedt;
}

/** Aus welchem Meeting stammt der Beleg eines Hinweises? {id, nr, datum} oder null. */
export function herkunft(h) {
  const f = h.fundstellen && h.fundstellen[0];
  if (!demoAktiv() || !f || h.ohne_befund) return null;
  // Der Auszug nennt die Quelle hinter jeder Aussage ("… dauert. [Q-001 · 00:01:14]") - die
  // naechste nach dem Zitat gilt; sonst die erste Quelle der Seite.
  const auszug = f.auszug || '';
  const ab = Math.max(0, auszug.indexOf(h.wiki_zitat || ''));
  const m = /\[(Q-\d+)/.exec(auszug.slice(ab)) || /\[(Q-\d+)/.exec(auszug);
  const id = m ? m[1] : (vor.seiten[f.datei] || [])[0];
  const mt = vor.meetings.find((x) => x.id === id);
  return mt ? { id: mt.id, nr: mt.nr, datum: tag(mt.datum) } : null;
}

function neuStarten(el, cls) {
  el.classList.remove(cls);
  void el.offsetWidth;  // Animation neu starten
  el.classList.add(cls);
}

/** Das Meeting im Zeitstrahl kurz hervorheben - von dort kommt der Beleg des neuen Hinweises. */
export function blinke(id) {
  const li = $('demoZeit').querySelector(`li[data-q="${CSS.escape(id)}"]`);
  if (li && !reducedMotion()) neuStarten(li, 'blink');
}

/** Beim Start: die Meetings erscheinen nacheinander, dann das Wiki, dann das heutige. */
export function vorspann() {
  if (vor && !reducedMotion()) neuStarten($('demoZeit'), 'vorspann');
}

/** Zustand am Zeitstrahl (das heutige Meeting pulsiert) und nach dem Ende die Bilanz in einer Zeile. */
export function demoZustand(s, z) {
  $('demoZeit').classList.toggle('laeuft', !!s.running && !s.pausiert);
  const fertig = !!vor && s.phase === 'beendet' && z.widerspruch + z.beantwortet + z.neu > 0;
  const box = $('demoSchluss');
  const key = fertig ? JSON.stringify(z) : '';
  if (box.dataset.key === key) return;
  box.dataset.key = key;
  box.hidden = !fertig;
  if (!fertig) { box.innerHTML = ''; return; }
  const chip = (n, cls, ic, text) => (n ? `<span class="mark ${cls}">${icon(ic)}${esc(text)}</span>` : '');
  box.innerHTML = `Meeting ${vor.heute.nr} gegen ${mehrzahl(vor.meetings.length, 'Meeting', 'Meetings')} geprüft:`
    + chip(z.widerspruch, 'widerspruch', 'zap', mehrzahl(z.widerspruch, 'Widerspruch', 'Widersprüche'))
    + chip(z.beantwortet, 'frage', 'help-circle', `${z.beantwortet} aus dem Wiki beantwortet`)
    + chip(z.neu, 'offen', 'circle-dashed', `${z.neu} neu`);
}
