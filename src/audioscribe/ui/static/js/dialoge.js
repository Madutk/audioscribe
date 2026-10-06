// Dialoge: Ordner- und Dateiauswahl (serverseitig geblaettert), Rueckfrage, Transkript-Vorschau.
// Native <dialog>-Elemente: Fokusfalle, Esc und Hintergrund kommen vom Browser.

import { $, S, api, esc, icon, empty, sep } from './kern.js';

// --- Ordner / Dateien waehlen ------------------------------------------------------------

let pick = null;   // {files, resolve, path, chosen:Set}

/**
 * Ordner waehlen. Loest mit dem Pfad auf oder mit null (abgebrochen).
 * Ein Browser kennt keinen Ordner-Dialog, der einen Pfad liefert - geblaettert wird im Server.
 */
export function pickFolder({ title = 'Ordner wählen', start = '', ok = 'Diesen Ordner wählen' } = {}) {
  return openPick({ title, start, ok, files: false });
}

/** Mediendateien eines Ordners waehlen. Loest mit {dir, names} auf oder mit null. */
export function pickFiles({ title = 'Aufnahme wählen', start = '' } = {}) {
  return openPick({ title, start, ok: 'Auswahl übernehmen', files: true });
}

function openPick({ title, start, ok, files }) {
  if (pick) closePick(null);
  $('dlgTitle').textContent = title;
  $('dlgOkLabel').textContent = ok;
  const links = (S.defaults && S.defaults.quick_links) || [];
  $('dlgLinks').innerHTML = links.map((l) => `<a data-path="${esc(l.path)}" href="#" role="button">${esc(l.label)}</a>`).join('');
  $('pickDlg').showModal();
  return new Promise((resolve) => {
    pick = { files, resolve, path: '', chosen: new Set() };
    showDir(start);
  });
}

function closePick(result) {
  const p = pick;
  pick = null;
  if ($('pickDlg').open) $('pickDlg').close();
  if (p) p.resolve(result);
}

async function showDir(path) {
  if (!pick) return;
  try {
    const data = await api(`/api/browse?path=${encodeURIComponent(path || '')}${pick.files ? '&files=1' : ''}`);
    if (!pick) return;
    if (data.path !== pick.path) pick.chosen.clear();
    pick.path = data.path;
    const s = sep();
    $('dlgCrumbs').innerHTML = data.crumbs
      .map((c) => `<a data-path="${esc(c.path)}" href="#" role="button">${esc(c.name)}</a>`).join(`<span>${s}</span>`);
    const up = data.parent ? `<div data-path="${esc(data.parent)}" tabindex="0" role="button">${icon('arrow-up')}..</div>` : '';
    const dirs = data.dirs.map((d) => `<div data-path="${esc(d.path)}" tabindex="0" role="button">${icon('folder')}${esc(d.name)}</div>`).join('');
    let files = '';
    if (pick.files) {
      files = data.files.length
        ? `<div class="group">Aufnahmen in diesem Ordner</div>` + data.files.map((f) =>
          `<div class="file"><label><input type="checkbox" value="${esc(f.name)}" ${pick.chosen.has(f.name) ? 'checked' : ''} />`
          + `${icon('film')}<span>${esc(f.name)}</span><span class="size">${f.mb} MB</span></label></div>`).join('')
        : `<div class="group">Keine Audio- oder Videodateien in diesem Ordner</div>`;
    }
    $('dlgList').innerHTML = up + (dirs || (pick.files ? '' : empty('folder', 'Keine Unterordner.'))) + files;
    updatePickInfo(data);
  } catch (err) {
    $('dlgInfo').textContent = err.message;
  }
}

function updatePickInfo(data) {
  if (!pick) return;
  if (pick.files) {
    const n = pick.chosen.size;
    $('dlgInfo').textContent = n ? `${n} Datei${n === 1 ? '' : 'en'} gewählt – ${pick.path}` : `${pick.path} – Datei ankreuzen`;
    $('dlgOk').disabled = n === 0;
  } else {
    $('dlgInfo').textContent = data ? `${data.path} – ${data.media_count} Medien-Datei(en)` : pick.path;
    $('dlgOk').disabled = false;
  }
}

$('dlgOk').onclick = () => {
  if (!pick) return;
  closePick(pick.files ? { dir: pick.path, names: [...pick.chosen] } : pick.path);
};
$('dlgCancel').onclick = () => closePick(null);
$('pickDlg').addEventListener('close', () => closePick(null));          // Esc
$('pickDlg').addEventListener('click', (e) => { if (e.target === $('pickDlg')) closePick(null); });   // Hintergrund
for (const id of ['dlgList', 'dlgCrumbs', 'dlgLinks']) {
  $(id).addEventListener('click', (e) => {
    const el = e.target.closest('[data-path]');
    if (!el) return;
    e.preventDefault();
    showDir(el.dataset.path);
  });
}
$('dlgList').addEventListener('keydown', (e) => {
  if (e.key !== 'Enter' && e.key !== ' ') return;
  const el = e.target.closest('[data-path]');
  if (el) { e.preventDefault(); showDir(el.dataset.path); }
});
$('dlgList').addEventListener('change', (e) => {
  if (!pick || e.target.type !== 'checkbox') return;
  if (e.target.checked) pick.chosen.add(e.target.value);
  else pick.chosen.delete(e.target.value);
  updatePickInfo(null);
});

// --- Rueckfrage ---------------------------------------------------------------------------

let confirmResolve = null;

/** Modale Rueckfrage; loest mit true (bestaetigt) oder false (abgebrochen) auf. */
export function askConfirm({ title, text, ok }) {
  $('confirmTitle').lastElementChild.textContent = title;
  $('confirmText').textContent = text;
  $('confirmOk').textContent = ok;
  $('confirm').showModal();
  $('confirmCancel').focus();  // Enter allein loest also nichts Unwiderrufliches aus
  return new Promise((resolve) => { confirmResolve = resolve; });
}

function closeConfirm(answer) {
  const resolve = confirmResolve;
  confirmResolve = null;
  if ($('confirm').open) $('confirm').close();
  if (resolve) resolve(answer);
}

$('confirmOk').onclick = () => closeConfirm(true);
$('confirmCancel').onclick = () => closeConfirm(false);
$('confirm').addEventListener('close', () => closeConfirm(false));
$('confirm').addEventListener('click', (e) => { if (e.target === $('confirm')) closeConfirm(false); });

// --- Transkript-Vorschau ---------------------------------------------------------------------

/** Fertiges Transkript eines Ergebnisordners zeigen (annotierte Fassung bevorzugt). */
export async function showTranscript(ordner, titel) {
  $('previewTitle').querySelector('span').textContent = titel || 'Transkript';
  $('previewPath').textContent = '';
  $('previewText').textContent = 'Lädt …';
  $('previewDlg').showModal();
  try {
    const data = await api('/api/transkript?pfad=' + encodeURIComponent(ordner));
    $('previewPath').textContent = data.datei + (data.gekuerzt ? ' – gekürzt angezeigt' : '');
    $('previewText').textContent = data.text;
  } catch (err) {
    $('previewText').textContent = err.message;
  }
}
$('previewClose').onclick = () => $('previewDlg').close();
$('previewDlg').addEventListener('click', (e) => { if (e.target === $('previewDlg')) $('previewDlg').close(); });
