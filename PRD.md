# PRD – AudioScribe

**Lokale Audio-Transkription mit Sprecher-Diarisierung**

| | |
|---|---|
| **Status** | Entwurf |
| **Datum** | 2026-06-30 |
| **Autor** | Marek (madutkow@googlemail.com) |
| **Projektordner** | `C:\Users\user\develop\git\audioscribe` |

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
- **Visuelle Bild-Annotation** – wichtige Standbilder aus dem Video dem Transkript
  zeitlich zuordnen. Ausspezifiziert in **§13**.
- **CPU-only-Betrieb** – Nutzung auf Rechnern ohne NVIDIA-Karte. Ausspezifiziert in **§14**.

## 13. Ausbaustufe: Visuelle Bild-Annotation (Review-Oberfläche)

> Status: Entwurf · Additive Ausbaustufe auf der Transkriptions-Basisstufe (§1–§12).
> Greift **nicht** in die Batch-Pipeline ein, sondern konsumiert deren Ausgaben.

### 13.1 Ziel

Meetings transportieren ihren Inhalt nicht nur über Sprache, sondern auch über
**geteilte Bildschirme** (Folien, Diagramme, Demos). Diese Stufe verknüpft den
transkribierten Text mit den zugehörigen **Standbildern**: Nach der unveränderten
Batch-Transkription markiert der Nutzer in einer lokalen Review-Oberfläche wichtige
Video-Frames; jedes Standbild wird dem Transkript an der **zeitlich passenden Stelle**
zugeordnet. Ergebnis ist ein angereichertes Transkript (Text + Bild) als Eingabe für
die übergeordnete Meeting-Protokoll-Pipeline.

### 13.2 Abgrenzung / Designentscheidungen (festgelegt)

- **Nachgelagert, nicht live:** Markiert wird **nach** der Transkription in einer
  Review-UI – kein Live-/Streaming-ASR (die Batch-Pipeline bleibt unverändert).
- **Artefakt = Standbild (PNG):** kein OCR in dieser Stufe (spätere Option, s. §13.8).
- **Interaktion:** Video **scrubben** + Knopf erfasst den **aktuellen Wiedergabe-
  Zeitpunkt**; daraus wird server-seitig ein framegenauer PNG extrahiert.
- **Markierungen als Sidecar** (`marks.json`), getrennt vom handeditierbaren Markdown.
- **Optionale, separate Komponente:** Der Kern-CLI bleibt ohne Webserver-
  Abhängigkeiten lauffähig.

### 13.3 Funktionale Anforderungen

| ID | Anforderung |
|----|-------------|
| FR-12 | Die Transkriptions-Pipeline schreibt zusätzlich zum Markdown eine maschinenlesbare `transcript.json` (Absätze/Segmente mit `start`/`end`, Sprecher, Text) **inklusive Pfad zum Original-Medium**. |
| FR-13 | Ein lokaler Befehl (`audioscribe review <ordner\|video>`) startet einen lokalen Webserver und öffnet eine Browser-Oberfläche mit **suchbarem (scrubbarem) Videoplayer** und synchron mitlaufendem Transkript. |
| FR-14 | Ein Knopf erfasst den **aktuellen Wiedergabe-Zeitpunkt** und extrahiert daraus ein **framegenaues Standbild (PNG)** mit dem gebündelten ffmpeg. |
| FR-15 | Markierungen werden in einem **Sidecar** (`marks.json`) gespeichert – getrennt vom handeditierbaren Markdown; erneute Transkriptionsläufe oder Handedits überschreiben sie **nicht**. |
| FR-16 | Beim Markieren wird ein **Reaktionslag-Offset** abgezogen (Default **−2,5 s**), in der UI justierbar. |
| FR-17 | Gesetzte Markierungen werden als **Thumbnail-Liste** angezeigt und lassen sich einzeln **löschen**. |
| FR-18 | Ein Befehl (`audioscribe export <ordner>`) **merged** Transkript + Markierungen zu Markdown (+ optional PDF) und bettet jedes Bild am Absatz mit nächstem `start ≤ t` ein. |

### 13.4 Nicht-funktionale Anforderungen

