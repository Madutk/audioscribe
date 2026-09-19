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

## 15. Ausbaustufe: Automatische Bildwechsel-Erkennung (Bildschirmaufnahmen)

> Status: umgesetzt · Additive Stufe der Transkriptions-Pipeline, standardmäßig **aus**.

### 15.1 Ziel

Bildschirmaufnahmen tragen einen erheblichen Teil ihres Inhalts im Bild. §13 holt ihn
über **manuelles** Markieren in der Review-Oberfläche. Diese Stufe erkennt Wechsel des
Bildschirminhalts **selbsttätig**, sichert je Wechsel ein Standbild und verknüpft es über
eine ID mit dem Transkript. Ziel ist ein Dokument, das Transkript und Bilder gemeinsam
einer KI zur Auswertung vorlegen kann.

### 15.2 Designentscheidungen (festgelegt)

- **Blockraster statt Pixelvergleich:** Das Bild wird auf 192×108 Graustufen verkleinert
  und in 16×9 Blöcke zerlegt. Ein Block gilt als geändert, wenn seine mittlere
  Absolutdifferenz die Schwelle übersteigt; ein Bildwechsel liegt erst bei mehreren
  Blöcken vor. **Damit löst ein Mauszeiger nichts aus** — er belegt genau einen Block.
  Gemessen an einer 2560×1440-Aufnahme: Mauszeiger 1–2 Blöcke, echte Wechsel 14–113.
- **Ein ffmpeg-Prozess für das ganze Video** (Rohstrom über eine Pipe), nicht ein Aufruf
  je Zeitpunkt. Konstanter Speicherbedarf, ~8× Echtzeit.
- **Serien werden zusammengefasst:** Animationen schlagen mehrfach an; das Standbild
  entsteht am Ende der Serie, also am fertig aufgebauten Bildschirm.
- **Notausgang bei Dauerbewegung:** Eine mitlaufende Kamerakachel beruhigt sich nie —
  nach 20 s wird trotzdem ein Bild gesichert, sonst lieferte eine Besprechungsaufnahme
  ein einziges Bild vom Schluss.
- **Verworfen:** ffmpegs `select='gt(scene,X)'` — kein Mauszeiger-Schutz, Schwelle bei
  Bildschirmarbeit nicht interpretierbar.
- **Wiederverwendung statt Parallelwelt:** Die Treffer werden als `Mark` in dasselbe
  `marks.json` geschrieben, das die Review-Oberfläche nutzt. Damit greift der komplette
  vorhandene Export-Pfad (FR-18) unverändert.

### 15.3 Funktionale Anforderungen

| ID | Anforderung |
|----|-------------|
| FR-23 | `audioscribe run --frames` erkennt Wechsel des Bildschirminhalts und sichert je Wechsel ein Standbild. Standardmäßig **aus**; nur für Videoquellen. |
| FR-24 | Bewegungen des Mauszeigers und blinkende Textcursor lösen **kein** Standbild aus. |
| FR-25 | Jedes Standbild trägt **ID und Zeitstempel** im Dateinamen (`frames/0001_00-01-23.jpg`); im annotierten Transkript erscheint es als `![Bild #0001 – 00:01:23](…)` am Absatz mit nächstem `start ≤ t`. |
| FR-26 | Empfindlichkeit (`grob`/`mittel`/`fein`), Bildformat (`jpg-1600`/`jpg-1280`/`png`), Abtastrate und Mindestabstand sind einstellbar — über CLI-Flags, `AUDIOSCRIBE_SCREEN_*` und (die ersten beiden) in der Stapel-Oberfläche. |
| FR-27 | Ein erneuter Lauf ersetzt die automatisch erzeugten Bilder samt Einträgen; **von Hand gesetzte Markierungen bleiben unberührt** (Gegenstück zu FR-15). |

### 15.4 Nicht-funktionale Anforderungen

