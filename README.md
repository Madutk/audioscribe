# AudioScribe

Lokale **Audio-Transkription mit Sprecher-Diarisierung**. Aus einer Meeting-Aufnahme
(Audio: mp3/m4a/wav/… oder Video: mp4/mkv/mov/webm/… – die Audiospur wird dann zuerst
extrahiert) entsteht ein zeitgestempeltes Markdown-Transkript, in dem die Sprecher
getrennt sind (`Sprecher 1 / 2 / 3`). Läuft **vollständig lokal** (kein Audio-Upload);
einzige Online-Aktion ist der einmalige Download der Modellgewichte.

Pipeline: **WhisperX** — faster-whisper `large-v3` (Transkription) → wav2vec2
(Wort-Alignment) → pyannote `speaker-diarization-3.1` (Diarisierung). Die Modelle laufen
sequenziell; der VRAM wird zwischen den Stufen freigegeben (Ziel-HW: RTX 3080, 8 GB).
Läuft wahlweise auf **NVIDIA-GPU (CUDA, schnell)** oder **CPU-only (deutlich langsamer)**.

## Umgebung

- **WSL2 / Ubuntu 24.04** (oder anderes Linux), Python 3.12.
- **GPU optional**: NVIDIA-GPU mit CUDA (schnell) **oder** reiner CPU-Betrieb
  (Rechner ohne NVIDIA-Karte; mehrfache Echtzeit-Laufzeit, s. „CPU-Betrieb" unten).
- Paket-/Env-Verwaltung über **[uv](https://docs.astral.sh/uv/)**.
- `ffmpeg` wird **gebündelt** mitgeliefert (`imageio-ffmpeg`) — kein System-`ffmpeg`/`sudo` nötig.

## Setup

```bash
# uv installieren (einmalig, falls noch nicht vorhanden)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Abhängigkeiten installieren — GENAU EINE Backend-Variante wählen:
uv sync --extra cu124      # Rechner MIT NVIDIA-GPU (CUDA-PyTorch)
uv sync --extra cpu        # Rechner OHNE NVIDIA-Karte (schlanke CPU-Wheels, ~3 GB weniger)
# (beide gleichzeitig lehnt uv mit einem Konfliktfehler ab; die Browser-Oberflächen
#  kommen bei Bedarf dazu: uv sync --extra cu124 --extra review)
#
# WICHTIG auf CPU-Rechnern: uv run synct standardmäßig OHNE Extras und würde das
# große PyPI-CUDA-torch zurückinstallieren — daher das Extra auch beim Ausführen
# mitgeben: uv run --extra cpu audioscribe …
# (Auf GPU-Rechnern ist das unkritisch: auch das PyPI-torch ist CUDA-fähig.)

# HuggingFace-Token für die Diarisierung hinterlegen
cp .env.example .env
#   -> HF_TOKEN=... eintragen und einmalig die Modell-Bedingungen akzeptieren:
#      https://huggingface.co/pyannote/speaker-diarization-3.1
#      https://huggingface.co/pyannote/segmentation-3.0

# Umgebung prüfen
uv run audioscribe doctor
```

## Nutzung

```bash
# Standard: Transkription + Diarisierung -> output/<name>/transkript.md
uv run audioscribe run input/meeting.m4a

# Video: die Audiospur wird zuerst extrahiert (work/<name>.16k.wav), dann transkribiert
uv run audioscribe run input/meeting.mp4

# zusätzlich PDF erzeugen
uv run audioscribe run input/meeting.m4a --pdf

# ohne Diarisierung (kein HF-Token nötig), Sprache automatisch erkennen
uv run audioscribe run input/meeting.m4a --no-diarize --language auto

# Sprecheranzahl vorgeben / eingrenzen
uv run audioscribe run input/meeting.m4a --num-speakers 3
uv run audioscribe run input/meeting.m4a --min-speakers 2 --max-speakers 5

# Zeitstempel-Granularitaet: neuer Zeitstempel alle N Saetze (Default 2; 0 = ganzer Beitrag)
uv run audioscribe run input/meeting.m4a --sentences-per-timestamp 3

# Geraet: Default "auto" (CUDA falls verfuegbar, sonst CPU); erzwingen mit --device
uv run audioscribe run input/meeting.m4a --device cpu
```

### Zeitstempel-Granularität

Standardmäßig wird **alle 2 Sätze** ein neuer Zeitstempel gesetzt, auch innerhalb eines
langen Sprecher-Beitrags – die feine Zeit stammt aus den Wort-Zeitstempeln des Alignments.
Steuerbar über `--sentences-per-timestamp N` bzw. `AUDIOSCRIBE_SENTENCES_PER_TIMESTAMP`:

```
**[00:01:23] Sprecher 1:** Guten Morgen, fangen wir an. Schön, dass alle da sind.
**[00:01:31] Sprecher 1:** Heute geht es um das Quartalsergebnis. Ich teile gleich den Bildschirm.
**[00:01:44] Sprecher 2:** Ja, einverstanden …
```

`--sentences-per-timestamp 0` fasst – wie früher – den ganzen Beitrag eines Sprechers zu
einem Block mit nur einem Zeitstempel zusammen. Ohne Alignment (`--no-align`) fällt die
Granularität auf Segment-Ebene zurück.

### Ausgabeformat (Markdown)

```
# Transkript: meeting.m4a

| | |
|---|---|
| Datei | meeting.m4a |
| Laenge | 00:42:10 |
| Sprache | de |
| Sprecher | 3 |
| Modell | large-v3 (WhisperX) |

---

**[00:01:23] Sprecher 1:** Guten Morgen, fangen wir an …
**[00:01:41] Sprecher 2:** Ja, einverstanden …
```

Namen werden bei Bedarf manuell nachgetragen (Markdown ist das editierbare
Primärformat; PDF wird daraus optional erzeugt).

## Browser-Oberfläche: ganze Ordner transkribieren

Wer nicht je Datei einen CLI-Aufruf tippen möchte: `audioscribe ui` startet eine schlanke
Oberfläche, in der **Eingangs- und Ausgangsordner** gewählt werden. Alle darin gefundenen
Audio-/Videodateien werden **nacheinander** transkribiert, der Fortschritt läuft live mit.
Vollständig lokal (nur `localhost`, kein Upload).

```bash
# einmalig die optionalen Pakete installieren (FastAPI + uvicorn)
uv sync --extra cu124 --extra review      # bzw. --extra cpu --extra review

uv run audioscribe ui                     # öffnet http://127.0.0.1:8766
uv run audioscribe ui --port 9000 --no-browser
```

**Ablauf in der Oberfläche:**

1. **Eingangs- und Ausgangsordner** wählen – entweder über „📁 Waehlen" (Ordner-Browser mit
   Schnellzielen für Projekt, Home und Windows-Laufwerke) oder direkt ins Textfeld getippt.
   Die zuletzt benutzten Ordner und Optionen werden **serverseitig gemerkt** und stehen nach
   einem Neustart wieder da – unabhängig von Browser und Adresse.
2. Die **Dateiliste** zeigt alle gefundenen Medien mit Länge und Größe. Jede Datei hat ein
   **Kontrollkästchen**; vorausgewählt sind die noch offenen. Schnellschalter: „Alle",
   „Nur offene", „Keine". Wer eine bereits transkribierte Datei ankreuzt, lässt sie **neu**
   laufen – die Markierung „bereits transkribiert" bleibt sichtbar.
3. **Optionen**: Modell, Sprache, Gerät (`cuda` ist ausgegraut, wenn keine GPU verfügbar ist)
   und Sprecher-Diarisierung an/aus.
4. **„▶ Transkription starten"** – je Datei ein Fortschrittsbalken, dazu ein Gesamtbalken über
   die Audio-Gesamtlänge und eine **Restzeit**. Schlägt eine Datei fehl, läuft der Stapel mit
   der nächsten weiter. Am Ende steht eine Zusammenfassung.

Ergebnisse landen wie gewohnt unter `<Ausgangsordner>/<Dateiname>/transkript.md`. Jede Datei
läuft als eigener `audioscribe run`-Subprozess – der Lauf hängt also **nicht** am Browser-Tab
und läuft weiter, wenn er geschlossen wird (Beenden per „■ Abbrechen" oder Strg+C im Terminal).

**Woher der Fortschritt kommt:** WhisperX meldet während der Transkription den Anteil der
bereits verarbeiteten Audio-Abschnitte, pyannote während der Diarisierung den Anteil der
Segmentierung und Sprecher-Einbettungen. Die Restzeit wird aus den **bereits fertigen Dateien**
geschätzt (Audiolänge gegen Laufzeit, getrennt nach festem Aufwand je Datei und Durchsatz) und
erscheint deshalb erst, sobald die erste Datei durch ist. Dateien ohne auslesbare Länge
(z. B. manche `.ts`-Container) werden separat ausgewiesen statt geraten.

Dieselben Fortschrittszeilen lassen sich auch im Terminal einschalten – standardmäßig bleibt
die Ausgabe dort ruhig:

```bash
AUDIOSCRIBE_PROGRESS=1 uv run audioscribe run input/meeting.mp4
```

**Windows/WSL:** Die Adresse einfach im Windows-Browser öffnen – WSL2 leitet `127.0.0.1`
durch. Öffnet sich kein Browser automatisch, die im Terminal ausgegebene URL von Hand
aufrufen. Ein aus dem Explorer kopierter Pfad wie `C:\Users\user\Videos` kann direkt
eingefügt werden und wird zu `/mnt/c/Users/user/Videos` – Medien auf dem WSL-Dateisystem
(z. B. `input/`) werden allerdings spürbar schneller gelesen als solche unter `/mnt/c`.

## Video transkribieren

Videos werden **genauso** verarbeitet wie Audiodateien – einfach den Pfad zur Videodatei
übergeben. AudioScribe extrahiert vorab automatisch die Tonspur und transkribiert sie dann.

```bash
# Standard: Video -> Audiospur extrahieren -> Transkription + Diarisierung
uv run audioscribe run input/meeting.mp4

# mit PDF, ohne Diarisierung, Sprecheranzahl vorgeben – alle Optionen gelten genauso
uv run audioscribe run input/meeting.mkv --pdf
uv run audioscribe run input/meeting.mov --no-diarize
uv run audioscribe run input/meeting.webm --num-speakers 3
```

**Unterstützte Container:** `mp4`, `mkv`, `mov`, `avi`, `webm`, `m4v`, `wmv`, `flv`,
`mpg`/`mpeg`, `ts`, `m2ts`, `3gp`, `ogv` (Erkennung an der Dateiendung).

**Was dabei passiert:**

1. **Audiospur extrahieren** (zusätzliche erste Pipeline-Stufe): Die Tonspur wird mit dem
   gebündelten ffmpeg als 16-kHz-Mono-WAV nach `work/<name>.16k.wav` geschrieben
   (kein System-`ffmpeg` nötig). Dieses Zwischen-WAV bleibt als wiederverwendbares Artefakt liegen.
2. Danach laufen die normalen Stufen (Transkription → Alignment → Diarisierung → Export).

Das Transkript landet wie gewohnt unter `output/<videoname>/transkript.md`; Kopfzeile und
Ordnername tragen den **Original-Videonamen** (z. B. `# Transkript: meeting.mp4`).

> Hinweise: Das Video muss eine **Tonspur** enthalten (sonst bricht die Extraktion mit einer
> klaren Meldung ab). Enthält der Ton **keine Sprache** (Stille/Musik), wird ein leeres
> Transkript erzeugt – kein Abbruch.

## Bild-Annotation: wichtige Standbilder zum Transkript (Review-Oberfläche)

Optionale Ausbaustufe (PRD §13): Nach der Transkription wichtige Video-**Standbilder**
markieren und dem Transkript an der zeitlich passenden Stelle zuordnen – z. B. geteilte
Folien/Bildschirme. Läuft vollständig lokal (nur `localhost`, kein Upload).

```bash
# einmalig die optionalen Pakete installieren (FastAPI + uvicorn)
uv sync --extra review

# 1) wie gewohnt transkribieren – schreibt zusätzlich output/<name>/transcript.json
uv run audioscribe run input/meeting.mp4

# 2) Review-Oberfläche starten (öffnet den Browser auf http://127.0.0.1:8765)
uv run audioscribe review input/meeting.mp4        # oder: review output/meeting

# 3) annotiertes Transkript erzeugen (Markdown, optional PDF)
uv run audioscribe export output/meeting --pdf
```

**Ablauf in der Oberfläche:**

1. Das Video ist scrub-/suchbar; das Transkript läuft synchron mit (Klick auf eine Zeile
   springt im Video dorthin, Klick auf ein Thumbnail zur Markierung).
2. **„📸 Frame markieren"** greift den aktuellen Wiedergabe-Zeitpunkt – abzüglich eines
   **Lag-Offsets** (Default −2,5 s, in der UI justierbar) – extrahiert per ffmpeg ein
   **framegenaues PNG** und legt es als Markierung an (optional mit Notiz).
3. Markierungen erscheinen rechts als **Thumbnail-Liste** und lassen sich einzeln löschen.
4. `audioscribe export` merged Transkript + Markierungen zu `transkript.annotiert.md`
   (+ optional `.pdf`); das editierbare `transkript.md` bleibt **unberührt**.

**Artefakte je Aufnahme:** `output/<name>/transcript.json`, `frames/<HH-MM-SS>.png`,
`marks.json`, `transkript.annotiert.md`. Die Markierungen (`marks.json`) **überstehen
erneute Transkriptionsläufe** – die Einfügeposition wird beim Export aus dem Zeitstempel
berechnet, nicht fest gespeichert.

## Erster Lauf & Modell-Downloads

Beim ersten `run` werden die Modellgewichte einmalig geladen und danach gecached
(`~/.cache`): Whisper `large-v3` (~3 GB), das deutsche wav2vec2-Alignment-Modell
(~360 MB) und – falls Diarisierung aktiv – die pyannote-Modelle. Danach läuft alles
offline. Validiere die Qualität am ersten echten Sample und justiere ggf. nach (s. PRD §9/§10).

## Kompatibilität (WhisperX + PyTorch 2.6)

Zwei bekannte Reibungspunkte des aktuellen Stacks werden automatisch im Code behandelt
(`src/audioscribe/compat.py`):

- **cuDNN** (betrifft nur den CUDA-Pfad; im CPU-Betrieb wird der Schritt komplett
  übersprungen): WhisperX pinnt `ctranslate2<4.5` (gegen cuDNN **8** gebaut), torch 2.6 bringt
  aber cuDNN **9** mit. AudioScribe lädt die cuDNN-8-Bibliotheken **einmalig** separat nach
  (`~/.cache/audioscribe/cudnn8/`) und macht sie via `LD_LIBRARY_PATH` auffindbar – ohne
  torchs cuDNN 9 zu stören (andere SO-Namen).
- **`torch.load`:** PyTorch 2.6 lädt standardmäßig mit `weights_only=True`; die
  pyannote-Checkpoints (VAD/Diarisierung) lassen sich damit nicht entpacken. Da alle Gewichte
  aus vertrauenswürdiger lokaler Quelle stammen, wird `weights_only=False` erzwungen.

## VRAM / Tuning (8 GB)

`large-v3` in `float16` kann auf 8 GB knapp werden. Stellschrauben:

```bash
# in der .env oder als Flag
AUDIOSCRIBE_WHISPER_COMPUTE_TYPE=int8_float16   # oder int8; Default "auto" (cuda->float16)
AUDIOSCRIBE_BATCH_SIZE=4                          # Standard 8; bei OOM senken
```

## CPU-Betrieb (Rechner ohne NVIDIA-Karte)

Mit `uv sync --extra cpu` installiert und `--device auto` (Default) läuft AudioScribe
automatisch auf der CPU; `compute_type` wird dann automatisch auf `int8` gesetzt
(CTranslate2 unterstützt kein `float16` auf CPU).

```bash
uv sync --extra cpu
uv run --extra cpu audioscribe doctor
uv run --extra cpu audioscribe run input/meeting.m4a
```

Zu beachten:

- Das `--extra cpu` gehört auf CPU-Rechnern **auch an `uv run`** — ohne Extra synct
  uv die Umgebung zurück auf das PyPI-torch (CUDA-Bundle, ~3 GB mehr; läuft zwar
  auch auf CPU, verfehlt aber den Zweck der schlanken Installation).

- **Deutlich langsamer** als auf GPU — `large-v3` braucht auf CPU ein Mehrfaches der
  Aufnahmedauer. Wirksamster Hebel ist ein **kleineres Modell**, nicht die Batch-Größe:
  ```bash
  uv run audioscribe run input/meeting.m4a --model medium   # oder small
  ```
- Diarisierung (pyannote) läuft ebenfalls auf CPU, auch das dauert entsprechend länger.
- Auf einem GPU-Rechner lässt sich CPU-Betrieb mit `--device cpu` erzwingen (z. B. zum Testen).
- `uv run audioscribe doctor` zeigt das effektive Gerät, den torch-Build (`+cpu`/`+cu124`)
  und den effektiven `compute_type`.

## Konfiguration

Alle Defaults stehen in `src/audioscribe/config.py` und sind per `AUDIOSCRIBE_*`-Umgebungs­variablen
oder `.env` überschreibbar (siehe `.env.example`).

## Entwicklung

```bash
uv run pytest        # Unit-Tests (reine Logik, keine Modell-Downloads)
```

## Status / Scope

Basisstufe gemäß `PRD.md`: eine Datei pro CLI-Aufruf (die Browser-Oberfläche arbeitet ganze
Ordner nacheinander ab), Markdown-Ausgabe (+ optional PDF), Diarisierung als „Sprecher N"
(keine echte Personen-Identifikation). AudioScribe ist die Transkriptions-Basisstufe für die
übergeordnete Meeting-Protokoll-Pipeline.
