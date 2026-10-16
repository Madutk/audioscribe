// Sprache der Oberflaeche (Einstellungen -> Sprache). Die deutschen Texte im Code sind die
// Quelle; tr('Text') liefert bei englischer Oberflaeche die Uebersetzung aus en/*.js.
// Platzhalter in geschweiften Klammern: tr('{n} Meetings', { n: 3 }).
// Die Sprache setzt der Server ins <html lang="…"> (ui/server.py: inject_theme).

import EN from './en/index.js';

export const sprache = document.documentElement.lang === 'en' ? 'en' : 'de';
export const englisch = sprache === 'en';

export function tr(text, werte) {
  let s = englisch && Object.prototype.hasOwnProperty.call(EN, text) ? EN[text] : text;
  if (werte) s = s.replace(/\{(\w+)\}/g, (m, k) => (k in werte ? String(werte[k]) : m));
  return s;
}

const ATTRIBUTE = ['title', 'aria-label', 'placeholder', 'alt'];
const OHNE = new Set(['SCRIPT', 'STYLE', 'svg', 'PRE', 'CODE']);
const norm = (s) => s.replace(/\s+/g, ' ').trim();

/** Statischen Text der Seite uebersetzen: Elemente mit data-t als Ganzes (innerHTML ist der
 *  Schluessel), sonst jeden Textknoten und die Attribute title, aria-label, placeholder, alt. */
export function uebersetzeDom(wurzel = document.body) {
  if (!englisch) return;
  const hat = (k) => Object.prototype.hasOwnProperty.call(EN, k);
  for (const el of wurzel.querySelectorAll('[data-t]')) {
    const k = norm(el.innerHTML);
    if (hat(k)) el.innerHTML = EN[k];
  }
  const gang = document.createTreeWalker(wurzel, NodeFilter.SHOW_TEXT, {
    acceptNode(n) {
      for (let p = n.parentNode; p; p = p.parentNode) {
        if (OHNE.has(p.nodeName) || (p.hasAttribute && (p.hasAttribute('data-t') || p.getAttribute('translate') === 'no'))) {
          return NodeFilter.FILTER_REJECT;
        }
      }
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const knoten = [];
  while (gang.nextNode()) knoten.push(gang.currentNode);
  for (const n of knoten) {
    const v = n.nodeValue;
    const k = norm(v);
    // Fuehrende und folgende Leerzeichen bleiben - sie trennen den Text vom Nachbarelement.
    if (k && hat(k)) n.nodeValue = (/^\s/.test(v) ? ' ' : '') + EN[k] + (/\s$/.test(v) ? ' ' : '');
  }
  for (const el of wurzel.querySelectorAll(ATTRIBUTE.map((a) => `[${a}]`).join(','))) {
    for (const a of ATTRIBUTE) {
      const v = el.getAttribute(a);
      if (v && hat(norm(v))) el.setAttribute(a, EN[norm(v)]);
    }
  }
  for (const tpl of wurzel.querySelectorAll('template')) uebersetzeDom(tpl.content);
  if (wurzel === document.body) document.title = tr(document.title);
}