| ID | Anforderung |
|----|-------------|
| NFR-10 | Die Stufe läuft **nach** Transkription und Diarisierung. Ein Fehler in ihr (fehlendes numpy, stolperndes ffmpeg) wird protokolliert und beendet den Lauf **nicht** — das Transkript ist zu dem Zeitpunkt bereits geschrieben. |
| NFR-11 | Die Bildmenge ist gedeckelt (400 je Aufnahme); wird gekürzt, nennt das Protokoll den passenden Regler. Kein stillschweigendes Abschneiden. |

### 15.5 Ein-/Ausgabe

- **Artefakte je Aufnahme:** `output/<name>/frames/<ID>_<HH-MM-SS>.jpg`, ergänzte
  `marks.json` (Felder `id`, `kind: "auto"`), `transkript.annotiert.md` (+ PDF bei `--pdf`).
  `transkript.md` und `transcript.json` bleiben **unverändert** (NFR-6/NFR-9).
- **Abhängigkeit:** Die Analyse nutzt numpy (kommt mit torch); fehlt es, wird die Stufe
  übersprungen.

### 15.6 Akzeptanzkriterien

- [x] Ein Lauf mit `--frames` auf einer Bildschirmaufnahme erzeugt Standbilder an den
      Stellen echter Wechsel; eine reine Mausbewegung erzeugt keines.
- [x] Die Standbilder tragen ID und Zeitstempel; das annotierte Transkript verweist mit
      derselben ID auf sie.
- [x] Ein zweiter Lauf liefert dieselben IDs (1..N) und lässt manuelle Markierungen stehen.
- [x] Ein Lauf **ohne** `--frames` verhält sich exakt wie zuvor.

## 16. Ausbaustufe: KI-Analyse per Claude-Agent

> Status: umgesetzt (autonomer Lauf) · optionales Extra `agent` · Dialogmodus vorbereitet, nicht umgesetzt.

### 16.1 Ziel

§15 liefert ein Dokument aus Transkript und Bildern, das eine KI auswerten kann. Diese Stufe
schließt den Schritt: Ein **Claude-Agent** analysiert einen Ergebnisordner selbstständig und
legt alle Dokumente, etwa Prozessdokumentation, Arbeitsanweisung und QS-Bericht, in einem
vom Nutzer gewählten Ordner ab. Gesteuert wird er über Prozessname, freien Kontext und
eine Auswahl an Skills. Abgerechnet wird über das **Claude-Abo** des Nutzers.

### 16.2 Designentscheidungen (festgelegt)

- **Claude Agent SDK statt Messages API.** Die Messages API rechnet ausschließlich über
  API-Key und Console-Guthaben ab. Das SDK steuert Claude Code und übernimmt dessen
  Anmeldung, bei einem Login per Abo also ohne API-Key. Außerdem liefert es Agenten-Loop,
  Datei-Werkzeuge, Bildverständnis (Read auf `frames/`) und Skills bereits mit.
- **Skills als Kopie im Arbeitsordner.** Die gewählten Skills werden nach
  `<ziel>/.claude/skills/` kopiert und nur über `setting_sources=["project"]` geladen. Der Lauf
  ist so reproduzierbar dokumentiert und unabhängig von den übrigen User-Skills.
- **Material als Kopie.** Transkript, `frames/` und `marks.json` werden nach `<ziel>/material/`
  kopiert. Skill-Skripte, die neben die Eingabe schreiben, bleiben damit im Zielordner, und
  die Ergebnisse sind in sich vollständig.
- **Schreibschutz per `can_use_tool`.** Jeder Schreib- oder Lesezugriff außerhalb des
  Arbeitsordners wird über eine reine Prüffunktion (`agent/guard.py`) entschieden und
  abgelehnt. `Bash` ist nicht pfadgenau prüfbar. Es bleibt standardmäßig an, weil die
  Skills Python-Skripte aufrufen, und lässt sich mit `--no-bash` abschalten.
- **Subprozess auch aus der Oberfläche.** Die UI startet `audioscribe analyze` wie die
  Transkription als Kindprozess. Damit sind Abbruch und Log gleich gelöst, und der Server
  importiert das SDK nicht.
