# PRD – AudioScribe

**Lokale Audio-Transkription mit Sprecher-Diarisierung**

| | |
|---|---|
| **Status** | Entwurf |
| **Datum** | 2026-06-30 |
| **Fortschreibung** | 2026-10-06: §21 Projekte, Startseite, Wiki-Ablage und Wiederaufnahme (FR-66 … FR-77, NFR-25 … NFR-29); KI-Verbrauch (FR-78) |
| **Autor** | Marek (madutkow@googlemail.com) |

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
| NFR-4 | **Plattform**: Ausführung unter **WSL2** (Ubuntu) auf Windows 11; natives Windows 11 für die Live-Transkription (§17); **macOS 14+ auf Apple Silicon** für alles (§19). |
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
- **Projekte** – Startseite, Projekt je LLM-Wiki, Ablage ins Wiki, Wiederaufnahme nach einem
  Absturz. Ausspezifiziert in **§21** (dazwischen: §15 Bildwechsel, §16 KI-Analyse, §17 Live,
  §18 Einstellungen, §19 macOS, §20 Souffleur).

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

- ~~**Kein Apple-MPS-Support** — Zielplattform bleibt Linux/WSL2 (NFR-4).~~ Aufgehoben
  durch §19 (Apple Silicon): `auto` wählt heute `cuda` > `mps` > `cpu`.
- **`--device auto` ist der neue Default** (statt bisher fest `cuda`): CUDA falls
  verfügbar, sonst MPS (Apple Silicon), sonst CPU. Explizites `--device cuda|mps|cpu`
  erzwingt.
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
| FR-33 | Die Browser-Oberfläche bietet einen Reiter „KI-Analyse“ mit Quellenauswahl, Prozessname, Kontext, Kontextdateien, Skills, Modell, Live-Protokoll und Abbruch. Der Ausgabeordner kommt aus dem Reiter „Einstellungen“ (FR-47) und wird als Zielhinweis angezeigt; Modell und Skill-Auswahl werden gemerkt. Der Fortschritt wird aus den Werkzeugaufrufen abgeleitet, nicht geschätzt: Plan des Agenten (TaskCreate/TaskUpdate bzw. TodoWrite) als Schrittliste mit Balken, aktiver Skill, angesehene Standbilder und geschriebene Dokumente. Nach dem Lauf nennt der Ergebniskasten den KI-Verbrauch (Tokens, ungefährer Preis in US-Dollar als Gegenwert zu API-Preisen, siehe FR-78). |
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

> Status: Proof of Concept · optionales Extra `live` · natives Windows oder macOS (§19), nicht WSL.

### 17.1 Ziel

§4.2 schloss Nah-Echtzeit-Transkription für die Basisstufe aus. Diese Stufe hebt das auf:
Neben der Offline-Verarbeitung fertiger Dateien schneidet AudioScribe eine laufende Sitzung
mit – einen gewählten Monitor, das System-Audio (Ausgabe) und das Mikrofon (Eingabe) –,
zeigt das Transkript mit wenigen Sekunden Verzögerung an, sichert bei jedem Bildwechsel
einen Screenshot und legt alles im selben Format ab wie ein Offline-Lauf. Die KI-Analyse
(§16) arbeitet damit unverändert weiter. Privater Proof of Concept ohne
Compliance-Anforderungen.

### 17.2 Designentscheidungen (festgelegt)

- **Python + Web-Oberfläche, keine native App.** Aufgenommen wird im lokalen
  Python-Prozess, der Browser zeigt nur an. Voraussetzung ist natives Windows-Python oder
  macOS-Python (§19); WSL hat weder Zugriff auf WASAPI noch auf den Bildschirm. Eine native
  App wäre erst für Tray-Icon, globale Hotkeys oder ein Overlay nötig.
- **Subprozess wie `run` und `analyze`.** Die Oberfläche startet `audioscribe live` als
  Kindprozess. Ereignisse kommen als `[Live] {json}`-Zeilen über stdout, gestoppt wird über
  stdin (`stop`), damit die Dateien sauber abgeschlossen werden. Das Prozessende gibt den
  VRAM frei.
- **Zwei getrennte Audiospuren statt Mix.** Mikrofon und System-Audio werden getrennt
  aufgenommen – unter Windows WASAPI-Loopback (PyAudioWPatch), unter macOS ScreenCaptureKit
  plus CoreAudio (§19). Damit ist „Ich“ gegen „Gegenseite“ ohne Modell und ohne Fehler
  trennbar. WASAPI-Loopback liefert bei Stille keine Pakete; die Lücken werden anhand der
  Sitzungsuhr mit Nullen gefüllt, sonst driften die Zeitstempel. Die Aufnahme steckt hinter
  einer kleinen Schnittstelle (`live/capture`: `mics`, `loopbacks`, `open`, `close`).
- **Residentes Modell.** `pipeline.transcribe` lädt und entlädt das Modell je Aufruf
  (NFR-2) und taugt nicht für Sekunden-Abschnitte. Der Live-Modus hält ein Whisper-Modell
  für die ganze Sitzung – `faster_whisper.WhisperModel` auf CUDA/CPU, `mlx_whisper` auf
  Apple Silicon (§19). Standard: `large-v3-turbo` auf CUDA und MLX, `small` auf CPU.
- **Schneller Start.** Nur Whisper, VAD und Audio-Geräte blockieren den Start; das
  Sprecher-Modell (pyannote samt Lightning, auf der CPU der größte Posten) lädt in einem
  Hintergrund-Thread, der erste System-Abschnitt wartet darauf. Liegen die Modelle im
  Cache, wird der Hugging-Face-Hub nicht befragt. Die Oberfläche zeigt den aktuellen
  Ladeschritt, das Protokoll die Dauer je Stufe.
- **Schnitt an Sprechpausen.** Silero-VAD (liegt faster-whisper bei) schneidet nach
  ≥ 0,6 s Pause oder spätestens nach 12 s. Stille wird nie transkribiert, das hält
  Whisper-Halluzinationen fern.
- **Vorschautext mit niedrigster Priorität.** Der laufende Abschnitt wird etwa alle 2 s
  vorläufig transkribiert und grau angezeigt. Vorschau-Aufträge laufen nur, wenn kein
  fertiger Abschnitt wartet, und pausieren ab 3 s Rückstand – wichtig für den CPU-Betrieb.
- **Aufholmodus ab 5 s wartendem Rückstand.** Whisper polstert jede Eingabe auf 30 s;
  kurze Abschnitte kosten also fast so viel wie lange. Wartende Abschnitte derselben Spur
  werden darum zu Stücken bis 25 s zusammengelegt und mit Beam 1 ohne Temperatur-Fallback
  dekodiert. Die Segmente werden gröber, der Rückstand wächst aber nicht mehr unbegrenzt.
  Rückstand ist nur, was fertig gesprochen *wartet*; der Abschnitt in Arbeit zählt nicht
  mit – sonst liefe jeder Abschnitt über 5 s im Sparmodus, auch bei leerer Warteschlange
  (so war es bis September 2026). Das gemessene Tempo (Rechenzeit je Audiosekunde) wird
  mitgemeldet.
- **Fazit aus dem Diagnose-Log, nicht aus Zählern.** Jeder Abschnitt hinterlässt eine
  Zeile in `diagnose.jsonl` mit Zeitpunkten, Rechenzeiten und den Qualitätswerten der
  Whisper-Segmente; das Fazit wird am Ende daraus abgeleitet. Eine zweite Buchführung,
  die vom Log abweichen könnte, gibt es nicht.
- **Sprecher live per Online-Clustering.** Je Abschnitt der System-Spur entsteht ein
  Stimm-Embedding (pyannote/wespeaker), das per Kosinus-Ähnlichkeit laufenden Zentroiden
  zugeordnet wird. So bleiben „Sprecher 1/2/3“ über die Sitzung stabil. Abschnitte unter
  1,5 s erben den letzten Sprecher; Überlappung bleibt Best-Effort.
