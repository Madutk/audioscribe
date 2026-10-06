// Einstieg der Oberflaeche: Kontext holen, Adresse (#/…) auf eine Ansicht abbilden, Kopf zeichnen.
// Jede Ansicht lebt in ihrem Modul und fragt den Server nur ab, solange sie sichtbar ist.

import { $, S, post, modus, projekt, reducedMotion, wireLogs, toast } from './kern.js';
import { HOME, ladeKontext, ladeDefaults } from './kontext.js';
import { enterStart, renderStart, enterNeu } from './start.js';
import { enterEinstellungen, enterProjekt, zeigeProjekt } from './einstellungen.js';
import { enterDatei, leaveDatei, resetDatei } from './datei.js';
import { enterAna, leaveAna, resetAna } from './nachbereitung.js';
import { enterLive, leaveLive, leereLive, aktualisiereLiveSprache } from './live.js';
import { loadWikiStatus } from './wiki.js';
import { starteVerbrauch } from './verbrauch.js';

// Adresse -> Ansicht. `modus` sagt, in welchem Kontext die Adresse gilt (null = ueberall).
const ROUTES = {
  '#/': { view: 'start', modus: 'start', hint: '' },
  '#/neu': { view: 'neu', modus: 'start', hint: '' },
  '#/projekt/live': { view: 'live', modus: 'projekt',
    hint: 'Monitor, System-Audio und Mikrofon mitschneiden – Transkript, Screenshots und Souffleur-Hinweise entstehen live' },
  '#/projekt/nachbereitung': { view: 'ana', modus: 'projekt',
    hint: 'Sitzungen dieses Projekts ins Wiki speichern oder von der KI auswerten lassen' },
  '#/projekt/einstellungen': { view: 'projekt', modus: 'projekt',
    hint: 'Ordner, Wiki-Ablage, KI und Sprache dieses Projekts' },
  '#/datei': { view: 'datei', modus: 'datei', hint: 'Aufnahme wählen, Speicherort festlegen, transkribieren' },
  '#/datei/ki': { view: 'ana', modus: 'datei', hint: 'Die KI wertet Transkript und Standbilder aus und legt Dokumente im Ausgabeordner ab' },
  '#/demo': { view: 'live', modus: 'demo', hint: 'Vorführung: ein aufgezeichnetes Meeting läuft ab – nichts wird aufgenommen oder gespeichert' },
  '#/einstellungen': { view: 'einstellungen', modus: null, hint: 'Globale Einstellungen – gelten für alle Projekte, die nichts Eigenes festlegen' },
};

const VIEWS = {
  start: { el: 'viewStart', enter: enterStart },
  neu: { el: 'viewNeu', enter: enterNeu },
  live: { el: 'tabLive', enter: enterLive, leave: leaveLive },
  ana: { el: 'tabAna', enter: enterAna, leave: leaveAna },
  datei: { el: 'tabTrans', enter: enterDatei, leave: leaveDatei },
  einstellungen: { el: 'tabSet', enter: enterEinstellungen },
  projekt: { el: 'tabProj', enter: enterProjekt },
};

let aktiv = null;   // Name der sichtbaren Ansicht

// --- Design (hell/dunkel) ---------------------------------------------------------------
// Serverseitig gemerkt wie alle anderen Einstellungen; 'system' folgt dem Betriebssystem.
const THEMES = ['system', 'light', 'dark'];
const THEME_LABEL = { system: 'System', light: 'Hell', dark: 'Dunkel' };
function applyTheme(theme) {
  if (theme === 'system') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  $('themeToggle').dataset.theme = theme;
  $('themeToggle').setAttribute('aria-label', `Design: ${THEME_LABEL[theme]} – klicken zum Wechseln`);
}
applyTheme(THEMES.includes(document.documentElement.dataset.theme) ? document.documentElement.dataset.theme : 'system');
$('themeToggle').onclick = () => {
  const next = THEMES[(THEMES.indexOf($('themeToggle').dataset.theme) + 1) % THEMES.length];
  applyTheme(next);
  post('/api/state', { theme: next }).catch(() => {});
};

