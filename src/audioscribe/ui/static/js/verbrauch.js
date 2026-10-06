// KI-Verbrauch im Kopf: Tokens und ungefaehrer Preis der KI-Aufrufe, die das Haus verlassen
// (Souffleur, KI-Analyse). Der Server zaehlt seit Programmstart; der Preis ist der Gegenwert zu
// API-Preisen, den der KI-Dienst selbst meldet - bei Abo-Anmeldung wird nichts abgerechnet.

import { $, api, esc, poller } from './kern.js';

const ZAHL = new Intl.NumberFormat('de-DE');
const KURZ = new Intl.NumberFormat('de-DE', { notation: 'compact', maximumFractionDigits: 1 });
const USD = new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'USD' });

/** Preis mit "≈"; leer, wenn der Dienst keinen genannt hat. */
export function preis(kosten) {
  if (kosten === null || kosten === undefined) return '';
  if (kosten > 0 && kosten < 0.01) return `< ${USD.format(0.01)}`;
  return `≈ ${USD.format(kosten)}`;
}

/** Eine Zeile, z. B. "182.340 Tokens · ≈ 1,24 $". */
export function verbrauchText(v) {
  const p = preis(v.kosten_usd);
  return `${ZAHL.format(v.tokens)} Tokens${p ? ` · ${p}` : ''}`;
}

function zeile(name, v, cls = '') {
  return `<tr class="${cls}"><th scope="row">${esc(name)}</th><td>${ZAHL.format(v.tokens)}</td>`
    + `<td>${esc(preis(v.kosten_usd) || '–')}</td></tr>`;
}

function render(d) {
  const g = d.gesamt;
  // Erst zeigen, wenn etwas verbraucht wurde - ohne KI-Aufruf bleibt der Kopf, wie er ist.
  $('kiVerbrauch').hidden = !g.tokens;
  if (!g.tokens) {
    if ($('kiVerbrauchInfo').matches(':popover-open')) $('kiVerbrauchInfo').hidePopover();
    return;
  }
  const p = preis(g.kosten_usd);
  $('kiVerbrauchTokens').textContent = `${KURZ.format(g.tokens)} Tokens`;
  $('kiVerbrauchPreis').textContent = p;
  $('kiVerbrauch').setAttribute('aria-label',
    `KI-Verbrauch seit Programmstart: ${ZAHL.format(g.tokens)} Tokens${p ? `, ${p}` : ''} – Einzelheiten anzeigen`);
  const s = d.quellen.souffleur.aktuell;
  const a = d.quellen.analyse.aktuell;
  $('kiVerbrauchZeilen').innerHTML =
    (s.tokens ? zeile(`Souffleur, diese Sitzung (${ZAHL.format(s.aufrufe)} ${s.aufrufe === 1 ? 'Aufruf' : 'Aufrufe'})`, s) : '')
    + (a.tokens ? zeile('KI-Analyse, dieser Lauf', a) : '')
    + zeile('Seit Programmstart', g, 'sum');
  $('kiVerbrauchTeile').textContent =
    `Eingabe ${ZAHL.format(g.eingabe)} · Ausgabe ${ZAHL.format(g.ausgabe)} · `
    + `Cache gelesen ${ZAHL.format(g.cache_lesen)} · Cache geschrieben ${ZAHL.format(g.cache_schreiben)}`;
}

async function hole() {
  try { render(await api('/api/verbrauch')); } catch (err) { /* Anzeige bleibt beim letzten Stand */ }
}

/** Laeuft unabhaengig von der Ansicht: der Verbrauch steht im Kopf jeder Seite. */
export function starteVerbrauch() {
  poller(hole, 5000).start();
}