- **Bildwechsel mit der Offline-Heuristik.** `mss` tastet den Monitor zweimal je Sekunde
  ab; verglichen wird mit `block_means`/`changed_blocks` und den Schwellen aus §15. Das
  Bild entsteht, wenn der Bildschirm wieder ruhig ist.
- **Messläufe per WAV-Replay.** Die Aufnahme ist hinter einer kleinen Schnittstelle
  (`mics`, `loopbacks`, `open`, `close`); statt WASAPI kann eine WAV-Datei auf der
  Sitzungsuhr eingespielt werden. Alles hinter der Aufnahme bleibt unverändert, darum sind
  Messwerte aus dem Replay auf den Echtbetrieb übertragbar.
- **Beide Fassungen bleiben erhalten.** Beim Stopp wird das Live-Ergebnis zusätzlich als
  `transkript.live.md`/`transcript.live.json` gesichert. `audioscribe refine` fährt danach
  die Offline-Pipeline (Transkription, Alignment, Diarisierung) über die aufgenommenen
  Spuren und ersetzt `transkript.md`; die Screenshots bleiben.

### 17.3 Funktionale Anforderungen

| ID | Anforderung |
|----|-------------|
| FR-37 | `audioscribe live` schneidet einen wählbaren Monitor **oder ein einzelnes Anwendungsfenster**, das System-Audio und das Mikrofon mit, bis `stop` über stdin oder Strg+C eintrifft. Geräte und Bildquelle sind wählbar (`--mic`, `--loopback`, `--monitor`, `--window HWND`), jede Quelle ist abschaltbar. Ein Fenster wird per `PrintWindow` auch verdeckt aufgenommen; minimiert pausieren die Standbilder, geschlossen endet nur die Bildaufnahme. |
| FR-38 | Abgeschlossene Sprechabschnitte erscheinen als Text mit Zeitstempel und Sprecher. Der laufende Abschnitt erscheint als vorläufiger Text (abschaltbar mit `--no-partials`). |
| FR-39 | Die **Verzögerung** (Ende des Gesprochenen bis zur Anzeige) und der **Rückstand** (fertig gesprochenes Audio, das auf die Transkription wartet – ohne den Abschnitt in Arbeit) werden laufend gemeldet und angezeigt. |
| FR-40 | Sprecher: Mikrofon = „Ich“. Die System-Spur wird per Online-Clustering in „Sprecher N“ getrennt; ohne HF-Token oder mit `--no-speakers` heißt sie „Gegenseite“. |
| FR-41 | Bildwechsel auf dem gewählten Monitor werden erkannt und als Standbild nach `frames/` gesichert, mit Startbild bei 0 s. Empfindlichkeit und Bildformat wie FR-24/FR-26. |
| FR-42 | Die Sitzung landet in `<output>/live-JJJJ-MM-TT_hh-mm-ss/` im Format eines Offline-Laufs (`transkript.md`, `transcript.json`, `marks.json`, `frames/`, `transkript.annotiert.md`) plus `audio/mikrofon.wav` und `audio/system.wav` (16 kHz mono). Geschrieben wird alle 30 s und beim Stopp. |
| FR-43 | `audioscribe refine ORDNER` schärft eine Sitzung nach: je Spur Transkription und Alignment, Diarisierung nur auf der System-Spur. Die Live-Fassung bleibt als `transkript.live.md`/`transcript.live.json` erhalten. |
| FR-44 | Die Oberfläche bekommt den Reiter „Live Transcription“ mit Monitorwahl samt Vorschau, Gerätewahl, Start/Stopp, laufendem Transkript, Verzögerungsanzeige, Pegeln und einer Thumbnail-Leiste mit Großansicht. Der bisherige Reiter „Transkription“ heißt „Offline Transcription“. Der Ausgabeordner der Sitzung ist der gemeinsame Ausgabeordner Transkription aus dem Reiter „Einstellungen“ (FR-47) und wird als Zielhinweis `<output>/live-…` angezeigt. |
| FR-45 | `audioscribe doctor` prüft Plattform, Berechtigungen (macOS), Audio-Geräte (inkl. Loopback) und Monitore. |
| FR-46 | Jede Live-Sitzung und jedes Nachschärfen hinterlassen ein Fazit: Ladezeit der Modelle, Aufnahmedauer, Rechenzeit und Tempo (Rechenzeit je Audiosekunde, nur Dekodieren; daneben inkl. Vorschau), Verzögerung Ø/Median/max, Abschnitte (davon zusammengelegt und sparsam dekodiert), höchster Rückstand, Zeit im Aufholmodus mit Anteil an der Aufnahme bzw. Dauer je Stufe. Es steht als `bilanz.json` im Sitzungsordner, als Zeile im Protokoll und als Kasten „Fazit“ im Reiter. |
| FR-47 | **Diagnose-Log.** Jede Live-Sitzung schreibt `diagnose.jsonl` (eine JSON-Zeile je fertigem Abschnitt): Lage im Audio, Zeitpunkte Abschluss/Start/Ende auf der Sitzungsuhr, Wartezeit, Rechenzeit (Dekodieren und Sprecher-Label getrennt), Latenz (bei zusammengelegten Stücken auch ab dem ersten Teil), Modell, Sparmodus, Teile, Wortzahl, Schlussgrund (`pause`/`zeitlimit`/`flush`) und je Whisper-Segment `avg_logprob`, `compression_ratio`, `no_speech_prob`, `temperature`. Vorschauen stehen als eigene Zeilen mit Fensterlänge und Rechenzeit, das Nachschärfen hängt je Segment und je Stufe eine Zeile an. Das Fazit (FR-46) ist aus diesem Log abgeleitet. |
| FR-48 | **Ehrliche Metriken.** Rückstand = Summe des fertig gesprochenen, noch nicht begonnenen Audios; Aufholmodus = Zeitanteil, in dem dieser Rückstand über einer Chunk-Länge liegt; Echtzeitfaktor getrennt für das Dekodieren allein und inkl. Vorschau. `audioscribe live --eco` erzwingt für Messläufe den Sparmodus für alle Abschnitte. |
| FR-49 | **WAV-Replay und Reintext.** `audioscribe live --wav DATEI [--wav-mic DATEI] [--speed X]` schickt Aufnahmen durch dieselbe Live-Pipeline (Schnitt, Warteschlange, Fazit, Diagnose-Log), als kämen sie in Echtzeit; ohne Standbilder, auch unter Linux; die Sitzung endet mit der Datei. Jedes Transkript (live und nachgeschärft) liegt zusätzlich als `transkript.txt` ohne Zeitstempel und Sprecher vor, die Live-Fassung als `transkript.live.txt`. |

### 17.4 Nicht-funktionale Anforderungen

| ID | Anforderung |
|----|-------------|
| NFR-15 | Läuft mit NVIDIA-GPU und rein auf CPU. Auf CPU darf die Verzögerung wachsen; sie muss sichtbar sein, die Vorschau drosselt sich selbst, und ab 5 s Rückstand holt die Sitzung durch Zusammenlegen und sparsames Dekodieren auf. |
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
- [ ] Ein einzelner 12-s-Abschnitt bei leerer Warteschlange zeigt Rückstand 0 und wird
      mit voller Qualität dekodiert; `diagnose.jsonl` enthält je Abschnitt `schluss`,
      `eco` und die Segment-Qualitätswerte, und das Fazit stimmt mit den Logzeilen überein.

## 18. Ausbaustufe: Reiter „Einstellungen“

> Abgelöst durch §21: Den Reiter mit den drei Standardordnern (FR-47) gibt es nicht mehr.
> Ordner gehören zum Projekt bzw. zur Ansicht „Aufnahme transkribieren“; global bleiben KI,
> Sprache und die Karte „Umgebung“ (FR-69). Der Umgebungs-Check samt `doctor --json` gilt
> unverändert.

