// Wiki des Projekts: Zustandsanzeige (Einstellungen, Live, Assistent) und der Dialog
// "Ins Wiki speichern" (PRD §21) - gemeinsam fuer Live-Ansicht und Nachbereitung.

import { $, S, api, post, esc, projekt, sep, trimSep, toast, basename } from './kern.js';
import { setKontext } from './kontext.js';

/** "JJJJ-MM-TT HH:MM" -> "HH:MM" (die Uhrzeit reicht; das Datum steht im Tooltip). */
const uhrzeit = (s) => (/\d\d:\d\d$/.test(s || '') ? s.slice(-5) : (s || ''));
const changeLink = () => ' <a class="goto" href="#/projekt/einstellungen">ändern</a>';

/**
 * Ein Bauteil fuer alle Orte: div.wiki-state.{none|ok|fail}. Live (compact) zeigt eine Zeile
 * mit "ändern"-Link, Einstellungen und Assistent die lange Fassung mit Pfad und Glossar-Zeile.
 */
export function renderWikiState(box, w, compact) {
  if (!box) return;
  const key = JSON.stringify([w, compact]);
  if (box.dataset.key === key) return;  // Poll alle 500 ms - nur bei Aenderung neu zeichnen
  box.dataset.key = key;
  const z = (w && w.zustand) || 'keins';
  const glossar = w && w.glossar_eintraege
    ? `Glossar: ${w.glossar_eintraege} Einträge${!compact && w.glossar_datei ? ` (<code>${esc(w.glossar_datei)}</code>)` : ''}`
    : 'Glossar: keins im Wiki';
  const warn = !compact && w && w.warnungen && w.warnungen.length ? `<br>${esc(w.warnungen.join(' · '))}` : '';
  const link = compact && projekt() && !projekt().demo ? changeLink() : '';
  let cls = 'none', badge = '<span class="badge">kein Wiki</span>', body;
  if (z === 'ok') {
    cls = 'ok'; badge = '<span class="badge ok">Wiki</span>';
    const gelesen = w.gelesen ? `, gelesen <span title="${esc(w.gelesen)}">${esc(uhrzeit(w.gelesen))}</span>` : '';
    body = compact
      ? `<b>${esc(w.name || w.pfad)}</b> · ${w.seiten} Seiten${gelesen} · ${glossar}${link}`
      : `<b>${esc(w.name || w.pfad)}</b> · <code>${esc(w.pfad)}</code><br>${w.seiten} Seiten${gelesen} · ${glossar}${warn}`;
  } else if (z === 'fehler') {
    cls = 'fail'; badge = '<span class="badge fail">nicht erreichbar</span>';
    body = compact
      ? `<code>${esc(w.pfad || '')}</code> · ${esc(w.meldung || '')}${link}`
      : `<code>${esc(w.pfad || '')}</code><br>${esc(w.meldung || '')} Bis dahin arbeitet der Souffleur ohne Wiki.<br>${glossar}${warn}`;
  } else if (z === 'laedt') {
    cls = 'none'; badge = '<span class="badge laeuft">liest …</span>';
    body = `${esc((w && w.meldung) || 'Wiki wird gelesen …')}${link}`;
  } else {
    const text = (w && w.meldung) || 'Kein Wiki verknüpft. Der Souffleur erkennt nur Fragen und liefert Essenzen.';
    body = compact
      ? `${esc(text)}${link}`
      : `${esc(text.replace(/\.\s*$/, ''))} – ohne Belege und ohne Widersprüche.<br>${glossar}`;
  }
  box.className = `wiki-state ${cls}${compact ? ' compact' : ''}`;
  box.innerHTML = `${badge}<span class="body">${body}</span>`;
}

/** Wiki-Zustand des Projekts holen (leer = das Wiki des geoeffneten Projekts). */
export async function loadWikiStatus() {
  try {
    S.wikiStatus = await api('/api/wiki/status?path=');
  } catch (err) {
    S.wikiStatus = { zustand: 'fehler', pfad: (projekt() && projekt().wiki_dir) || '', meldung: err.message, warnungen: [] };
  }
  document.dispatchEvent(new CustomEvent('audioscribe:wiki'));
  return S.wikiStatus;
}

// --- Dialog "Ins Wiki speichern" ---------------------------------------------------------

let wikiSave = null;   // {sitzung, resolve}

/** Wie audioscribe.agent.material.slugify - nur fuer die Vorschau des Zielordners. */
export function slugify(text) {
  let v = text.trim().toLowerCase()
    .replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/ß/g, 'ss');
  v = v.normalize('NFKD').replace(/[^\x00-\x7f]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return v.slice(0, 80).replace(/-+$/, '') || 'analyse';
}