| ID | Anforderung |
|----|-------------|
| NFR-7 | **Optionale Komponente**: Die Review-Funktion liegt in einer eigenen Dependency-Gruppe (z. B. `[review]`); der Kern-CLI (Transkription/Diarisierung) bleibt **ohne** Webserver-Abhängigkeiten lauffähig. |
| NFR-8 | **Vollständig lokal**: Der Webserver bindet ausschließlich an `localhost`; kein Medien-Upload, keine Daten verlassen den Rechner (konsistent mit NFR-1). |
| NFR-9 | **Kein Eingriff in die Pipeline**: Die Annotation ist eine additive Schicht auf den Pipeline-Ausgaben; Transkriptionsverhalten und -ergebnisse bleiben unverändert. |

### 13.5 Technischer Ansatz (festgelegte Entscheidungen)

- **`transcript.json` als Brücke:** Die Pipeline emittiert die Absätze/Segmente
  maschinenlesbar (die `Segment`/`Paragraph`-Dataclasses tragen `start`/`end` bereits);
  Markdown-Parsing entfällt. Der Original-Medienpfad wird mitgespeichert (das
  extrahierte `…16k.wav` enthält keine Bilder).
- **Lokaler Webserver** (FastAPI + uvicorn) als optionale Dependency-Gruppe; bindet an
  `localhost`, öffnet den Browser. Eine statische HTML/JS-Seite (natives `<video>`,
  Knopf-`onclick` → `fetch('/mark?t=' + video.currentTime)`).
- **Video range-fähig ausliefern** (HTTP Range), sonst ist im `<video>` kein Springen/
  Scrubbing möglich.
- **Frame-Extraktion** via gebündeltem ffmpeg (`imageio-ffmpeg`), **framegenauer Seek**
  (Genauigkeit vor Tempo – konsistent mit NFR-3).
- **Merge-Export:** `transcript.json` + `marks.json` → Markdown/PDF mit eingebetteten
  Bildern; nutzt den vorhandenen Export-Pfad (`export.py`).

### 13.6 Ein- / Ausgabe

- **Befehle:** `audioscribe review <ordner\|video>`, `audioscribe export <ordner\|video> [--pdf]`.
- **Artefakte je Aufnahme:** `output/<name>/transcript.json`, `…/frames/<HH-MM-SS>.png`,
  `…/marks.json`, `…/transkript.annotiert.md` (+ optional `…/transkript.annotiert.pdf`).
  Das handeditierbare `transkript.md` bleibt **unberührt** (NFR-6).
- **`marks.json`** (Sidecar):

  ```json
  [
    { "t": 80.9, "png": "frames/00-01-20.png", "note": null,
      "created": "2026-06-30 15:40" }
  ]
  ```
  > `t` ist der **lag-korrigierte** Zeitstempel und die Quelle der Wahrheit; die
  > Einfüge-Position im Transkript wird beim Export aus `t` berechnet (nicht
  > gespeichert) – so bleiben Markierungen auch nach erneuter Transkription gültig.
- **Markdown (gemergt):**

  ```
  **[00:01:23] Sprecher 1:** Ich teile gleich den Bildschirm …

  ![Markierter Bildschirm 00:01:23](frames/00-01-23.png)

  **[00:01:41] Sprecher 2:** Ja, einverstanden …
  ```

### 13.7 Restentscheidungen & Standard-Defaults

| Punkt | Default |
|-------|---------|
| Reaktionslag-Offset | **−2,5 s**, in der UI justierbar (FR-16). |
| Insertion-Regel | Bild nach dem Absatz mit nächstem `start ≤ t`. |
| Dedup | **kein** harter Mindestabstand; manuelles Löschen über die Thumbnail-Liste (FR-17). |
| Bildformat | voller Frame als **PNG** (JPG nur, falls Dateigröße stört). |

### 13.8 Offene Punkte / Risiken