### 18.1 Ziel

Die drei Standardordner der Oberfläche liegen an **einer** Stelle statt verteilt über die
Reiter. Bisher nahm der Live-Reiter stillschweigend den Ausgangsordner des Offline-Reiters,
und die KI-Analyse suchte ihre Quellen dort, hatte aber ein eigenes Ausgabefeld. Dazu
kommt eine Sichtprüfung der Umgebung, damit niemand erst ins Terminal muss, um zu sehen,
warum die Diarisierung oder die GPU nicht läuft.

### 18.2 Designentscheidungen (festgelegt)

- **Ein Ausgabeordner Transkription für Offline und Live.** Live-Sitzungen landen
  weiter als `live-JJJJ-MM-TT_hh-mm-ss/` neben den Offline-Ergebnissen (FR-42); die
  KI-Analyse findet beides ohne zweite Suche.
- **Modell, Sprache, Gerät bleiben Job-Optionen** in den Reitern – sie wechseln je Lauf.
- **Umgebungs-Check als Subprozess.** `audioscribe doctor --json` läuft als Wegwerf-
  Prozess, weil torch/pyannote nicht in den Server gehören (VRAM, siehe §14). Das
  Ergebnis wird gecacht; „Aktualisieren“ erzwingt einen neuen Lauf.

### 18.3 Funktionale Anforderungen

| ID | Anforderung |
|----|-------------|
| FR-47 | Die Oberfläche bekommt den Reiter „Einstellungen“ mit **Eingangsordner**, **Ausgabeordner Transkription** (gemeinsam für Offline und Live) und **Ausgabeordner Analysen**, je mit Ordner-Browser. Änderungen gelten sofort für alle Reiter und werden serverseitig gemerkt. Die Reiter Offline, Live und KI-Analyse zeigen ihren Zielordner nur noch als Hinweis mit Sprung „ändern“ in die Einstellungen. Eine Karte „Umgebung“ zeigt die Zeilen von `audioscribe doctor` (Status OK/WARN/FAIL, Name, Detail) mit Zeitstempel und „Aktualisieren“. `audioscribe doctor --json` gibt dieselben Zeilen als JSON-Liste aus; ein geplatzter Einzelcheck erscheint dort als FAIL-Zeile. |

### 18.4 Akzeptanzkriterien

- [ ] Ausgabeordner in den Einstellungen ändern: Offline-Dateiliste, Live-Zielhinweis und
      Analyse-Quellen wechseln ohne Neuladen mit; nach einem Neustart stehen die Werte
      wieder da.
- [ ] Eine Live-Sitzung landet im gewählten Ausgabeordner Transkription.
- [ ] Die Karte „Umgebung“ zeigt dieselben Zeilen wie `audioscribe doctor` im Terminal.

## 19. Ausbaustufe: macOS auf Apple Silicon

> Status: implementiert, Validierung auf dem Gerät offen (§19.4) · Extra `mac` · MacBook
> Pro mit M4/M5 (M1–M3 laufen, langsamer) · macOS 14+.

### 19.1 Ziel

AudioScribe läuft vollständig auf einem Mac mit Apple Silicon – Offline-Pipeline,
KI-Analyse und vor allem der Live-Modus mit Quasi-Echtzeit. Alles bleibt innerhalb von
Python: keine Homebrew-Werkzeuge, kein virtuelles Audiogerät (BlackHole), nur
pip-/uv-Pakete. Ein Doppelklick startet die Oberfläche.

### 19.2 Designentscheidungen (festgelegt)

- **Whisper über MLX, torch über MPS.** CTranslate2 (faster-whisper, WhisperX) kennt kein
  Metal; auf dem Mac liefe `large-v3-turbo` damit nur auf der CPU und wäre nicht
  live-tauglich. Darum rechnet Whisper über `mlx-whisper` (Metal, 14–37× Echtzeit), die
  torch-Modelle (pyannote-Embedding, wav2vec2, Diarisierung) über MPS mit
  `PYTORCH_ENABLE_MPS_FALLBACK=1`. `ct2_device()` hält CTranslate2 auf `cpu`, falls es doch
  gebraucht wird (Backend `faster-whisper` erzwungen).
- **Ein Transcriber-Protokoll, zwei Backends.** `live/asr.make_transcriber(backend, …)`
  liefert `LiveTranscriber` (faster-whisper) oder `MlxTranscriber`. Beide geben dasselbe
  `Ergebnis` mit Segment-Qualitätswerten; das Diagnose-Log (FR-47) bleibt backend-neutral.
  mlx-whisper kennt keinen Beam-Search: fertige Abschnitte bekommen den Temperatur-Fallback
  mit `best_of` 5, die Vorschau reines Greedy.
- **Nachschärfen und `run` ebenfalls über MLX.** `pipeline/transcribe_mlx.py` ersetzt nur
  Stufe 2 (VAD-Fenster bis 30 s wie WhisperX) und liefert das WhisperX-Format; Alignment
  und Diarisierung laufen unverändert, nur auf MPS. Standardmodell bleibt `large-v3`.
- **System-Audio über ScreenCaptureKit.** PortAudio kann auf dem Mac kein Loopback.
  ScreenCaptureKit (macOS 13+) liefert den gemischten Ton aller Apps als Nebenprodukt einer
  Bildschirmaufnahme (2×2 Pixel, 1 Bild/s); genutzt werden nur die Audiopuffer (Float32,
  48 kHz, planar → mono). Core-Audio-Process-Taps (macOS 14.2+) brauchen C-Callbacks und
  werden nicht verfolgt. Das Mikrofon kommt über `sounddevice` (PortAudio im Wheel).
- **Berechtigungen vor der Sitzungsuhr.** Mikrofon und Bildschirmaufnahme sind
  TCC-Berechtigungen der startenden App (Terminal, iTerm, VS Code), die Bildschirmaufnahme
  wirkt erst nach deren Neustart. `ensure_permissions()` fragt sie ab, bevor die Aufnahme
  beginnt, damit Dialoge nicht als Stille in die Zeitleiste fallen; `doctor` und die
  Oberfläche nennen die App beim Namen.
- **Ein `uv.lock`, drittes Extra `mac`.** Alle Mac-Pakete tragen `sys_platform == 'darwin'`
  (mlx zusätzlich `arm64`); unter Linux/Windows ist das Extra wirkungslos. torch kommt weiter
  aus `cpu` – das arm64-Wheel enthält MPS. `.venv-mac` ist von `.venv` (WSL) und `.venv-win`
  getrennt, aus demselben Grund wie bisher.
- **Latenzboden ist der Schnitt, nicht das Modell.** Pausenerkennung (0,6 s) plus Puffer
  (0,3 s, auf dem Mac 0,15 s) plus VAD-Takt ergeben rund eine Sekunde, bevor dekodiert wird.
  Die Stellschrauben dafür sind Einstellungen (FR-55), nicht Konstanten.

### 19.3 Funktionale Anforderungen

