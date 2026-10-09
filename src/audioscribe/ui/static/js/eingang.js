// Aufnahmen ohne Projekt ("Sofort aufnehmen"): einem vorhandenen Projekt zuordnen oder dafuer
// ein neues anlegen. Die Sitzung wird in den Sitzungsordner des Projekts verschoben; danach ist
// das Projekt offen und die Nachbereitung waehlt die Sitzung vor.

import { $, S, post, esc, icon, basename, dirname, toast } from './kern.js';
import { go, setKontext } from './kontext.js';
import { pickFolder } from './dialoge.js';

let sitzung = null;   // Ordner der Aufnahme, die der Dialog gerade zuordnet

/** Sitzung ins Projekt verschieben, Projekt oeffnen, Nachbereitung mit der Sitzung zeigen. */
export async function ordneZu(ordner, projektPfad) {
  const k = await post('/api/eingang/zuordnen', { sitzung: ordner, projekt: projektPfad });
  S.zuordnen = null;
  setKontext(k);
  toast(`Aufnahme ins Projekt „${k.projekt.name}“ verschoben`);
  S.vorwahl = k.ziel;
  go('#/projekt/nachbereitung');
}

/** Dialog: zuletzt geoeffnete Projekte, anderes Projekt waehlen oder neues anlegen. */
export function zuordnenDialog(ordner, titel = '') {
  sitzung = ordner;
  $('zuordnenErr').textContent = '';
  $('zuordnenInfo').textContent = `„${titel || basename(ordner)}“ wandert in den Sitzungsordner des gewählten Projekts.`;
  const liste = ((S.kontext && S.kontext.zuletzt) || []).filter((z) => z.vorhanden);
  $('zuordnenListe').innerHTML = liste.length
    ? liste.map((z) => `
      <div class="recent">
        ${icon('book')}
        <button class="open" type="button" data-projekt="${esc(z.pfad)}">
          <span>${esc(z.name || z.pfad)}</span><small title="${esc(z.pfad)}">${esc(z.pfad)}</small>
        </button>
      </div>`).join('')
    : '<p class="hint">Noch keine Projekte geöffnet – wähle einen Projektordner oder lege ein neues Projekt an.</p>';
  $('zuordnenDlg').showModal();
}

async function waehle(projektPfad) {
  $('zuordnenErr').textContent = '';
  try {
    await ordneZu(sitzung, projektPfad);
    $('zuordnenDlg').close();
  } catch (err) {
    $('zuordnenErr').textContent = err.message;
  }
}

$('zuordnenListe').addEventListener('click', (e) => {
  const b = e.target.closest('[data-projekt]');
  if (b) waehle(b.dataset.projekt);
});
$('zuordnenAnderes').onclick = async () => {
  const z = S.kontext && S.kontext.zuletzt[0];
  const pfad = await pickFolder({ title: 'Projekt wählen – Projektordner', ok: 'In dieses Projekt verschieben',
    start: (z && dirname(z.pfad)) || (S.kontext.neu && S.kontext.neu.speicherort) || '' });
  // pickFolder schliesst den eigenen Dialog; unserer bleibt offen fuer Fehlermeldungen.
  if (pfad) waehle(pfad);
};
$('zuordnenNeu').onclick = async () => {
  $('zuordnenErr').textContent = '';
  try {
    // Der Assistent gehoert zur Startseite - aus "Sofort aufnehmen" heraus erst dorthin wechseln.
    if (S.kontext.modus !== 'start') setKontext(await post('/api/kontext', { modus: 'start' }));
  } catch (err) {
    $('zuordnenErr').textContent = err.message;
    return;
  }
  S.zuordnen = sitzung;
  $('zuordnenDlg').close();
  go('#/neu');
};
$('zuordnenCancel').onclick = () => $('zuordnenDlg').close();