| Thema | Risiko / Frage |
|-------|----------------|
| Video-Auslieferung | Ohne **HTTP-Range-Support** kein Scrubbing im `<video>` – Range-fähigen Endpoint bzw. `StaticFiles` verwenden. |
| ffmpeg-Seek | Schneller Seek (`-ss` vor `-i`) rundet auf Keyframes; für framegenaue Treffer genauen Seek (`-ss` nach `-i` / `-accurate_seek`) nutzen – langsamer. |
| Zeitachsen | `video.currentTime` und WhisperX-Zeitstempel teilen denselben Nullpunkt (gemeinsame Quelle) – am ersten Sample bestätigen. |
| Original-Medium | Pfad muss persistiert werden (FR-12); fehlt das Original, kann die UI keine Frames ziehen. |
| OCR (später) | Folientext per OCR wäre für das Protokoll wertvoller als ein Bild – bewusst auf eine spätere Stufe verschoben. |

### 13.9 Akzeptanzkriterien

- [ ] Nach `run` existiert eine `transcript.json` mit Zeitstempeln und Original-Medienpfad.
- [ ] `audioscribe review` öffnet eine Oberfläche, in der das Video **flüssig scrub-/suchbar** ist und das Transkript synchron mitläuft.
- [ ] Ein Knopfdruck erzeugt ein framegenaues PNG und einen Eintrag in `marks.json`; die Markierung erscheint in der Thumbnail-Liste und ist löschbar.
- [ ] `audioscribe export` erzeugt ein Markdown (+ optional PDF) mit den Bildern an der zeitlich passenden Stelle.
- [ ] Erneute Transkription oder Handedits am Markdown **lassen `marks.json` unangetastet**.
- [ ] Der gesamte Vorgang läuft lokal (`localhost`, kein Upload); der Kern-CLI bleibt ohne die Review-Dependencies lauffähig.

## 14. Ausbaustufe: CPU-only-Betrieb (Rechner ohne NVIDIA-Karte)

> Status: Umgesetzt · Additive Ausbaustufe auf der Transkriptions-Basisstufe (§1–§12).
> Der Nutzer arbeitet auch an Rechnern **ohne** NVIDIA-GPU; dort muss AudioScribe
> installier- und lauffähig sein — als **Option** bei Installation und Ausführung.

### 14.1 Ziel

AudioScribe läuft wahlweise auf **CUDA** (wie bisher, schnell) oder **rein auf der CPU**
(langsamer, aber ohne NVIDIA-Hardware/-Treiber). Die Wahl fällt zweistufig: bei der
Installation (welches PyTorch-Backend wird installiert) und beim Ausführen (welches
Gerät wird verwendet — standardmäßig automatisch erkannt).

### 14.2 Abgrenzung / Designentscheidungen (festgelegt)

- **Kein Apple-MPS-Support** — Zielplattform bleibt Linux/WSL2 (NFR-4).
- **`--device auto` ist der neue Default** (statt bisher fest `cuda`): CUDA falls
  verfügbar, sonst CPU. Explizites `--device cuda|cpu` erzwingt.
- **Backend-Wahl über zwei sich ausschließende uv-Extras** (`cpu` / `cu124`) mit
  `[tool.uv] conflicts` — offizielles uv-Muster für PyTorch-Accelerator-Wahl,
  ein gemeinsames `uv.lock` für beide Varianten.

### 14.3 Funktionale Anforderungen

| ID | Anforderung |
|----|-------------|
| FR-19 | Die Installation bietet zwei sich ausschließende Backend-Extras: `uv sync --extra cu124` (CUDA-Wheels, wie bisher) und `uv sync --extra cpu` (schlanke CPU-Wheels ohne `nvidia-*`-Pakete). Gleichzeitige Wahl bricht mit einem Konfliktfehler ab; beide Varianten teilen sich ein `uv.lock`. |
| FR-20 | `--device` (bzw. `AUDIOSCRIBE_DEVICE`) akzeptiert `auto` (Default), `cuda[:N]` und `cpu`. `auto` wählt CUDA, falls via torch verfügbar, sonst CPU. Explizit erzwungenes `cuda` ohne verfügbares CUDA bricht mit einer klaren Fehlermeldung ab (Hinweis auf `--device auto|cpu` und `doctor`). |
| FR-21 | `--compute-type` (bzw. `AUDIOSCRIBE_WHISPER_COMPUTE_TYPE`) defaultet auf `auto` und wird device-abhängig aufgelöst: `cuda → float16`, `cpu → int8` (CTranslate2 unterstützt kein float16 auf CPU). Eine explizite Angabe gewinnt immer. |
| FR-22 | `audioscribe doctor` bewertet die Gerätesituation gemäß Statusmatrix: fehlendes CUDA ist nur noch FAIL, wenn das Gerät explizit auf `cuda` erzwungen ist; bei `auto` wird der CPU-Fallback als OK (mit „langsam“-Hinweis) gemeldet. Angezeigt werden torch-Build (`+cpu`/`+cu124`), effektives Gerät, effektiver `compute_type` und ggf. der GPU-Name. |

