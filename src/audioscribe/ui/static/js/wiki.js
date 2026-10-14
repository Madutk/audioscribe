// Wiki des Projekts: Zustandsanzeige (Einstellungen, Live, Assistent) und der Dialog
// "Speichern unter ..." / "Ins Wiki speichern" (PRD §21) - gemeinsam fuer Live-Ansicht und
// Nachbereitung, im Projekt wie bei "Sofort aufnehmen".

import { $, S, api, post, esc, modus, projekt, sep, trimSep, dirname, toast, basename } from './kern.js';
import { setKontext } from './kontext.js';
import { pickFolder } from './dialoge.js';

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

/** Gleicher Ordner? (Pfade so, wie Server und Nutzer sie schreiben - ohne Schluss-Trenner.) */
const gleicherOrdner = (a, b) => !!a && !!b && trimSep(a) === trimSep(b);

/**
 * Vorbelegung der beiden Ziele: raw/ und Assets des Projekt-Wikis; bei "Sofort aufnehmen" das
 * Wiki aus den Einstellungen (ueber /api/wiki/status); sonst der Ordner neben der Sitzung.
 */
function vorgabeBasen(sitzung) {
  const p = projekt();
  if (p && p.raw_dir) return { raw: p.raw_dir, assets: p.assets_dir, wiki: true };
  const a = S.wikiStatus && S.wikiStatus.ablage;
  if (a && a.raw_basis) return { raw: a.raw_basis, assets: a.assets_basis, wiki: true };
  const eltern = dirname(sitzung.path || '');
  return { raw: eltern, assets: eltern ? `${eltern}${sep()}assets` : '', wiki: false };
}

/** Sind die gewaehlten Ziele genau raw/ und Assets des Projekt-Wikis? Nur dann gilt "immer". */
function istStandard() {
  const p = projekt();
  if (!p || !p.raw_dir) return false;
  const bilder = $('wikiDlgBilder').checked && !$('wikiDlgBilder').disabled;
  return gleicherOrdner($('wikiDlgRaw').value, p.raw_dir)
    && (!bilder || gleicherOrdner($('wikiDlgAssets').value, p.assets_dir));
}

function zielVorschau() {
  if (!wikiSave) return;
  const p = projekt() || {};
  const name = wikiSave.sitzung.name || '';
  const datum = (name.match(/\d{4}-\d{2}-\d{2}/) || ['JJJJ-MM-TT'])[0];
  const titel = $('wikiDlgName').value.trim();
  const live = name.match(/^live-\d{4}-\d{2}-\d{2}_(\d{2}-\d{2}-\d{2})$/);
  const kurz = titel ? slugify(titel) : (live ? `live-${live[1]}` : slugify(name.replace(/\d{4}-\d{2}-\d{2}/, '') || name));
  const bilder = $('wikiDlgBilder').checked && !$('wikiDlgBilder').disabled;
  const raw = trimSep($('wikiDlgRaw').value.trim());
  const assets = trimSep($('wikiDlgAssets').value.trim());
  $('wikiDlgAssetsRow').hidden = !bilder;
  $('wikiDlgTarget').innerHTML = (raw
    ? `Ablage: <code>${esc(raw)}${esc(sep())}${esc(datum)}_${esc(kurz)}</code>`
    : '<span class="err">Bitte einen Ordner für das Transkript wählen.</span>')
    + (bilder && assets ? `<br>Bilder: <code>${esc(assets)}${esc(sep())}${esc(datum)}_${esc(kurz)}</code>` : '');
  // "Kuenftig immer" meint die Ablage ins Projekt-Wiki - bei anderen Zielen gibt es nichts zu merken.
  $('wikiDlgImmerRow').hidden = !istStandard() || p.wiki_speichern === 'immer' || !!wikiSave.sitzung.ohneImmer;
}

/**
 * Sitzung speichern - ins Wiki oder "unter ..." in frei gewaehlte Ordner. `sitzung` = {path,
 * name, titel, frames}. Loest mit der Ablage auf ({ordner, assets, bilder, frei, …}) oder mit
 * null, wenn abgebrochen wurde. Ohne Projekt nur bei "Sofort aufnehmen".
 */