- **Dialog vorbereitet.** Die Session-ID steht in `analyse.json`, `AnalyseSitzung.nachricht()`
  nimmt Folgeanweisungen an, und `--resume` setzt eine Sitzung fort.

### 16.3 Funktionale Anforderungen

| ID | Anforderung |
|----|-------------|
| FR-28 | `audioscribe analyze ORDNER\|VIDEO` startet einen Claude-Agenten auf dem Ergebnisordner eines `run`. Das annotierte Transkript hat Vorrang. Fehlt ein Transkript, bricht der Befehl mit Hinweis auf `run --frames` ab. |
| FR-29 | Der Nutzer gibt einen **Prozessnamen** (`--name`) und einen **Ausgabeordner** (`--out`) an. Alle Ergebnisse landen in `<out>/<slug(name)>/`. Fehlende Angaben werden im Terminal abgefragt. |
| FR-30 | Freier **Kontext** als Text (`--context-text`) und/oder als Dateien (`--context`, mehrfach). Kleine Textdateien werden direkt übergeben, andere Formate liegen dem Agenten als Datei vor. |
| FR-31 | **Skills** werden aus einem wählbaren Ordner (`--skills-dir`, Default `~/.claude/skills`, rekursiv) bereitgestellt: `--skill` mehrfach, Vorauswahl über `AUDIOSCRIBE_AGENT_SKILLS`, `--no-skills`, Liste mit `--list-skills`. |
| FR-32 | Der Agent schließt mit `INDEX.md` ab (Dokumente, Zweck, offene Punkte, Annahmen). `analyse.json` protokolliert Status, Skills, Modell, Session-ID, Dauer und rechnerische Kosten, `agent-log.txt` den Verlauf. |
| FR-33 | Die Browser-Oberfläche bietet einen Reiter „KI-Analyse“ mit Quellenauswahl, Prozessname, Ausgabeordner, Kontext, Kontextdateien, Skills, Modell, Live-Protokoll und Abbruch. Ausgabeordner, Modell und Skill-Auswahl werden gemerkt. Der Fortschritt wird aus den Werkzeugaufrufen abgeleitet, nicht geschätzt: Plan des Agenten (TaskCreate/TaskUpdate bzw. TodoWrite) als Schrittliste mit Balken, aktiver Skill, angesehene Standbilder und geschriebene Dokumente. Der Token-Gegenwert in USD wird nicht angezeigt, weil bei Abo-Anmeldung nichts abgerechnet wird. |
| FR-34 | `audioscribe doctor` prüft SDK, Claude Code und Skill-Ordner und warnt, wenn `ANTHROPIC_API_KEY` die Abo-Abrechnung übersteuert. |
| FR-35 | Enthält die Prozessdoku ein Mermaid-Diagramm, entstehen daraus `prozessbild.png` und `prozessbild.svg`. Die Quelle `prozessbild.mmd` schreibt der Agent; fehlt sie, übernimmt audioscribe den ersten Mermaid-Block aus den Dokumenten. Gerendert wird über den vorhandenen Edge oder Chrome headless (unter WSL die Windows-Exe) mit lokal mitgelieferter Mermaid-Bibliothek, ohne Playwright und ohne zusätzlichen Download. Fehler beim Rendern werden protokolliert und brechen die Analyse nicht ab. `audioscribe prozessbild ORDNER` rendert nach einer Handkorrektur neu, `--no-prozessbild` bzw. `AUDIOSCRIBE_AGENT_PROZESSBILD=0` schaltet die Bilder ab. |
| FR-36 | Zusätzlich entsteht ein BPMN-2.0-Modell mit Lanes (`bpmn-modell.bpmn`, bearbeitbar in Camunda Modeler, bpmn.io, Signavio …) samt PNG/SVG. Der Agent liefert nur die Fachlogik (`bpmn-modell.json`: Lanes, Knoten mit denselben S-/E-Nummern wie Doku und Prozessbild, Flüsse) und prüft sie mit `audioscribe bpmn . --pruefen`. Lanes sind Rollen, wenn mehrere Beteiligte erkennbar sind, sonst Systeme, mit Begründung in der Doku. Layout, XML (inkl. DI) und Bild erzeugt audioscribe selbst: kein `bpmn-auto-layout` (keine Lanes), kein bpmn-js zum Zeichnen (Wasserzeichen-Pflicht). Eine in einem Werkzeug bearbeitete `.bpmn` (fremder `exporter`) wird nur mit `--neu` überschrieben. Fehler werden protokolliert und brechen die Analyse nicht ab. |