### 14.4 Nicht-funktionale Anforderungen

| ID | Anforderung |
|----|-------------|
| NFR-10 | **Kein torch-Import beim bloßen Config-Import**: Die Geräteauflösung passiert lazy erst bei Gebrauch; `review`/`export` bleiben torch-frei lauffähig (konsistent mit NFR-7). |
| NFR-11 | **Identisches Verhalten**: Ausgaben (Markdown/JSON/PDF) sind auf CPU inhaltlich identisch zum GPU-Lauf — nur langsamer. Der cuDNN-8-Bootstrap (LD_LIBRARY_PATH/Re-Exec) entfällt im CPU-Pfad vollständig. |

### 14.5 Technischer Ansatz (festgelegte Entscheidungen)

- **pyproject:** torch/torchaudio wandern aus den Kern-Dependencies in die Extras
  `cpu`/`cu124` (je `>=2.4,<2.7`; Deckel hält beide Lock-Varianten auf derselben
  torch-Version). Extra-abhängige `[tool.uv.sources]` binden sie an die Indexe
  `download.pytorch.org/whl/cpu` bzw. `/whl/cu124`.
- **Auflösung:** reine Funktionen `resolve_device()` / `resolve_compute_type()` in
  `config.py`; `Settings` speichert Rohwerte (`auto`). Die CLI löst im `run`-Befehl auf,
  schreibt das Ergebnis in die `AUDIOSCRIBE_*`-Env zurück (Konsistenz über das
  Re-Exec des cuDNN-Bootstraps hinweg) und führt den Bootstrap nur im CUDA-Pfad aus.
- **Restlücke (bewusst):** `uv sync`/`uv run` ganz ohne Backend-Extra installiert das
  PyPI-torch (CUDA-Bundle); uv kennt keine Pflicht- oder Default-Extras. Auf
  CPU-Rechnern gehört das Extra deshalb auch an `uv run` (`uv run --extra cpu …`).
  Abgefangen über README und den doctor (torch-Build-Anzeige + Tipp auf
  `--extra cpu`, wenn ohne CUDA der fette Build installiert ist).

### 14.6 Standard-Defaults

| Punkt | Default |
|-------|---------|
| Gerät | `auto` (CUDA falls verfügbar, sonst CPU). |
| compute_type | `auto` → `float16` (cuda) / `int8` (cpu). |
| batch_size | unverändert 8 (limitiert VRAM; auf CPU unkritisch — wirksamster Hebel dort ist ein kleineres Modell, z. B. `--model medium`). |

### 14.7 Akzeptanzkriterien

- [ ] `uv sync --extra cpu` installiert ohne `nvidia-*`-Pakete (torch-Build `+cpu`); `uv sync --extra cu124` verhält sich wie bisher; beide gleichzeitig → Konfliktfehler.
- [ ] `audioscribe run` läuft auf einem Rechner ohne NVIDIA-Karte ohne Zusatzangabe durch (`auto` → CPU, compute_type `int8`, kein cuDNN-Download/Re-Exec).
- [ ] `--device cpu` erzwingt CPU auch auf einem GPU-Rechner; `--device cuda` ohne CUDA bricht mit klarer Meldung ab.
- [ ] `audioscribe doctor` meldet die Matrix aus FR-22 korrekt (insb. kein FAIL mehr bei `auto` ohne CUDA).