| ID | Anforderung |
|----|-------------|
| FR-50 | **macOS-Start.** `start.sh` (und `AudioScribe.command` für den Doppelklick) installiert bei Bedarf `uv`, lässt `uv` Python 3.12 besorgen, legt `.venv-mac` an, wählt die Extras `cpu mac live review agent`, setzt `PYTORCH_ENABLE_MPS_FALLBACK=1` und startet die Oberfläche; `--doctor` und `--devices` als Kurzbefehle. `audioscribe doctor` zeigt Plattform (macOS-Version, Chip, Terminal-App), Rechengerät `mps`, ASR-Backend und Berechtigungen. |
| FR-51 | **Aufnahme ohne Zusatztreiber.** System-Audio über ScreenCaptureKit, Mikrofon über sounddevice, Fensterliste und Fensteraufnahme über Quartz, Monitore über mss. Dieselbe Geräteliste (`mics`, `loopbacks` mit einem synthetischen Eintrag „System-Audio (ScreenCaptureKit)“) wie unter Windows; Oberfläche und doctor nennen fehlende Berechtigungen samt Systemeinstellungs-Pfad und App. |
| FR-52 | **MLX-Backend.** `AUDIOSCRIBE_ASR_BACKEND=auto\|faster-whisper\|mlx` bzw. `--backend`; `auto` nimmt `mlx` auf Apple Silicon, sonst `faster-whisper`. Modellnamen werden auf `mlx-community/whisper-*` gemappt (`AUDIOSCRIBE_MLX_REPO` erzwingt ein Repo). Gilt für `live`, `refine` und `run`; Gewichte werden offline-first aus dem Hugging-Face-Cache geladen, der Download meldet Fortschritt. |
| FR-53 | **Gerät `mps`.** `--device auto\|cuda\|mps\|cpu` in CLI und Oberfläche; `auto` wählt cuda > mps > cpu. Die Oberfläche deaktiviert nicht verfügbare Geräte (Probe im Wegwerf-Prozess). CTranslate2 bekommt nie `mps`. |
| FR-54 | **Mac-Pfade und Browser.** Der Ordner-Dialog bietet Schreibtisch, Dokumente, Downloads, Filme, iCloud Drive und `/Volumes/*`; eingefügte Pfade werden auf dem Mac nicht nach `/mnt/c` umgeschrieben. Das Prozessbild findet Chrome, Edge, Chromium und Brave in `/Applications` bzw. `~/Applications`. |
| FR-55 | **Live-Stellschrauben.** `AUDIOSCRIBE_LIVE_PAUSE_S` (0,6), `AUDIOSCRIBE_LIVE_PARTIAL_INTERVAL_S` (2,0), `AUDIOSCRIBE_LIVE_PARTIAL_MIN_S` (1,0) und `AUDIOSCRIBE_LIVE_VAD_EVERY_TICK` (0) steuern Schnitt und Vorschau; `bilanz.json` trägt `backend`, `geraet` und `modell`, damit Messläufe vergleichbar bleiben. |

### 19.4 Nicht-funktionale Anforderungen

| ID | Anforderung |
|----|-------------|
| NFR-18 | **Latenzziel Mac.** Mit `large-v3-turbo` über MLX liegt die Verzögerung (Median, `bilanz.json`) auf einem M4 Pro/Max oder M5 bei ≤ 3 s, auf dem Basis-M4 bei ≤ 5 s; der Rückstand pendelt sich ein (Aufholmodus ≈ 0). Erwartung je Abschnitt: M4 2,5–3,5 s, M4 Pro/Max 1,8–2,5 s, M5 1,7–2,2 s; mit FR-55 ~1,5–2 s. |
| NFR-19 | **Keine Systempakete.** Alles kommt als pip-/uv-Wheel: PortAudio in sounddevice, ffmpeg in imageio-ffmpeg, die Apple-Frameworks über PyObjC. Einzige Ausnahme ist der optionale Browser fürs Prozessbild (Safari kann nicht headless rendern). |
| NFR-20 | **Windows, WSL und Linux unverändert.** Gleiche Befehle, gleiche Ausgaben, ein `uv.lock`; die bestehenden Tests laufen ohne Änderung durch. |

### 19.5 Akzeptanzkriterien (Validierung auf dem Gerät)

- [ ] `AudioScribe.command` (Doppelklick) oder `./start.sh`: `uv` und Python kommen von
      selbst, `.venv-mac` entsteht, der Erststart-Hinweis erscheint, der Browser öffnet
      `http://127.0.0.1:8766`.
- [ ] `./start.sh --doctor`: Plattform `macOS 15.x (arm64, Apple M4 …)`, `PyTorch/Device
      auto=mps`, `ASR-Backend mlx-whisper …`, ffmpeg gebündelt, kein FAIL; Reiter
      Einstellungen zeigt dieselben Zeilen.
- [ ] `.venv-mac/bin/audioscribe live --list-devices`: Mikrofone, ein `System-Audio
      (ScreenCaptureKit)`, Monitore, Fenster. Nach Freigabe der Bildschirmaufnahme und
      Neustart der Terminal-App meldet `doctor` Live OK.
- [ ] Spike `python -m audioscribe.live.capture.sck --probe 5` bei laufendem Video: WAV ist
      nicht stumm, das Format (Float32 planar, 48 kHz) steht im Protokoll.
- [ ] Oberfläche: `cuda` deaktiviert, `mps` wählbar; Schnellzugriffe Schreibtisch, Downloads,
      `/Volumes/*`; ein Windows-Pfad wird nicht umgeschrieben; der Live-Reiter zeigt das
      ScreenCaptureKit-Label und den Backend-Hinweis.
- [ ] Zwei Minuten Live mit Teams oder YouTube (`auto`/`auto`, Sprecher an, Nachschärfen an):
      beide Pegel schlagen aus, erster Text unter 10 s, Verzögerung meist unter 3 s, der
      Rückstand wächst nicht, Standbilder bei Folienwechseln; das Nachschärfen läuft ohne
      MPS-Fehler durch.
- [ ] `bilanz.json`: `verzoegerung_median_s`, `verzoegerung_max_s`, `tempo`,
      `aufholmodus_s`, `backend`, `geraet`, Dauer je Refine-Stufe erfüllen NFR-18;
      `audio/system.wav` ist nicht stumm.
- [ ] Replay-Benchmark auf derselben Referenz-WAV: `AUDIOSCRIBE_ASR_BACKEND=mlx … live --wav
      ref.wav --model large-v3-turbo` gegen `…=faster-whisper … --model small --device cpu`;
      `bilanz.json`, `diagnose.jsonl` und `transkript.txt` (WER) vergleichen; Sweep mit
      `AUDIOSCRIBE_LIVE_PAUSE_S=0.45 AUDIOSCRIBE_LIVE_VAD_EVERY_TICK=1`.
- [ ] Offline `run` auf einer 10-min-Datei mit `--device auto` (MLX + MPS) und `--device
      cpu`: strukturgleiche Ausgabe, MLX deutlich schneller.
- [ ] Negativpfade: `--device cuda` → klare Meldung; entzogene Bildschirmaufnahme →
      Berechtigungshinweis statt Stacktrace; `uv run audioscribe doctor` ohne Extras →
      ASR-Backend WARN, `./start.sh` repariert.

## 20. Ausbaustufe: Souffleur – Live-Abgleich mit dem LLM-Wiki

> Fortgeschrieben durch §21: „Projekt = Installation“ (§20.2) gilt nicht mehr – das Wiki
> gehört zum Projekt, die Verknüpfung (FR-56) steht in den Projekteinstellungen statt in
> einer Karte „Wiki (Souffleur)“. Die automatische Übergabe in einen Übergabeordner (FR-60
> und das zugehörige Akzeptanzkriterium) ist entfallen; Transkript und Markierungen gehen
> über die Wiki-Ablage nach `raw/` (FR-71). Ohne Projekt (Kommandozeile, Tests) gilt weiter
> der Wiki-Pfad der Installation.

### 20.1 Ziel

Der Souffleur hört beim Meeting über das Live-Transkript mit, gleicht das Gesagte mit dem
Wiki des Projekts ab und gibt dem Moderator Hinweise: Widerspruch zum Wiki, offener Punkt,
gestellte Frage mit Antwort aus dem Wiki, dazu die Essenz der letzten Minuten auf Knopfdruck.
Auftrag und Leitplanken: `doc/Audioscribe-Souffleur-Anforderungen.md` (Abschnitt 4 dort ist
verbindlich). Stufe 1 umfasst K1, A1–A4, B1, B2, C1; B3 (Lösungsknopf), Wiki-Pflege/Lint und
mehrere Wikis sind nicht enthalten.

