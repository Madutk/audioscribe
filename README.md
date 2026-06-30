# AudioScribe

Lokale **Audio-Transkription mit Sprecher-Diarisierung**. Aus einer Meeting-Aufnahme
(Audio: mp3/m4a/wav/… oder Video: mp4/mkv/mov/webm/… – die Audiospur wird dann zuerst
extrahiert) entsteht ein zeitgestempeltes Markdown-Transkript, in dem die Sprecher
getrennt sind (`Sprecher 1 / 2 / 3`). Läuft **vollständig lokal** (kein Audio-Upload);
einzige Online-Aktion ist der einmalige Download der Modellgewichte.

Pipeline: **WhisperX** — faster-whisper `large-v3` (Transkription) → wav2vec2
(Wort-Alignment) → pyannote `speaker-diarization-3.1` (Diarisierung). Die Modelle laufen
sequenziell; der VRAM wird zwischen den Stufen freigegeben (Ziel-HW: RTX 3080, 8 GB).

## Umgebung

- **WSL2 / Ubuntu 24.04**, Python 3.12, NVIDIA-GPU mit CUDA (in WSL verfügbar).
- Paket-/Env-Verwaltung über **[uv](https://docs.astral.sh/uv/)**.
- `ffmpeg` wird **gebündelt** mitgeliefert (`imageio-ffmpeg`) — kein System-`ffmpeg`/`sudo` nötig.

## Setup

```bash
# uv installieren (einmalig, falls noch nicht vorhanden)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Abhängigkeiten installieren (lädt u.a. CUDA-PyTorch + WhisperX)
uv sync

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
```

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

## Erster Lauf & Modell-Downloads

Beim ersten `run` werden die Modellgewichte einmalig geladen und danach gecached
(`~/.cache`): Whisper `large-v3` (~3 GB), das deutsche wav2vec2-Alignment-Modell
(~360 MB) und – falls Diarisierung aktiv – die pyannote-Modelle. Danach läuft alles
offline. Validiere die Qualität am ersten echten Sample und justiere ggf. nach (s. PRD §9/§10).

## Kompatibilität (WhisperX + PyTorch 2.6)

Zwei bekannte Reibungspunkte des aktuellen Stacks werden automatisch im Code behandelt
(`src/audioscribe/compat.py`):

- **cuDNN:** WhisperX pinnt `ctranslate2<4.5` (gegen cuDNN **8** gebaut), torch 2.6 bringt
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
AUDIOSCRIBE_WHISPER_COMPUTE_TYPE=int8_float16   # oder int8
AUDIOSCRIBE_BATCH_SIZE=4                          # Standard 8; bei OOM senken
```

## Konfiguration

Alle Defaults stehen in `src/audioscribe/config.py` und sind per `AUDIOSCRIBE_*`-Umgebungs­variablen
oder `.env` überschreibbar (siehe `.env.example`).

## Entwicklung

```bash
uv run pytest        # Unit-Tests (reine Logik, keine Modell-Downloads)
```

## Status / Scope

Basisstufe gemäß `PRD.md`: eine Datei pro Aufruf, Markdown-Ausgabe (+ optional PDF),
Diarisierung als „Sprecher N" (keine echte Personen-Identifikation). AudioScribe ist die
Transkriptions-Basisstufe für die übergeordnete Meeting-Protokoll-Pipeline.
