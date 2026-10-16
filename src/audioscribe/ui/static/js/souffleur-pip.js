// Souffleur auskoppeln: die Karte wandert in ein kleines Fenster, das ueber allen anderen liegt
// (Document Picture-in-Picture, Chrome/Edge). Dieselbe Karte, derselbe JS-Kontext - Hinweise,
// Essenz und Schalter laufen ohne Umbau weiter. Schliessen holt sie in die rechte Spalte zurueck.

import { $, api, hms, setPipDoc } from './kern.js';
import { setSouffleurHidden } from './souffleur.js';
import { tr } from './i18n.js';

export const pipMoeglich = 'documentPictureInPicture' in window;

let pipWin = null;
let stopScharf = null;   // Timer der Rueckfrage "Wirklich stoppen?"
let stopText = tr('Stoppen'); // Beschriftung laut letztem Poll
let themaAus = null;      // beendet den Abgleich des Farbschemas
const systemDunkel = window.matchMedia('(prefers-color-scheme: dark)');

/** 'light' oder 'dark', wie das Hauptfenster gerade aussieht - auch bei der Einstellung "System". */
function sichtbaresThema() {
  const t = document.documentElement.dataset.theme;
  if (t === 'light' || t === 'dark') return t;
  return systemDunkel.matches ? 'dark' : 'light';
}

export const istAusgekoppelt = () => pipWin !== null;

/** Muss aus einem Klick oder Tastendruck kommen - der Browser verlangt eine Nutzeraktion. */
export async function auskoppeln() {
  if (!pipMoeglich || pipWin) return;
  const karte = $('souffleur');
  const win = await documentPictureInPicture.requestWindow({ width: 360, height: 520 });
  const doc = win.document;
  doc.title = 'Souffleur';
  // Stil, Farbschema und Icon-Sprite des Hauptfensters mitnehmen.
  for (const el of document.head.querySelectorAll('link[rel="stylesheet"], style')) {
    const kopie = el.cloneNode(true);
    if (kopie.href) kopie.href = el.href;  // absolute Adresse, das Fenster hat keine eigene
    doc.head.append(kopie);
  }
  // Das Mini-Fenster wertet "System" anders aus als das Hauptfenster (in Chrome oft dunkel) -
  // daher die Seite festschreiben, die das Hauptfenster tatsaechlich zeigt.
  const themaUebernehmen = () => { doc.documentElement.dataset.theme = sichtbaresThema(); };
  themaUebernehmen();
  const beobachter = new MutationObserver(themaUebernehmen);
  beobachter.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  systemDunkel.addEventListener('change', themaUebernehmen);
  themaAus = () => { beobachter.disconnect(); systemDunkel.removeEventListener('change', themaUebernehmen); };
  doc.body.dataset.modus = document.body.dataset.modus || '';
  doc.body.classList.add('pip');
  const sprite = document.querySelector('body > svg[aria-hidden="true"]');
  if (sprite) doc.body.append(sprite.cloneNode(true));

  setSouffleurHidden(false);
  setPipDoc(doc);
  doc.body.append(karte);
  pipWin = win;
  $('souffleurPopped').hidden = false;
  $('liveAside').classList.add('popped');
  doc.addEventListener('keydown', tasten);
  win.addEventListener('pagehide', zurueck, { once: true });
}

/** Mini-Fenster schliessen; das Zurueckholen erledigt dessen pagehide. */
export function einkoppeln() {
  if (pipWin) pipWin.close();
}

function zurueck() {
  const karte = $('souffleur');
  if (karte) $('liveAside').insertBefore(document.adoptNode(karte), $('liveShots'));
  setPipDoc(null);
  pipWin = null;
  if (themaAus) { themaAus(); themaAus = null; }
  entschaerfe();
  $('souffleurPopped').hidden = true;
  $('liveAside').classList.remove('popped');
  document.dispatchEvent(new CustomEvent('audioscribe:souffleur-zurueck'));
}

export const umschalten = () => (pipWin ? einkoppeln() : auskoppeln());

function tasten(e) {
  if (e.altKey && !e.ctrlKey && !e.metaKey && e.code === 'KeyP') { e.preventDefault(); einkoppeln(); }
}

// --- Aufnahmeleiste im Mini-Fenster ---------------------------------------------------------

/** Aus dem Live-Poll: Laufzeit, Zustand, Start- und Stopp-Knopf wie in der Hauptansicht. */
export function pipStatus(s, phaseText) {
  const running = !!s.running;
  $('pipElapsed').textContent = s.stats ? hms(s.stats.elapsed) : '–';
  $('pipPhase').textContent = phaseText;
  $('pipDot').classList.toggle('an', running && !s.pausiert);
  // Start wie im Hauptfenster (dort steht im Testmodus "Abspielen starten"): die Sitzung
  // nimmt die Einstellungen der Live-Ansicht - so laesst sich das Meeting vorbereiten,
  // waehrend nur das kleine Fenster offen ist.
  $('pipStart').hidden = running;
  if (running) $('pipStart').disabled = false;
  $('pipStartLabel').textContent = $('liveStartLabel').textContent;
  $('pipStartIcon').setAttribute('href', $('liveStartIcon').getAttribute('href'));
  $('pipStop').hidden = !running;
  if (!running) entschaerfe();
  stopText = s.phase === 'nachschaerfen' ? tr('Nachschärfen abbrechen') : s.stopping ? tr('Sofort abbrechen') : tr('Stoppen');
  if (!stopScharf) $('pipStopLabel').textContent = stopText;
}

function entschaerfe() {
  if (stopScharf) { clearTimeout(stopScharf); stopScharf = null; }
  $('pipStop').classList.remove('scharf');
  $('pipStopLabel').textContent = stopText;
}

// Im kleinen Fenster ist ein Fehlklick schnell passiert: der erste Klick fragt nur nach.
$('pipStop').onclick = () => {
  if (!stopScharf) {
    $('pipStopLabel').textContent = tr('Wirklich stoppen?');
    $('pipStop').classList.add('scharf');
    stopScharf = setTimeout(entschaerfe, 3000);
    return;
  }
  entschaerfe();
  api('/api/live/stop', { method: 'POST' }).catch(() => {});
};
// Starten uebernimmt live.js (dort liegen Einstellungen und Startlogik); bis zum naechsten
// Poll bleibt der Knopf gesperrt, damit ein Doppelklick nicht zwei Sitzungen anstoesst.
$('pipStart').onclick = () => {
  $('pipStart').disabled = true;
  document.dispatchEvent(new CustomEvent('audioscribe:live-start'));
};
$('pipBack').onclick = einkoppeln;
$('souffleurUnpop').onclick = einkoppeln;
$('souffleurPop').hidden = !pipMoeglich;
$('souffleurPop').onclick = () => auskoppeln().catch(() => {});