### 16.4 Nicht-funktionale Anforderungen

| ID | Anforderung |
|----|-------------|
| NFR-12 | Der Agent **schreibt nur im Zielordner**; der audioscribe-Ergebnisordner bleibt unverändert. Abgelehnte Zugriffe erscheinen im Protokoll. |
| NFR-13 | Der Lauf ist von der privaten Claude-Code-Umgebung getrennt: keine User-Skills außer den gewählten, keine MCP-Server/Connectoren, keine globale `CLAUDE.md`. |
| NFR-14 | Ohne das Extra `agent` bleiben alle übrigen Befehle und die Oberfläche lauffähig; `analyze` nennt dann den Installationsbefehl. |

### 16.5 Ein-/Ausgabe

- **Eingabe:** `output/<name>/` (`transkript[.annotiert].md`, `transcript.json`, `marks.json`,
  `frames/`), Kontext, Skills.
- **Ausgabe:** `<out>/<slug>/` mit den Dokumenten des Agenten, `prozessbild.{mmd,png,svg}`, `bpmn-modell.{json,bpmn,png,svg}`, `INDEX.md`, `material/`,
  `kontext/`, `analyse.json`, `agent-log.txt` und `.claude/skills/`.
- **Konfiguration:** `AUDIOSCRIBE_AGENT_{MODEL, SKILLS_DIR, SKILLS, MAX_TURNS, OUTPUT_DIR}`.

### 16.6 Akzeptanzkriterien

- [x] Ein Lauf mit Abo-Login ohne `ANTHROPIC_API_KEY` erzeugt Dokumente und `INDEX.md`
      im Zielordner. `analyse.json` enthält eine Session-ID.
- [x] Ein Schreibversuch außerhalb des Zielordners wird abgelehnt und protokolliert.
- [x] `--resume` setzt die Sitzung mit erhaltenem Verlauf fort.
- [x] Start, Live-Protokoll und Abbruch funktionieren aus der Oberfläche. Ein Abbruch
      hinterlässt `status: abgebrochen` und keine verwaisten Prozesse.

### 16.7 Ausblick: Dialogmodus

Nach dem autonomen Lauf sollen Rückfragen und Nachbesserungen im Dialog möglich sein. Die
Grundlage steht: `AnalyseSitzung` hält einen `ClaudeSDKClient` offen und nimmt über
`nachricht()` weitere Anweisungen in derselben Sitzung an. Offen sind:

- ein Chat-Bereich im Reiter „KI-Analyse“, der Folgeanweisungen über `--resume` oder einen
  langlebigen Sitzungsprozess schickt
- Rückfragen des Agenten an den Nutzer (derzeit trifft er gekennzeichnete Annahmen)
- eine Übersicht früherer Analysen aus den `analyse.json`-Dateien

## 17. Ausbaustufe: Live-Transkription

> Status: Proof of Concept · optionales Extra `live` · nur natives Windows (nicht WSL).

### 17.1 Ziel

§4.2 schloss Nah-Echtzeit-Transkription für die Basisstufe aus. Diese Stufe hebt das auf:
Neben der Offline-Verarbeitung fertiger Dateien schneidet AudioScribe eine laufende Sitzung
mit – einen gewählten Monitor, das System-Audio (Ausgabe) und das Mikrofon (Eingabe) –,
zeigt das Transkript mit wenigen Sekunden Verzögerung an, sichert bei jedem Bildwechsel
einen Screenshot und legt alles im selben Format ab wie ein Offline-Lauf. Die KI-Analyse
(§16) arbeitet damit unverändert weiter. Privater Proof of Concept ohne
Compliance-Anforderungen.