export function openWikiDialog(sitzung) {
  if (!projekt() && modus() !== 'aufnahme') return Promise.resolve(null);
  if (wikiSave) closeWikiDialog(null);
  const p = projekt() || {};
  const bilder = sitzung.frames || 0;
  const basen = vorgabeBasen(sitzung);
  $('wikiDlgInfo').textContent = basen.wiki
    ? 'Das Transkript wird als neue Quelle im Wiki abgelegt, die Bilder im Assets-Ordner. '
      + 'Bestehendes bleibt unverändert; die Wiki-Seiten werden nicht angefasst. Beide Ziele lassen sich ändern.'
    : 'Transkript und Bilder werden in Ordner deiner Wahl kopiert; der Sitzungsordner bleibt unverändert.';
  $('wikiDlgName').value = sitzung.titel || '';
  $('wikiDlgName').placeholder = sitzung.name || '';
  $('wikiDlgRaw').value = basen.raw || '';
  $('wikiDlgAssets').value = basen.assets || '';
  $('wikiDlgBilder').disabled = bilder === 0;
  $('wikiDlgBilder').checked = bilder > 0 && p.wiki_bilder !== false;
  $('wikiDlgBilderLabel').textContent = bilder ? `Bilder mit übertragen (${bilder})` : 'Bilder mit übertragen – diese Sitzung hat keine';
  // Markierungen sind KI-erzeugt: nur mit, wenn das Projekt es so festgelegt hat.
  $('wikiDlgMarkierungen').checked = p.wiki_markierungen === true;
  $('wikiDlgImmer').checked = false;
  $('wikiDlgErr').textContent = '';
  $('wikiDlgOk').disabled = false;
  $('wikiDlg').showModal();
  return new Promise((resolve) => { wikiSave = { sitzung, resolve }; zielVorschau(); });
}

/** "Ordner waehlen ..." neben einem Pfadfeld: Systemdialog, Start ist der aktuelle Feldwert. */
async function ordnerWaehlen(feld, title) {
  const pfad = await pickFolder({ title, start: $(feld).value.trim() });
  if (pfad) { $(feld).value = pfad; zielVorschau(); }
}

function closeWikiDialog(result) {
  const w = wikiSave;
  wikiSave = null;
  if ($('wikiDlg').open) $('wikiDlg').close();
  if (w) w.resolve(result);
}

$('wikiDlgName').oninput = zielVorschau;
$('wikiDlgRaw').oninput = zielVorschau;
$('wikiDlgAssets').oninput = zielVorschau;
$('wikiDlgBilder').onchange = zielVorschau;
$('pickWikiDlgRaw').onclick = () => ordnerWaehlen('wikiDlgRaw', 'Ordner für das Transkript wählen');
$('pickWikiDlgAssets').onclick = () => ordnerWaehlen('wikiDlgAssets', 'Ordner für die Bilder wählen');
$('wikiDlgCancel').onclick = () => closeWikiDialog(null);
$('wikiDlg').addEventListener('close', () => closeWikiDialog(null));
$('wikiDlg').addEventListener('click', (e) => { if (e.target === $('wikiDlg')) closeWikiDialog(null); });
$('wikiDlgOk').onclick = async () => {
  if (!wikiSave) return;
  $('wikiDlgErr').textContent = '';
  $('wikiDlgOk').disabled = true;
  const bilder = $('wikiDlgBilder').checked && !$('wikiDlgBilder').disabled;
  const immer = $('wikiDlgImmer').checked && !$('wikiDlgImmerRow').hidden;
  try {
    const ablage = await post('/api/wiki/speichern', {
      sitzung: wikiSave.sitzung.path,
      titel: $('wikiDlgName').value.trim(),
      bilder,
      markierungen: $('wikiDlgMarkierungen').checked,
      immer,
      raw_basis: $('wikiDlgRaw').value.trim(),
      assets_basis: bilder ? $('wikiDlgAssets').value.trim() : '',
    });
    if (immer) setKontext(await api('/api/kontext'));
    if (ablage.hinweis) toast(ablage.hinweis, 'fehler');
    toast(`${ablage.frei ? 'Gespeichert' : 'Ins Wiki gespeichert'}: ${basename(ablage.ordner)}${ablage.bilder ? ` · ${ablage.bilder} Bilder` : ''}`
      + `${ablage.markierungen ? ` · ${ablage.markierungen} Markierungen` : ''}`);
    closeWikiDialog(ablage);
  } catch (err) {
    $('wikiDlgErr').textContent = err.message;
    $('wikiDlgOk').disabled = false;
  }
};
