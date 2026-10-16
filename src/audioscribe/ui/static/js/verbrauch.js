// KI-Verbrauch im Kopf: Tokens und ungefaehrer Preis der KI-Aufrufe, die das Haus verlassen
// (Souffleur, KI-Analyse). Der Server zaehlt seit Programmstart; der Preis ist der Gegenwert zu
// API-Preisen, den der KI-Dienst selbst meldet - bei Abo-Anmeldung wird nichts abgerechnet.

import { $, api, esc, poller } from './kern.js';
import { tr, englisch } from './i18n.js';

const LOCALE = englisch ? 'en-US' : 'de-DE';
const ZAHL = new Intl.NumberFormat(LOCALE);
const KURZ = new Intl.NumberFormat(LOCALE, { notation: 'compact', maximumFractionDigits: 1 });
const USD = new Intl.NumberFormat(LOCALE, { style: 'currency', currency: 'USD' });

/** Preis mit "≈"; leer, wenn der Dienst keinen genannt hat. */
export function preis(kosten) {
  if (kosten === null || kosten === undefined) return '';
  if (kosten > 0 && kosten < 0.01) return `< ${USD.format(0.01)}`;
  return `≈ ${USD.format(kosten)}`;
}

/** Eine Zeile, z. B. "182.340 Tokens · ≈ 1,24 $". */
export function verbrauchText(v) {
  const p = preis(v.kosten_usd);
  return tr('{n} Tokens', { n: ZAHL.format(v.tokens) }) + (p ? ` · ${p}` : '');
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
  $('kiVerbrauchTokens').textContent = tr('{n} Tokens', { n: KURZ.format(g.tokens) });
  $('kiVerbrauchPreis').textContent = p;
  $('kiVerbrauch').setAttribute('aria-label',
    tr('KI-Verbrauch seit Programmstart: {verbrauch} – Einzelheiten anzeigen', { verbrauch: tr('{n} Tokens', { n: ZAHL.format(g.tokens) }) + (p ? `, ${p}` : '') }));
  const s = d.quellen.souffleur.aktuell;
  const a = d.quellen.analyse.aktuell;
  $('kiVerbrauchZeilen').innerHTML =
    (s.tokens ? zeile(s.aufrufe === 1 ? tr('Souffleur, diese Sitzung (1 Aufruf)') : tr('Souffleur, diese Sitzung ({n} Aufrufe)', { n: ZAHL.format(s.aufrufe) }), s) : '')
    + (a.tokens ? zeile(tr('KI-Analyse, dieser Lauf'), a) : '')
    + zeile(tr('Seit Programmstart'), g, 'sum');
  $('kiVerbrauchTeile').textContent =
    tr('Eingabe {ein} · Ausgabe {aus} · Cache gelesen {gelesen} · Cache geschrieben {geschrieben}', {
      ein: ZAHL.format(g.eingabe), aus: ZAHL.format(g.ausgabe),
      gelesen: ZAHL.format(g.cache_lesen), geschrieben: ZAHL.format(g.cache_schreiben),
    });
}

async function hole() {
  try { render(await api('/api/verbrauch')); } catch (err) { /* Anzeige bleibt beim letzten Stand */ }
}

/** Laeuft unabhaengig von der Ansicht: der Verbrauch steht im Kopf jeder Seite. */
export function starteVerbrauch() {
  poller(hole, 5000).start();
}