// --- Kopf -------------------------------------------------------------------------------

const CTX = {
  projekt: () => ({ name: projekt().name, icon: 'book', close: 'Projekt schließen' }),
  datei: () => ({ name: 'Aufnahme transkribieren', icon: 'film', close: 'Zur Startseite' }),
  demo: () => ({ name: 'Demo', icon: 'play-circle', close: 'Demo beenden' }),
};

function renderShell() {
  const m = modus();
  document.body.dataset.modus = m;
  const ctx = CTX[m] ? CTX[m]() : null;
  $('ctx').hidden = !ctx;
  if (ctx) {
    $('ctxName').textContent = ctx.name;
    $('ctxName').title = m === 'projekt' ? projekt().wurzel : '';
    $('ctxIcon').setAttribute('href', '#i-' + ctx.icon);
    $('ctxCloseLabel').textContent = ctx.close;
  }
  document.title = m === 'projekt' ? `${projekt().name} – AudioScribe` : 'AudioScribe';
}

function markNav(hash) {
  for (const a of document.querySelectorAll('#nav a, #openSettings')) {
    if (a.getAttribute('href') === hash) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  }
}

// --- Router -----------------------------------------------------------------------------

async function show() {
  if (!S.kontext) return;
  const hash = location.hash || '#/';
  const route = ROUTES[hash];
  // Unbekannte Adresse oder eine, die nicht zum Kontext passt: der Server bestimmt, wo wir sind.
  if (!route || (route.modus && route.modus !== modus())) {
    history.replaceState(null, '', HOME[modus()]);
    return show();
  }
  const wechsel = () => {
    if (aktiv && aktiv !== route.view && VIEWS[aktiv].leave) VIEWS[aktiv].leave();
    for (const [name, v] of Object.entries(VIEWS)) $(v.el).hidden = name !== route.view;
    document.body.dataset.view = route.view;
    $('tabMeta').textContent = route.hint;
    markNav(hash);
    aktiv = route.view;
  };
  const neu = aktiv !== route.view;
  if (neu && document.startViewTransition && !reducedMotion()) document.startViewTransition(wechsel);
  else wechsel();
  if (neu) window.scrollTo(0, 0);
  try {
    await VIEWS[route.view].enter();
  } catch (err) {
    toast(err.message, 'fehler');
  }
}

window.addEventListener('hashchange', show);

// Kontext gewechselt oder aktualisiert: Kopf neu zeichnen; nach einem Wechsel beginnen die
// Arbeitsansichten leer und holen Ordner, Vorgaben und Wiki-Zustand des neuen Kontexts.
document.addEventListener('audioscribe:kontext', (e) => {
  renderShell();
  if (e.detail.gewechselt) {
    leaveLive(); leaveAna(); leaveDatei();
    leereLive(); resetAna(); resetDatei();
    S.wikiStatus = null;
    aktiv = null;
    // Ein Ordner aus der Projektdatei war hier nicht brauchbar - sagen, was stattdessen gilt.
    if (projekt() && projekt().hinweis) toast(projekt().hinweis, 'fehler');
  }
  const defaults = ladeDefaults(true);
  if (!e.detail.gewechselt) defaults.then(aktualisiereLiveSprache);
  defaults.catch(() => {});
  if (projekt()) loadWikiStatus();
  if (aktiv === 'start') renderStart();
  if (aktiv === 'projekt') zeigeProjekt();
});

// Server wieder da (z. B. nach einem Neustart): Kontext neu holen - er beginnt auf der Startseite.
document.addEventListener('audioscribe:verbunden', () => {
  ladeKontext().then(show).catch(() => {});
});

async function boot() {
  wireLogs();
  try {
    await ladeKontext();
  } catch (err) {
    $('launchErr').textContent = err.message;
    // Ohne Server keine Oberflaeche - alle paar Sekunden erneut versuchen.
    setTimeout(boot, 3000);
    return;
  }
  await show();
  starteVerbrauch();
}

boot();
