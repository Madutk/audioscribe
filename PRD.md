# PRD – AudioScribe

**Lokale Audio-Transkription mit Sprecher-Diarisierung**

| | |
|---|---|
| **Status** | Entwurf |
| **Datum** | 2026-06-30 |
| **Autor** | Marek (madutkow@googlemail.com) |
| **Projektordner** | `C:\Users\Marek\develop\git\audioscribe` |

---

## 1. Ziel & Vision

AudioScribe verwandelt eine Meeting-Audiodatei in ein lesbares, zeitgestempeltes
Transkript, in dem die einzelnen Sprecher voneinander getrennt sind
(„Sprecher 1 / 2 / 3"). Es ist die **Transkriptions-Basisstufe** für die
übergeordnete lokale Meeting-Protokoll-Pipeline (Video → Protokoll) und läuft
**vollständig lokal** auf der vorhandenen Hardware – ohne dass Audio den Rechner
verlässt.

## 2. Problem / Motivation

Meetings (10 min – 2 h) sollen ohne manuelles Mitschreiben in ein durchsuchbares,
weiterverarbeitbares Textformat überführt werden. Cloud-Transkriptionsdienste
scheiden aus Datenschutzgründen aus; vertrauliche Inhalte dürfen den Rechner
nicht verlassen. Es braucht daher eine lokale Lösung, die Transkription **und**
Sprechertrennung kombiniert.

## 3. Nutzer & Nutzungskontext

- **Primärnutzer:** Marek (Einzelnutzer, technisch versiert).
- **Bedienung:** Datei wird dem Skript übergeben; Wartezeit von einigen Minuten
  ist akzeptabel (kein Echtzeit-Bedarf).
- **Folgeschritt:** Das erzeugte Transkript dient als Eingabe für die
  Protokoll-Generierung der Meeting-Pipeline.

## 4. Umfang

### 4.1 In Scope (Basisausstattung)
- Transkription einer einzelnen Audiodatei in Text.
- **Video-Eingabe**: aus einer Videodatei wird zunächst die Audiospur extrahiert,
  danach wie eine Audiodatei verarbeitet.
- **Diarisierung**: automatische Trennung in „Sprecher 1 / 2 / 3".
- **Wort-/Segment-Zeitstempel** im Transkript.
- Ausgabe als **Markdown** (Primärformat), optional **PDF**.
- Deutsch als Hauptsprache, inklusive eingestreuter englischer Fachbegriffe.

### 4.2 Out of Scope (für die Basisstufe)
- **Echte Personen-Identifikation** (Zuordnung realer Namen via Stimmprofil/Enrollment).
  Namen werden bei Bedarf **manuell** nachgetragen.
- Nah-Echtzeit-/Live-Transkription.
- Robuste Trennung **stark überlappender** Sprache (nur Best-Effort).
- GUI / Web-Oberfläche (zunächst Kommandozeilen-Skript).
- Batch-Verarbeitung ganzer Ordner (zunächst eine Datei pro Aufruf).

## 5. Funktionale Anforderungen

| ID | Anforderung |
|----|-------------|
| FR-1 | Das Tool nimmt eine Audiodatei (mp3, m4a, wav, …) als Eingabe entgegen. |
| FR-2 | Es erzeugt ein vollständiges Transkript des gesprochenen Inhalts. |
| FR-3 | Es trennt die Sprecher automatisch und kennzeichnet sie als „Sprecher 1/2/3". |
| FR-4 | Jeder Sprecherbeitrag erhält einen Zeitstempel (HH:MM:SS). |
| FR-5 | Aufeinanderfolgende Beiträge desselben Sprechers werden zu Absätzen zusammengefasst. |
| FR-6 | Die Sprecheranzahl wird automatisch erkannt; optional über Parameter vorgebbar (`num/min/max-speakers`). |
| FR-7 | Ausgabe als Markdown mit Kopfzeile (Datei, Länge, Sprache, Anzahl Sprecher). |
| FR-8 | Optionale Konvertierung des Markdown in PDF. |
| FR-9 | Sprache standardmäßig Deutsch, mit Option auf Auto-Erkennung. |
| FR-10 | Das Tool nimmt auch **Videodateien** (mp4, mkv, mov, webm, …) entgegen und extrahiert vor der Transkription automatisch die Audiospur (als 16-kHz-Mono-WAV). |
| FR-11 | **Feingranulare Zeitstempel**: auch innerhalb eines Sprecher-Beitrags wird in einstellbaren Abständen ein neuer Zeitstempel gesetzt (Default: alle 2 Sätze, parametrisierbar; `0` = ganzer Beitrag als ein Block). Die Zeit stammt aus den Wort-Zeitstempeln des Alignments. |

## 6. Nicht-funktionale Anforderungen

| ID | Anforderung |
|----|-------------|
| NFR-1 | **Vollständig lokal**: Audio verlässt den Rechner nicht. Einzige Online-Aktion ist der einmalige Download der Modellgewichte von Hugging Face. |
| NFR-2 | **Hardware-Budget**: Lauffähig auf RTX 3080 Laptop mit 8 GB VRAM. Die Modelle laufen **sequenziell**; VRAM wird zwischen den Stufen freigegeben. |
| NFR-3 | **Performance**: Batch-Verarbeitung; einige Minuten Rechenzeit pro Aufnahme sind akzeptabel (Qualität vor Tempo). |
| NFR-4 | **Plattform**: Ausführung unter **WSL2** (Ubuntu) auf Windows 11. |
| NFR-5 | **Robustheit**: Aufnahmen von 10 min bis 2 h müssen ohne Speicherüberlauf verarbeitbar sein. |
| NFR-6 | **Editierbarkeit**: Markdown wird immer erzeugt, damit der Text vor der PDF-Erzeugung korrigiert werden kann. |

## 7. Technischer Ansatz (festgelegte Entscheidungen)

**Pipeline: WhisperX**, bestehend aus drei sequenziellen Stufen:

1. **Transkription** – faster-whisper `large-v3`.
2. **Wort-Alignment** – wav2vec2, für exakte Zeitstempel.
3. **Diarisierung** – pyannote (`speaker-diarization-3.1`).

Nach jeder Stufe wird das Modell aus dem VRAM entfernt (passend zu den 8 GB).
Die pyannote-Gewichte erfordern einen Hugging-Face-Token und das einmalige
Akzeptieren der Modell-Lizenzen; die Inferenz selbst läuft danach offline.

**Begründung:** WhisperX bündelt Transkription, Alignment und Diarisierung in
einer Pipeline, ist auf der vorhandenen Hardware lauffähig und etabliert.

## 8. Ein- / Ausgabe

- **Eingabe:** Pfad zu einer Audio- oder Videodatei (bei Video wird die Audiospur
  zuvor extrahiert). Optionale Parameter für Modell, Sprache, Sprecheranzahl,
  Rechenpräzision/Batchgröße (VRAM-Tuning).
- **Ausgabe (Markdown):** Kopfblock mit Metadaten + zeitgestempelte
  Sprecherabsätze, z. B.:

  ```
  **[00:01:23] Sprecher 1:** Guten Morgen, fangen wir an …
  **[00:01:41] Sprecher 2:** Ja, einverstanden …
  ```
- **Ausgabe (PDF):** optional aus dem Markdown gerendert.

## 9. Annahmen & Standard-Defaults

- Sprecheranzahl: **automatisch** (überschreibbar).
- Sprache: **Deutsch**, englische Fachbegriffe inbegriffen.
- Überlappende Sprache: **Best-Effort**, keine Garantie.
- Audioquelle/Mikrofonsituation: noch unbekannt – wird am ersten echten Sample
  validiert und ggf. nachjustiert.

## 10. Offene Punkte / Risiken

| Thema | Risiko / Frage |
|-------|----------------|
| VRAM (8 GB) | `large-v3` in float16 könnte knapp werden → Fallback auf `int8` / kleinere Batchgröße. Am echten Sample prüfen. |
| Audioqualität | Diarisierungsqualität hängt stark vom Mikrofon-Setup ab (Raummikro vs. Headsets). |
| Überlappung | Gleichzeitiges Sprechen verschlechtert die Sprechertrennung. |
| HF-Abhängigkeit | Einmaliger Online-Download nötig; reine Offline-Variante (ohne HF) wäre Aufwand. |
| Code-Switching | Deutsch/Englisch gemischt kann Whisper gelegentlich stolpern lassen. |

## 11. Akzeptanzkriterien

- [ ] Eine 10–120-minütige deutsche Meeting-Aufnahme wird ohne Absturz verarbeitet.
- [ ] Das Transkript enthält zeitgestempelte, nach Sprechern getrennte Absätze.
- [ ] Markdown wird erzeugt; PDF-Erzeugung ist mit einem Befehl möglich.
- [ ] Der gesamte Vorgang läuft lokal (kein Audio-Upload).
- [ ] Läuft auf der RTX 3080 (8 GB) innerhalb weniger Minuten pro Aufnahme.

## 12. Ausbaustufen (später, nicht Teil der Basis)

- Manuelles/halbautomatisches Mapping „Sprecher N → realer Name" (z. B. via
  Stimm-Enrollment wiederkehrender Teilnehmer).
- Ordner-/Batch-Verarbeitung mehrerer Dateien.
- Bessere Diarisierung (z. B. NeMo-basierter Ansatz), falls pyannote nicht reicht.
- Integration in die übergeordnete Meeting-Protokoll-Pipeline (Transkript →
  strukturiertes Protokoll).
- Einfache GUI / Drag-&-Drop.