### 17.2 Designentscheidungen (festgelegt)

- **Python + Web-Oberfläche, keine native Windows-App.** Aufgenommen wird im lokalen
  Python-Prozess, der Browser zeigt nur an. Voraussetzung ist natives Windows-Python; WSL
  hat weder Zugriff auf WASAPI noch auf den Bildschirm. Eine native App wäre erst für
  Tray-Icon, globale Hotkeys oder ein Overlay nötig.
- **Subprozess wie `run` und `analyze`.** Die Oberfläche startet `audioscribe live` als
  Kindprozess. Ereignisse kommen als `[Live] {json}`-Zeilen über stdout, gestoppt wird über
  stdin (`stop`), damit die Dateien sauber abgeschlossen werden. Das Prozessende gibt den
  VRAM frei.
- **Zwei getrennte Audiospuren statt Mix.** Mikrofon und WASAPI-Loopback werden getrennt
  aufgenommen (PyAudioWPatch). Damit ist „Ich“ gegen „Gegenseite“ ohne Modell und ohne
  Fehler trennbar. Loopback liefert bei Stille keine Pakete; die Lücken werden anhand der
  Sitzungsuhr mit Nullen gefüllt, sonst driften die Zeitstempel.
- **Residentes Modell.** `pipeline.transcribe` lädt und entlädt das Modell je Aufruf
  (NFR-2) und taugt nicht für Sekunden-Abschnitte. Der Live-Modus hält ein
  `faster_whisper.WhisperModel` für die ganze Sitzung. Standard: `large-v3-turbo` auf
  CUDA, `small` auf CPU.
- **Schnitt an Sprechpausen.** Silero-VAD (liegt faster-whisper bei) schneidet nach
  ≥ 0,6 s Pause oder spätestens nach 12 s. Stille wird nie transkribiert, das hält
  Whisper-Halluzinationen fern.
- **Vorschautext mit niedrigster Priorität.** Der laufende Abschnitt wird etwa alle 2 s
  vorläufig transkribiert und grau angezeigt. Vorschau-Aufträge laufen nur, wenn kein
  fertiger Abschnitt wartet, und pausieren ab 3 s Rückstand – wichtig für den CPU-Betrieb.
- **Sprecher live per Online-Clustering.** Je Abschnitt der System-Spur entsteht ein
  Stimm-Embedding (pyannote/wespeaker), das per Kosinus-Ähnlichkeit laufenden Zentroiden
  zugeordnet wird. So bleiben „Sprecher 1/2/3“ über die Sitzung stabil. Abschnitte unter
  1,5 s erben den letzten Sprecher; Überlappung bleibt Best-Effort.
- **Bildwechsel mit der Offline-Heuristik.** `mss` tastet den Monitor zweimal je Sekunde
  ab; verglichen wird mit `block_means`/`changed_blocks` und den Schwellen aus §15. Das
  Bild entsteht, wenn der Bildschirm wieder ruhig ist.
- **Beide Fassungen bleiben erhalten.** Beim Stopp wird das Live-Ergebnis zusätzlich als
  `transkript.live.md`/`transcript.live.json` gesichert. `audioscribe refine` fährt danach
  die Offline-Pipeline (Transkription, Alignment, Diarisierung) über die aufgenommenen
  Spuren und ersetzt `transkript.md`; die Screenshots bleiben.

### 17.3 Funktionale Anforderungen