### 20.2 Designentscheidungen (festgelegt)

- **Projekt = Installation.** Es gibt noch keine Projekt-Einheit im Code; der Wiki-Pfad gilt
  je Installation und wird an genau einer Stelle gelesen (`souffleur/konfig.py`), damit er
  später je Projekt gespeichert werden kann.
- **Wiki nur lesen, Form Karpathy-Muster.** Markdown-Ordner mit `index.md`, `wiki/`, `raw/`,
  `log.md`; gelesen werden nur Seiten. Fundstelle = Datei › Überschrift (Zeile). Lexikalische
  Suche (BM25 über Abschnitte) ohne neue Abhängigkeit. Das Glossar bestätigter Fehlerkennungen
  ist Teil des Wikis (`glossar.md`, Tabelle `Fehlerkennung | Korrekt`), keine eigene Einstellung.
- **Wiki-Stand:** Index beim Sitzungsstart; Änderungen gelten ab dem nächsten Meeting.
- **Markierungen als Begleitdateien** (`souffleur.json`, `souffleur-protokoll.md`,
  `souffleur-diagnose.jsonl`, `souffleur-essenz.jsonl`) im Sitzungsordner – nie im Transkript.
- **Übergabe (A4)** in einen eigenen Übergabeordner, rein anhängend, nie in den Wiki-Pfad;
  Format `markierungen.json` (format_version 1) ist in `souffleur/uebergabe.py` gekapselt und
  mit dem Lint-Verantwortlichen abzustimmen. Kein Rückkanal in dieser Stufe.
- **KI-Dienst austauschbar** (`KiDienst`-Protokoll, Factory, `AUDIOSCRIBE_SOUFFLEUR_BACKEND`).
  Stufe 1: Claude Agent SDK, werkzeugloser Einzelaufruf je Fenster mit JSON-Schema-Antwort,
  Sitzungsdateien der CLI abgeschaltet und ersatzweise gelöscht, Arbeitsordner nie der
  Wiki-Pfad. Oberfläche und Ausgaben sagen nur „KI“.
- **Ein KI-Aufruf je Fenster** mit lokal vorgesuchten Auszügen; lokale Validierung (Aussage
  wörtlich im Segment, Zitat wörtlich im Auszug, Widerspruch nur mit Zitat, Dedup).
- **Souffleur im Server-Prozess** (Worker-Thread je Sitzung, gefüttert vom LiveRunner),
  Hinweise als `hinweis`-Ereignis über das bestehende Polling.
- **Transkript-Replay als Kindprozess** (`live --transcript`), Abzweig vor dem Audio-Backend,
  kein Nachschärfen – derselbe Weg für Test und Betrieb.
- **Einstellungen im Konfigurationsordner der Plattform** (`%APPDATA%`, `~/Library/Application
  Support`, `~/.config`), alte `ui-state.json` wird übernommen.

### 20.3 Funktionale Anforderungen

| ID | Anforderung |
|----|-------------|
| FR-56 | **K1 Wiki-Verknüpfung.** Einstellungen-Karte „Wiki (Souffleur)“ mit Pfadfeld, Ordner-Browser und sofortiger Prüfung (drei Zustände: kein Wiki, verbunden mit Name/Seiten/Glossar, nicht erreichbar mit Grund). Der Pfad bleibt gespeichert, gilt ab der nächsten Sitzung und wird nirgends im Code festgelegt. Derselbe Zustand ist im Live-Reiter sichtbar. Ohne Wiki läuft alles weiter; Wiki-Funktionen zeigen ihren Zustand. |
| FR-57 | **A1 Stimmigkeits-Check.** Der Abgleich läuft ohne Zutun je Fenster; Smalltalk, Organisatorisches und passende Aussagen erzeugen keinen Hinweis. |
| FR-58 | **A2 Widerspruch.** Markierung mit Fundstelle (Datei › Überschrift, Zeile) und wörtlichem Wiki-Zitat; Gegenüberstellung gesagt / im Wiki; KI-Einschätzung getrennt als KI gekennzeichnet; ohne Zitat kein Widerspruch. |
| FR-59 | **A3 Offene Punkte.** Als ungeklärt Benanntes, offene Zuständigkeiten und Fragen ohne Befund werden markiert und als Liste während und nach dem Meeting angezeigt. |
| FR-60 | **A4 Übergabe.** Nach der Sitzung Ordner `<Übergabeordner>/<sitzung>/` mit byte-gleicher Transkriptkopie, `markierungen.json`, `markierungen.md`, `README.md`; rein anhängend, nie im Wiki-Pfad; jede Markierung mit Zeitbezug. |
| FR-61 | **B1 Fragen-Erkennung.** Echte Fragen werden markiert, rhetorische Fragen und Floskeln möglichst nicht. |
| FR-62 | **B2 Antwortvorschlag.** Zu einer Frage zeigt der Souffleur Wiki-Wissen mit Fundstelle; liegt nichts vor, steht genau das da („Im Wiki liegt dazu nichts vor“) ohne KI-Ersatztext, und die Frage zählt als offener Punkt. |
| FR-63 | **C1 Essenz.** Knöpfe „Essenz 2 min“ und „Essenz 5 min“; die Zusammenfassung bezieht sich genau auf das Fenster, ist kurz, als KI gekennzeichnet und wird getrennt in `souffleur-essenz.jsonl` abgelegt, nie in die Übergabe. |
| FR-64 | **Transkript-Replay.** `audioscribe live --transcript DATEI|ORDNER [--speed X] [--replay-delay S]` und die Kachel „Transkript abspielen“ (Datei, Tempo 1–20×) spielen ein gespeichertes Transkript zu seinen Zeitstempeln ab, als käme es live; Sitzungsordner, Fazit und Souffleur verhalten sich wie im Betrieb; kein Audio, kein Modell, kein Nachschärfen. |
| FR-65 | **Markierungsarten** Widerspruch, offener Punkt, Frage sind in Farbe, Form und Wort unterscheidbar und erweiterbar; der Moderator kann die Souffleur-Spalte samt Transkript-Chips mit einem Griff (Alt+S) ausblenden und die Auswertung abschalten. |

### 20.4 Nicht-funktionale Anforderungen

| ID | Anforderung |
|----|-------------|
| NFR-21 | **Leitplanken nachweisbar.** Das Paket `souffleur/` öffnet das Wiki nur lesend und schreibt im Sitzungsordner nur die vier Begleitdateien; `transkript.md`/`transcript.json` bleiben byte-gleich (Test). Wiki-Zitate tragen Fundstellen, KI-Text steht in eigenen Feldern. |
| NFR-22 | **Verzögerung gemessen.** Je Hinweis: Sprachende → Hinweis (Sitzungsuhr) mit Anteilen Spracherkennung, Warten, Suche, KI-Prozessstart, KI-Antwort; reale Verzögerung ab Empfang; Mittel/Median/Max in `souffleur.json` und Protokoll. Kein fester Grenzwert; Richtwert 15 s. |
| NFR-23 | **Robust.** Ohne Wiki, ohne KI-Dienst oder bei KI-Fehlern (3 in Folge → 60 s Pause) läuft die Sitzung weiter; der Zustand wird angezeigt. Keine Transkript- oder Wiki-Auszüge bleiben außerhalb des Sitzungsordners liegen. |
| NFR-24 | **Plattformneutral.** Windows und macOS nativ (uv-Umgebung), Pfade über `pathlib`, Prozesse mit Listen-argv; keine Linux-Annahmen. |

### 20.5 Akzeptanzkriterien

- [ ] Wiki-Pfad auf das Test-Wiki setzen → Zustand „verbunden“ mit Seiten und Glossar;
      Pfad auf einen nicht vorhandenen Ordner → verständliche Meldung, Live läuft weiter.
