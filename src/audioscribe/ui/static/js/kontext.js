// Kontext der Oberflaeche (PRD §21): Startseite, Projekt, Aufnahme ohne Projekt, einzelne Datei oder Demo.
// Der Server haelt den Kontext; hier wird er geholt, gewechselt und an die Ansichten gemeldet.

import { $, S, api, post, toast } from './kern.js';

/** Startadresse je Modus - dorthin fuehrt ein Kontextwechsel. */
export const HOME = { start: '#/', projekt: '#/projekt/live', datei: '#/datei', demo: '#/demo', aufnahme: '#/aufnahme' };

export function go(hash) {
  if (location.hash === hash) window.dispatchEvent(new HashChangeEvent('hashchange'));
  else location.hash = hash;
}

/** Neuen Kontext uebernehmen und allen Ansichten melden (sie leeren sich und laden neu). */
export function setKontext(k) {
  const vorher = S.kontext;
  S.kontext = k;
  const gewechselt = !vorher || vorher.modus !== k.modus
    || (vorher.projekt && vorher.projekt.wurzel) !== (k.projekt && k.projekt.wurzel);
  document.dispatchEvent(new CustomEvent('audioscribe:kontext', { detail: { gewechselt } }));
  return gewechselt;
}

export async function ladeKontext() {
  return setKontext(await api('/api/kontext'));
}

// /api/defaults startet beim ersten Aufruf eine Geraete-Probe (Sekunden). Die Startseite wartet
// darauf nicht; die Arbeitsansichten holen sich die Werte ueber dieses eine Versprechen.
let defaultsLaeuft = null;
export function ladeDefaults(neu = false) {
  if (neu || !defaultsLaeuft) {
    defaultsLaeuft = api('/api/defaults').then((d) => {
      S.defaults = d;
      S.folders.input_dir = d.input_dir || '';
      S.folders.output_dir = d.output_dir || '';
      S.folders.agent_output_dir = d.agent_output_dir || '';
      return d;
    });
    defaultsLaeuft.catch(() => { defaultsLaeuft = null; });
  }
  return defaultsLaeuft;
}

/** Zur Startseite bzw. in einen projektlosen Modus wechseln. Laeuft noch etwas, sagt der Server nein. */
export async function wechsle(modusNeu) {
  try {
    setKontext(await post('/api/kontext', { modus: modusNeu }));
    go(HOME[S.kontext.modus]);
    return true;
  } catch (err) {
    toast(err.message, 'fehler');
    return false;
  }
}

export async function oeffneProjekt(pfad) {
  setKontext(await post('/api/projekt/oeffnen', { pfad }));
  go(HOME.projekt);
}

$('ctxClose').onclick = () => wechsle('start');