| ID | Anforderung |
|----|-------------|
| FR-37 | `audioscribe live` schneidet einen wählbaren Monitor, das System-Audio und das Mikrofon mit, bis `stop` über stdin oder Strg+C eintrifft. Geräte und Monitor sind wählbar (`--mic`, `--loopback`, `--monitor`), jede Quelle ist abschaltbar. |
| FR-38 | Abgeschlossene Sprechabschnitte erscheinen als Text mit Zeitstempel und Sprecher. Der laufende Abschnitt erscheint als vorläufiger Text (abschaltbar mit `--no-partials`). |
| FR-39 | Die **Verzögerung** (Ende des Gesprochenen bis zur Anzeige) und der **Rückstand** (aufgenommenes, noch nicht transkribiertes Audio) werden laufend gemeldet und angezeigt. |
| FR-40 | Sprecher: Mikrofon = „Ich“. Die System-Spur wird per Online-Clustering in „Sprecher N“ getrennt; ohne HF-Token oder mit `--no-speakers` heißt sie „Gegenseite“. |
| FR-41 | Bildwechsel auf dem gewählten Monitor werden erkannt und als Standbild nach `frames/` gesichert, mit Startbild bei 0 s. Empfindlichkeit und Bildformat wie FR-24/FR-26. |
| FR-42 | Die Sitzung landet in `<output>/live-JJJJ-MM-TT_hh-mm-ss/` im Format eines Offline-Laufs (`transkript.md`, `transcript.json`, `marks.json`, `frames/`, `transkript.annotiert.md`) plus `audio/mikrofon.wav` und `audio/system.wav` (16 kHz mono). Geschrieben wird alle 30 s und beim Stopp. |
| FR-43 | `audioscribe refine ORDNER` schärft eine Sitzung nach: je Spur Transkription und Alignment, Diarisierung nur auf der System-Spur. Die Live-Fassung bleibt als `transkript.live.md`/`transcript.live.json` erhalten. |
| FR-44 | Die Oberfläche bekommt den Reiter „Live Transcription“ mit Monitorwahl samt Vorschau, Gerätewahl, Start/Stopp, laufendem Transkript, Verzögerungsanzeige, Pegeln und einer Thumbnail-Leiste mit Großansicht. Der bisherige Reiter „Transkription“ heißt „Offline Transcription“. |
| FR-45 | `audioscribe doctor` prüft Plattform, Audio-Geräte (inkl. Loopback) und Monitore. |

### 17.4 Nicht-funktionale Anforderungen

| ID | Anforderung |
|----|-------------|
| NFR-15 | Läuft mit NVIDIA-GPU und rein auf CPU. Auf CPU darf die Verzögerung wachsen; sie muss sichtbar sein, und die Vorschau drosselt sich selbst. |
| NFR-16 | Ohne das Extra `live` bleiben alle übrigen Befehle und Reiter lauffähig; der Reiter nennt dann den Installationsbefehl. |
| NFR-17 | Ein Absturz verliert höchstens die letzten 30 s Transkript; Audio und Screenshots liegen bis zum Absturz auf der Platte. |

### 17.5 Ein-/Ausgabe

- **Eingabe:** Monitor, Mikrofon, WASAPI-Loopback des Ausgabegeräts.
- **Ausgabe:** `<output>/live-…/` wie in FR-42, nach `refine` zusätzlich die Live-Fassung.
- **Hinweise:** Mit Lautsprechern statt Headset hört das Mikrofon die Gegenseite mit
  (doppelte Textstellen). Die AudioScribe-Oberfläche gehört nicht auf den überwachten
  Monitor, sonst lösen neue Thumbnails selbst Bildwechsel aus.

### 17.6 Akzeptanzkriterien

- [ ] Eine Sitzung mit Gespräch und Bildschirmwechseln zeigt Text mit wenigen Sekunden
      Verzögerung (GPU) und sichert die Wechsel als Standbilder.
- [ ] Der Sitzungsordner erscheint im Reiter „KI-Analyse“ als Quelle.
- [ ] `refine` ersetzt das Transkript, die Live-Fassung und die Bilder bleiben erhalten.
- [ ] Rein auf CPU läuft die Sitzung durch; die Anzeige weist den Rückstand aus.