- [ ] Test-Transkript mit „Transkript abspielen“ (Tempo wählbar) abspielen: Widersprüche
      werden gefunden und der richtigen Wiki-Stelle zugeordnet, passende Aussagen nicht
      gemeldet; echte Fragen markiert, rhetorische nicht; offene Punkte in der Liste.
- [ ] `souffleur-protokoll.md` enthält je Markierung Zeitstempel, Art, Aussage, Fundstelle,
      Verzögerung (mit KI-Startanteil) zum Abgleich mit dem Lösungsschlüssel.
- [ ] `transkript.md` vor und nach der Sitzung byte-gleich; das Wiki unverändert.
- [ ] Übergabeordner enthält Transkriptkopie und `markierungen.json`; ein zweiter Lauf hängt
      `-2` an statt zu überschreiben.
- [ ] `pytest` grün: `tests/test_souffleur.py`, `tests/test_souffleur_ui.py`,
      `tests/test_replay_transkript.py`, `tests/test_souffleur_html.py`.

## 21. Ausbaustufe: Projekte, Startseite, Wiki-Ablage und Wiederaufnahme

> Status: umgesetzt · Umbau der Browser-Oberfläche (`audioscribe ui`) · löst „Projekt =
> Installation“ (§20.2), den Reiter „Einstellungen“ (§18) und die automatische Übergabe
> (FR-60) ab · echte Aufnahme- und Absturztests auf dem Gerät stehen aus (§21.5).

### 21.1 Ziel

Die Oberfläche beginnt mit einer **Startseite** statt mit vier gleichrangigen Reitern. Von
dort führen vier Einstiege weiter: neues Projekt, Projekt öffnen, eine einzelne Aufnahme
transkribieren, Demo abspielen. Ein **Projekt** gehört zu genau einem LLM-Wiki und trägt
seine eigenen Einstellungen (Ordner, Wiki-Ablage, KI, Sprache); die Arbeitsansichten zeigen
nur noch, was zum gewählten Einstieg gehört. Nach einer Sitzung geht das Material auf Wunsch
als neue Quelle ins Wiki – Transkript und Markierungen nach `raw/`, Bilder in einen
Assets-Ordner, die Zuordnung Zeitstempel ↔ Bild bleibt erhalten – und/oder in die
KI-Nachbereitung. Eine Sitzung, die durch einen Absturz unterbrochen wurde, lässt sich nach
dem Neustart fortsetzen oder sauber abschließen.

### 21.2 Designentscheidungen (festgelegt)

- **Ein Projekt = ein LLM-Wiki.** Der Wiki-Ordner (Wurzel mit `raw/` und `wiki/`) ist die
  Identität des Projekts. Beim Anlegen wird ein vorhandenes Wiki verknüpft oder ein neues
  Gerüst angelegt (`projekt/vorlage.py`: `raw/`, `wiki/` mit Unterordnern, `index.md`,
  `log.md`, `uebersicht.md`, `glossar.md`, `README.md`; nur was fehlt). Ein zweites Projekt
  im selben Wiki wird abgewiesen.
- **Projektdatei im Wiki.** `<wiki>/.audioscribe/projekt.json` (atomar geschrieben). Der
  Punktordner wird vom Wiki-Index übersprungen. Pfade stehen relativ zur Wiki-Wurzel in der
  Datei, wo das geht – das Projekt zieht mit dem Wiki um (anderer Rechner, Git). Die
  Installation merkt sich nur die zuletzt geöffneten Projekte (`einstellungen.json`,
  Schlüssel `zuletzt_projekte`).
- **Ordner des Projekts.** Sitzungsordner (Pflicht; Vorschlag `<wiki>-sitzungen` neben dem
  Wiki, weil Mitschnitte groß sind) für Live-Sitzungen und – darunter in `analysen/` – die
  KI-Analysen. Assets-Ordner für Bilder (Vorschlag `raw/assets`): muss im Wiki liegen, nie
  unter `wiki/`. Auch der Sitzungsordner darf nicht unter `wiki/` liegen.
- **Der Server hält den Kontext** (`ui/kontext.py`): Startseite, Projekt, einzelne Aufnahme
  oder Demo – genau einer, so wie er genau eine Live-Sitzung, einen Stapel und eine Analyse
  hält. Ein Neuladen der Seite ändert nichts; nach einem Neustart des Servers beginnt die
  Oberfläche auf der Startseite. Ein Kontextwechsel während eines Laufs wird abgewiesen
  (409); nur die Demo-Sitzung wird beim Verlassen abgebrochen. Im Projekt bestimmt der
  Server die Ordner – Angaben des Browsers werden dann nicht verwendet.
- **Einstellungen in zwei Ebenen.** Global je Installation: KI-Dienst, Modell für den
  Souffleur, Modell für die KI-Analyse, Sprache der Aufnahmen. Ein Projekt kann jeden dieser
  Werte überschreiben; fehlt er im Projekt, gilt der globale (`projekt/einstellungen.py:
  effektiv`). Sprache und Modell werden nicht mehr „vom letzten Lauf“ gemerkt; Gerät,
  Whisper-Modell und Bildoptionen bleiben Lauf-Optionen wie in §18.
- **Wiki-Ablage ist ein Export** (`projekt/wiki_ablage.py`). Quelle für KI-Analyse und
  Review bleibt der Sitzungsordner (dort gilt überall `frames/`). Ziel ist
  `raw/<JJJJ-MM-TT>_<kurzname>/` – das Namensschema der Rohquellen im Wiki; der Kurzname
  kommt aus dem Sitzungstitel, sonst aus dem Ordnernamen.
- **Bewusste Änderung der Leitplanke „nie in den Wiki-Pfad“.** Bisher schrieb AudioScribe
  nichts unter den Wiki-Pfad (FR-60, NFR-21). Neu gilt: Die Seiten unter `wiki/` werden
  weiter **nur gelesen**. Nach `raw/` und in den Assets-Ordner wird **nur angehängt**
  (nichts überschrieben, Namenskollision → `-2`, `-3` …) und **nur auf Nutzeraktion** bzw.
  auf die ausdrücklich gewählte Projekteinstellung „immer“. Das Paket `souffleur/` selbst
  schreibt weiterhin nichts ins Wiki; `souffleur/uebergabe.py` baut nur noch die Inhalte von
  `markierungen.json/.md`.
- **Die automatische Übergabe entfällt.** Übergabeordner, `AUDIOSCRIBE_UEBERGABE_DIR` und der
  Abschluss-Schritt des Souffleurs (FR-60) gibt es nicht mehr; die Markierungen gehen mit der
  Wiki-Ablage in dieselbe Quelle wie das Transkript.
- **Absturzsicherung im Aufnahmeprozess** (`live/journal.py`). Drei Grundsätze: erst laden,
  dann schreiben (Transkript, `marks.json`, `souffleur.json` und WAV würden sonst den Bestand
  überschreiben); eine Zeitbasis (Sample-Position der fertigen WAV = Sitzungszeit); ein
  definierter Lebenszyklus mit den Zuständen `laeuft | unterbrochen | beendet | verworfen`.
  Lebenszeichen ist eine Sperre des Betriebssystems auf `sitzung.lock` (`msvcrt.locking` /
  `fcntl.flock`) – keine PID-Probe, keine neue Abhängigkeit.
- **Fortsetzen nimmt neu auf, Abschließen nicht.** Fortsetzen startet eine Aufnahme mit den
  aktuell gewählten Geräten im alten Sitzungsordner; Geräte und Bildquelle der alten Sitzung
  werden nicht blind übernommen (Indizes und Fenster-Handles gelten nach einem Neustart
  nicht mehr). Eine Aufnahme startet nie ohne Klick.