function zielVorschau() {
  const p = projekt();
  if (!p || !wikiSave) return;
  const name = wikiSave.sitzung.name || '';
  const datum = (name.match(/\d{4}-\d{2}-\d{2}/) || ['JJJJ-MM-TT'])[0];
  const titel = $('wikiDlgName').value.trim();
  const live = name.match(/^live-\d{4}-\d{2}-\d{2}_(\d{2}-\d{2}-\d{2})$/);
  const kurz = titel ? slugify(titel) : (live ? `live-${live[1]}` : slugify(name.replace(/\d{4}-\d{2}-\d{2}/, '') || name));
  $('wikiDlgTarget').innerHTML = `Ablage: <code>${esc(trimSep(p.raw_dir))}${esc(sep())}${esc(datum)}_${esc(kurz)}</code>`
    + ($('wikiDlgBilder').checked && !$('wikiDlgBilder').disabled
      ? `<br>Bilder: <code>${esc(trimSep(p.assets_dir))}${esc(sep())}${esc(datum)}_${esc(kurz)}</code>` : '');
}

/**
 * Sitzung ins Wiki speichern. `sitzung` = {path, name, titel, frames}. Loest mit der Ablage
 * auf ({ordner, assets, bilder, …}) oder mit null, wenn abgebrochen wurde.
 */
export function openWikiDialog(sitzung) {
  const p = projekt();
  if (!p) return Promise.resolve(null);
  if (wikiSave) closeWikiDialog(null);
  const bilder = sitzung.frames || 0;
  $('wikiDlgInfo').textContent = 'Das Transkript wird als neue Quelle abgelegt. '
    + 'Bestehendes im Wiki bleibt unverändert; die Wiki-Seiten werden nicht angefasst.';
  $('wikiDlgName').value = sitzung.titel || '';
  $('wikiDlgName').placeholder = sitzung.name || '';
  $('wikiDlgBilder').disabled = bilder === 0;
  $('wikiDlgBilder').checked = bilder > 0 && p.wiki_bilder !== false;
  $('wikiDlgBilderLabel').textContent = bilder ? `Bilder mit übertragen (${bilder})` : 'Bilder mit übertragen – diese Sitzung hat keine';
  // Markierungen sind KI-erzeugt: nur mit, wenn das Projekt es so festgelegt hat.
  $('wikiDlgMarkierungen').checked = p.wiki_markierungen === true;
  $('wikiDlgImmer').checked = false;
  $('wikiDlgImmerRow').hidden = p.wiki_speichern === 'immer' || !!sitzung.ohneImmer;
  $('wikiDlgErr').textContent = '';
  $('wikiDlgOk').disabled = false;
  $('wikiDlg').showModal();
  return new Promise((resolve) => { wikiSave = { sitzung, resolve }; zielVorschau(); });
}

function closeWikiDialog(result) {
  const w = wikiSave;
  wikiSave = null;
  if ($('wikiDlg').open) $('wikiDlg').close();
  if (w) w.resolve(result);
}

$('wikiDlgName').oninput = zielVorschau;
$('wikiDlgBilder').onchange = zielVorschau;
$('wikiDlgCancel').onclick = () => closeWikiDialog(null);
$('wikiDlg').addEventListener('close', () => closeWikiDialog(null));
$('wikiDlg').addEventListener('click', (e) => { if (e.target === $('wikiDlg')) closeWikiDialog(null); });
$('wikiDlgOk').onclick = async () => {
  if (!wikiSave) return;
  $('wikiDlgErr').textContent = '';
  $('wikiDlgOk').disabled = true;
  const immer = $('wikiDlgImmer').checked;
  try {
    const ablage = await post('/api/wiki/speichern', {
      sitzung: wikiSave.sitzung.path,
      titel: $('wikiDlgName').value.trim(),
      bilder: $('wikiDlgBilder').checked && !$('wikiDlgBilder').disabled,
      markierungen: $('wikiDlgMarkierungen').checked,
      immer,
    });
    if (immer) setKontext(await api('/api/kontext'));
    if (ablage.hinweis) toast(ablage.hinweis, 'fehler');
    toast(`Ins Wiki gespeichert: ${basename(ablage.ordner)}${ablage.bilder ? ` · ${ablage.bilder} Bilder` : ''}`
      + `${ablage.markierungen ? ` · ${ablage.markierungen} Markierungen` : ''}`);
    closeWikiDialog(ablage);
  } catch (err) {
    $('wikiDlgErr').textContent = err.message;
    $('wikiDlgOk').disabled = false;
  }
};