- **Bekannte Grenzen.** Was beim Absturz noch nicht transkribiert war, fehlt im
  Live-Transkript und steht nur im Mitschnitt – das Nachschärfen schließt die Lücke.
  Rückstandswerte im Fazit gelten nur für den laufenden Teil. Ein Transkript-Replay
  (Demo, Testmodus) wird nie fortgesetzt.
- **Frontend ohne Build-Schritt.** Native ES-Module unter `ui/static/js/` (`main`, `kern`,
  `kontext`, `dialoge`, `wiki`, `start`, `einstellungen`, `datei`, `nachbereitung`, `live`,
  `souffleur`), ein Hash-Router (`#/`, `#/neu`, `#/projekt/live`, `#/projekt/nachbereitung`,
  `#/projekt/einstellungen`, `#/datei`, `#/datei/ki`, `#/demo`, `#/einstellungen`), Abfragen
  nur für die sichtbare Ansicht. Stylesheets: `style.css` (Tokens mit `light-dark()`,
  Bausteine, Arbeitsansichten) und `css/shell.css` (Kopf, Startseite, Assistent, Dialoge).
  Dialoge sind native `<dialog>`-Elemente. `app.js` gibt es nicht mehr; der Server liefert
  aus `static/` nur `.css`, `.js` und `.svg` aus.
- **Dateiinhalte über den Server.** Neben den Standbildern der eigenen Live-Sitzung (§17)
  liefert der Server für die Transkript-Vorschau genau zwei Dateien eines Ergebnisordners aus:
  `transkript.annotiert.md` bzw. `transkript.md`, gedeckelt auf 400 000 Zeichen
  (`GET /api/transkript`). „Ordner öffnen“ ruft den Dateimanager des Systems auf. Der Server
  bindet weiter nur an `localhost` und weist fremde Herkünfte ab (NFR-8).
- **Demo ist Wegwerfware.** Fester Einstieg, leicht entfernbar (eine Route, eine Leiste in
  der Live-Ansicht): spielt `demo/llm-wiki/live_bahn_test/transkript.md` gegen das Demo-Wiki
  ab, schreibt nur nach `~/.cache/audioscribe/demo` und nie ins Wiki.

### 21.3 Funktionale Anforderungen

| ID | Anforderung |
|----|-------------|
| FR-66 | **Startseite.** Beim Start zeigt die Oberfläche vier Einstiege als Karten – „Neues Projekt“, „Projekt öffnen“, „Aufnahme transkribieren“, „Demo abspielen“ –, jede mit einem Satz Beschreibung und einer ausklappbaren Kurzhilfe. Darunter die zuletzt geöffneten Projekte (öffnen, aus der Liste entfernen; nicht erreichbare sind gekennzeichnet). Die Demo-Karte ist ohne Demo-Daten deaktiviert. |
| FR-67 | **Projekt anlegen.** Assistent in drei Schritten: (1) Projektname und LLM-Wiki – vorhandenes verknüpfen oder neues Gerüst anlegen, mit Sofortprüfung des Wikis; (2) Ordner für Sitzungen und Ordner für Bilder (Assets), beide vorgeschlagen, dazu das Verhalten nach einer Sitzung; (3) KI und Sprache mit der Vorgabe „globale Einstellung“. Pflicht sind Name, Wiki-Ordner, Sitzungsordner und Assets-Ordner; jedes Feld trägt eine Kurzbeschreibung, Fehler stehen am Feld. Ergebnis ist `<wiki>/.audioscribe/projekt.json`; ein vorhandenes Wiki bleibt dabei unverändert. |
| FR-68 | **Projekt öffnen.** Über die Liste der zuletzt geöffneten oder durch Wahl des Wiki-Ordners. Ordner, Wiki, KI und Sprache des Projekts gelten danach in allen Arbeitsansichten; der Projektname steht im Kopf, „Projekt schließen“ führt zur Startseite. Laufende Arbeit sperrt den Wechsel mit verständlicher Meldung. |
| FR-69 | **Einstellungen global und je Projekt.** Die globale Seite (Zahnrad) pflegt KI-Dienst, Modell für den Souffleur, Modell für die KI-Analyse und Sprache der Aufnahmen und zeigt die Umgebungs-Prüfung aus FR-47. Die Projektseite pflegt Name, Ordner, Wiki-Ablage (`fragen` \| `immer` \| `nie`, Bilder ja/nein) und kann jeden globalen Wert überschreiben oder wieder auf „globale Einstellung“ stellen. Änderungen gelten sofort. |
| FR-70 | **Arbeitsbereich des Projekts.** Drei Bereiche: *Live-Sitzung* (Live-Transkription mit Souffleur wie §17/§20, dazu ein optionaler Sitzungstitel), *Nachbereitung* (Sitzungen des Projekts mit Marken „im Wiki“, „nachbereitet“, „unterbrochen“; Wiki-Ablage, Transkript-Vorschau und KI-Analyse je Sitzung) und *Projekt* (Einstellungen). Nach dem Ende einer Sitzung erscheint die Karte „Wie geht es weiter?“ mit „Ins Wiki speichern“ und „Mit KI nachbereiten“ – beides möglich, in beliebiger Reihenfolge. |
| FR-71 | **Sitzung ins Wiki speichern.** Dialog mit Titel der Quelle, Vorschau des Zielordners und „Bilder mit übertragen“. Abgelegt wird nach `raw/<JJJJ-MM-TT>_<kurzname>/`: `transkript.md` (byte-gleich), `transcript.json` (ohne den lokalen `source_path`), `markierungen.json`/`markierungen.md` des Souffleurs, `README.md`. Mit Bildern zusätzlich: die Standbilder nach `<assets>/<ordnername>/`, `marks.json` mit Zeitstempel → Bild (Pfad relativ zur Ablage) und `transkript.annotiert.md`, in dem jedes Bild am selben Absatz steht wie im Sitzungsordner. Ein Vermerk `wiki-ablage.json` im Sitzungsordner hält fest, was abgelegt wurde. |
| FR-72 | **„Immer so speichern“.** Im Dialog wählbar und in den Projekteinstellungen änderbar: Steht das Projekt auf `immer`, geht jede sauber beendete Sitzung nach dem Nachschärfen ohne Nachfrage ins Wiki; das Ergebnis (oder der Fehler) steht in der Karte „Wie geht es weiter?“. Bei `nie` bietet die Karte die Ablage nicht an; sie bleibt über die Nachbereitung erreichbar. |
| FR-73 | **Nachbereitung ins Wiki.** Die Dokumente einer fertigen KI-Analyse lassen sich nach `<raw-Sitzung>/nachbereitung-ki/<analyse>/` legen – ohne Materialkopie, Skills und Protokoll, mit einer `README.md`, die sie als KI-erzeugt und nicht als Quelle kennzeichnet. Liegt die Sitzung noch nicht im Wiki, wird sie zuerst gespeichert. Mit Bildern verweisen die Dokumente auf die Bilder im Assets-Ordner der Sitzung (keine zweite Kopie), ohne Bilder werden Bildzeilen zu Textverweisen. |
| FR-74 | **Aufnahme transkribieren (ohne Projekt).** Die Ansicht zeigt nur diesen Weg: Datei(en) im Dialog wählen (der Ordner-Dialog listet dafür die Mediendateien), Speicherort, Optionen, Fortschritt. Je fertiger Aufnahme – auch einer früher schon transkribierten – eine Ergebniskarte mit Pfad, Transkript-Vorschau und „Ordner öffnen“, dazu die deutliche Folgeaktion „Mit KI weiterverarbeiten“; die KI-Analyse wählt die Aufnahme dann als Quelle vor. |
| FR-75 | **Demo abspielen.** Die Demo zeigt die Live-Ansicht ohne Steuerspalte mit einem Knopf „Demo starten“ (Stoppen, erneut starten). Sie spielt das Beispiel-Meeting gegen das Demo-Wiki ab; es wird nichts aufgenommen, nichts ins Wiki gespeichert und nichts in der Projektliste gemerkt. |
| FR-76 | **Laufende Sicherung.** Während einer Live-Sitzung schreibt der Aufnahmeprozess in den Sitzungsordner: `sitzung.json` (Zustand, stabile `sitzung_id`, Titel, Sprache/Modell, Aufnahme-Teile mit `start_sample`), `sitzung.journal.jsonl` (jedes Segment sofort und mit `fsync`, jedes Standbild, alle 5 s eine Takt-Zeile), `sitzung.lock` (Lebenszeichen) und `sprecher.json` (Stimmprofile, damit „Sprecher 1/2“ dieselben bleiben). `marks.json` wird atomar geschrieben. Fällt der Server weg, schließt der Aufnahmeprozess geordnet ab (Audio schließen, sichern, Zustand `unterbrochen`). |
| FR-77 | **Wiederaufnahme.** Nicht sauber beendete Sitzungen erscheinen als Banner auf der Startseite („Projekt öffnen und fortsetzen“) und in der Live-Ansicht des Projekts mit drei Wegen: **Fortsetzen** (`audioscribe live --resume ORDNER`: bisheriges Transkript, Standbilder und Souffleur-Hinweise erscheinen sofort, Zeitleiste, Segment- und Bildnummern laufen weiter, Audio in neue Teil-Dateien, die beim sauberen Ende je Spur zu einer WAV verbunden werden), **Abschließen** (`audioscribe live --finalize ORDNER`: Transkript aus dem Gesicherten ohne Modelle, danach wie gewohnt Nachschärfen) und **Verwerfen** (die Sitzung wird nicht mehr angeboten, die Dateien bleiben liegen). `--titel TEXT` setzt den Sitzungstitel. Verliert der Browser die Verbindung zum Server, zeigt er das an und verbindet sich von selbst wieder. |
| FR-78 | **KI-Verbrauch.** Jeder KI-Aufruf, der den Rechner verlässt (Souffleur je Fenster und Essenz, KI-Analyse), wird mit Tokens und ungefährem Preis in US-Dollar gezählt. Die Zahlen meldet der KI-Dienst selbst (Preis zu API-Tarifen des jeweiligen Modells); eine eigene Preistabelle gibt es nicht. Im Kopf steht dezent neben dem Zahnrad die Summe seit Programmstart („… Tokens · ≈ … $“), sichtbar erst nach dem ersten Aufruf; ein Klick zeigt die Aufteilung (Souffleur dieser Sitzung, KI-Analyse dieses Laufs, gesamt, Eingabe/Ausgabe/Cache). Der Preis trägt immer „≈“ und den Hinweis „Gegenwert zu API-Preisen – bei Anmeldung über ein Abo wird nichts abgerechnet“. Während einer Analyse wachsen die Tokens als Zwischenstand, verbindlich sind die Zahlen je Ergebnis; `analyse.json` führt Tokens und Preis über alle Läufe, `souffleur-diagnose.jsonl` den Verbrauch je Aufruf, das Analyse-Protokoll eine Zeile `[Verbrauch]`. Lokale Arbeit (Transkription, Sprechertrennung, KI-Attrappe) zählt nicht; ein per Zeitüberschreitung abgebrochener Aufruf liefert keine Zahlen. |

### 21.4 Nicht-funktionale Anforderungen

| ID | Anforderung |
|----|-------------|
| NFR-25 | **Leitplanke nachweisbar.** Die Wiki-Ablage schreibt nur unter `raw/` und in den Assets-Ordner, nie unter `wiki/`, überschreibt nichts und läuft nur auf Nutzeraktion bzw. gewähltes „immer“; `transkript.md` der Ablage ist byte-gleich zur Sitzung (Tests in `tests/test_wiki_ablage.py`). NFR-21 gilt für das Paket `souffleur/` unverändert. |
| NFR-26 | **Wiederaufnahme zerstört nichts.** Beim Fortsetzen wird der Bestand zuerst geladen und erst dann geschrieben; eine vorhandene WAV wird nie zum Schreiben geöffnet; das Verbinden der Teile ist streamend und wiederholbar (temporäre Datei + Umbenennen). Sitzungen ohne `--resume` verhalten sich wie bisher. |
| NFR-27 | **Lebenszeichen ohne neue Abhängigkeit.** Ob eine Sitzung noch läuft, entscheidet die Betriebssystem-Sperre auf `sitzung.lock` (Windows und macOS/Linux, Standardbibliothek); sie verhindert zugleich ein doppeltes Fortsetzen desselben Ordners. |
| NFR-28 | **Kein Build-Schritt, zugänglich.** Die Oberfläche läuft ohne Node und ohne Fremdbibliothek; `start.ps1`/`start.sh` bleiben unverändert. Hell/Dunkel über einen Satz Tokens (`light-dark()`), Tastaturbedienung, sichtbarer Fokus, `prefers-reduced-motion` wird beachtet, Statusmeldungen über `aria-live`. |
| NFR-29 | **Tests ohne Rechnerzustand.** Die Tests lesen und schreiben nie die Einstellungen des Rechners (`tests/conftest.py`); Wiederaufnahme, Wiki-Ablage und Projekt-Routen sind ohne Hardware und ohne KI-Dienst geprüft. |

### 21.5 Akzeptanzkriterien

- [ ] Start zeigt die Startseite mit vier Einstiegen; jeder hat eine Kurzhilfe.
- [ ] Neues Projekt mit vorhandenem Wiki und mit „Neues Wiki anlegen“: Projektdatei liegt
      unter `<wiki>/.audioscribe/`, das vorhandene Wiki ist sonst unverändert, das neue Wiki
      ist sofort lesbar (Zustand „Wiki“ mit Seitenzahl).
- [ ] Projekt schließen und über „Zuletzt geöffnet“ wieder öffnen: Ordner, Wiki-Ablage, KI
      und Sprache stehen wieder da; eine Sprache im Projekt schlägt die globale, „globale
      Einstellung“ stellt sie zurück.
- [ ] Sitzung beenden → „Wie geht es weiter?“ → „Ins Wiki speichern“ mit Bildern: Ordner
      unter `raw/`, Bilder im Assets-Ordner, `transkript.annotiert.md` zeigt jedes Bild am
      richtigen Absatz, `transkript.md` byte-gleich, `wiki/` unverändert; ein zweites
      Speichern hängt `-2` an.
- [ ] Projekt auf „immer“: die nächste beendete Sitzung liegt ohne Nachfrage im Wiki.
- [ ] KI-Analyse einer Sitzung → „Nachbereitung ins Wiki speichern“: Dokumente unter
      `nachbereitung-ki/`, als KI-erzeugt gekennzeichnet, Bildverweise zeigen in die Assets.
- [ ] „Aufnahme transkribieren“: Datei wählen, transkribieren, Ergebniskarte mit Vorschau,
      „Mit KI weiterverarbeiten“ führt zur KI-Analyse mit vorgewählter Quelle.
- [ ] Demo: ein Knopf startet das Beispiel-Meeting, Souffleur-Hinweise erscheinen, im
      Demo-Wiki entsteht nichts.
- [ ] Absturztest auf dem Gerät: Server während einer Aufnahme beenden, neu starten →
      Banner; „Fortsetzen“ zeigt das bisherige Transkript und nimmt weiter auf, nach dem
      Stopp gibt es je Spur eine WAV und das Nachschärfen läuft durch; „Abschließen“
      schreibt das Transkript ohne weitere Aufnahme.
- [ ] `pytest` grün: `tests/test_projekt.py`, `tests/test_wiki_ablage.py`,
      `tests/test_projekt_ui.py`, `tests/test_wiederaufnahme.py` sowie die bestehenden
      Dateien aus §20.5.
