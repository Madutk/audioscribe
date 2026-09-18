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
# WICHTIG: 'uv run' synct vorher OHNE Extras und ersetzt die gewählten Wheels durch
# die von PyPI. Das Extra gehört daher AUCH ans Ausführen — oder man startet die
# Skripte direkt aus dem venv. Siehe "GPU-Betrieb (CUDA)" bzw. "CPU-Betrieb".

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

# Extras beim Start MITGEBEN - sonst synct uv die Umgebung ohne sie zurück und die
# Geräte-Auswahl steht danach auf 'cuda (nicht verfügbar)':
uv run --extra cu124 --extra review audioscribe ui        # öffnet http://127.0.0.1:8766
uv run --extra cu124 --extra review audioscribe ui --port 9000 --no-browser

# Ohne uv (synchronisiert nichts, kürzer):
.venv/bin/audioscribe ui                  # Windows: .venv\Scripts\audioscribe.exe ui
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
3. **Optionen**: Modell, Sprache, Gerät (`cuda` ist ausgegraut, wenn keine GPU verfügbar ist),
   Sprecher-Diarisierung an/aus und **Bildwechsel-Erkennung** für Bildschirmaufnahmen
   (mit Empfindlichkeit und Bildformat, s. u.).
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

**Ordner wählen:** Ein aus dem Explorer kopierter Pfad wie `C:\Users\marek\Videos` kann in
beide Felder direkt eingefügt werden; der Knopf **📁 Wählen** blättert serverseitig durch
das Dateisystem. Die Schnellziele über der Ordnerliste führen zu den Laufwerken (`C:`, `D:`
…) sowie zu Home, Desktop, Downloads und Videos – unter Windows gibt es keine gemeinsame
Wurzel `/`, aus der man sich zu allen Ordnern durchklicken könnte. Versteckte Ordner und
Systemordner (`$Recycle.Bin`, `System Volume Information`) bleiben ausgeblendet.

**Windows/WSL:** Läuft AudioScribe unter WSL, die Adresse einfach im Windows-Browser
öffnen – WSL2 leitet `127.0.0.1` durch. Öffnet sich kein Browser automatisch, die im
Terminal ausgegebene URL von Hand aufrufen. Pfade werden dann in die jeweils passende
Richtung umgesetzt: unter WSL wird `C:\Users\marek\Videos` zu `/mnt/c/Users/marek/Videos`,
nativ unter Windows umgekehrt `/mnt/c/...` zu `C:\...`. Medien auf dem WSL-Dateisystem
(z. B. `input/`) werden spürbar schneller gelesen als solche unter `/mnt/c`.

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

## Bildwechsel automatisch erkennen (Bildschirmaufnahmen)

Statt Standbilder von Hand zu markieren, erkennt AudioScribe Wechsel des Bildschirm­inhalts
selbst und sichert je Wechsel eines. **Mausbewegungen lösen nichts aus.**

```bash
uv run audioscribe run input/demo.mkv --frames

# einstellbar:
--frame-sensitivity grob|mittel|fein   # Default mittel
--frame-format jpg-1600|jpg-1280|png   # Default jpg-1600 (~150 KB je Bild)
--frame-fps 1                          # Abtastungen/s, Default 2
--frame-min-gap 8                      # Mindestabstand in Sekunden, Default 4
```

In der Stapel-Oberfläche stehen Checkbox, Empfindlichkeit und Bildformat in der Karte
„Optionen"; die beiden Feinparameter bleiben der Kommandozeile vorbehalten.

**Ergebnis:** `output/<name>/frames/0001_00-01-23.jpg` … und ein
`transkript.annotiert.md`, in dem jedes Bild mit seiner ID am zeitlich passenden Absatz
steht:

```
**[00:01:20] Sprecher 1:** Hier seht ihr die Auswertung …

![Bild #0001 – 00:01:23](frames/0001_00-01-23.jpg)
```

Die ID ist die Klammer zwischen Bild und Text: Transkript und Bilder lassen sich damit
gemeinsam einer KI vorlegen, die sich auf „Bild #0001" beziehen kann.

**Wie es arbeitet:** Ein einziger ffmpeg-Durchlauf verkleinert das Video auf 192×108
Graustufen; verglichen wird über ein Raster aus 16×9 Blöcken. Ein Mauszeiger belegt genau
einen Block und bleibt damit unter der Schwelle, ein Fenster- oder Folienwechsel betrifft
Dutzende. Zusammenhängende Trefferserien (Animationen, Scrollen) ergeben **ein** Bild —
aufgenommen am Ende der Serie, wenn der Bildschirm fertig aufgebaut ist.

**Kosten:** grob ein Achtel der Videolänge (80-Minuten-Aufnahme ≈ 10 Minuten). Deshalb ist
die Erkennung standardmäßig aus. Ein erneuter Lauf ersetzt die automatischen Bilder und
lässt von Hand gesetzte Markierungen unberührt.

## KI-Analyse per Claude-Agent (Prozessdokumentation u. a.)

Ein Claude-Agent wertet einen fertigen Ergebnisordner aus, also Transkript und Standbilder,
und legt alle Dokumente in einem Ordner ab, den du selbst wählst. Dafür gibst du ihm einen
**Prozessnamen**, freien **Kontext** und eine Auswahl an **Skills** mit. Die Skills legen
Aufbau und Qualitätsmaßstab der Dokumente fest, zum Beispiel `prozessrekonstruktion`,
`prozessdoku-qs` oder `arbeitsanweisung-ableiten`.

**Abrechnung über das Claude-Abo:** Die Anbindung läuft über das
[Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk). Es steuert Claude Code und
benutzt dessen Anmeldung. Wer sich einmal mit `claude` per Pro-/Max-Abo eingeloggt hat,
braucht keinen API-Key. **Achtung:** Ist `ANTHROPIC_API_KEY` gesetzt (Umgebung oder
`.env`), hat der Key Vorrang, und die Kosten laufen über das API-Guthaben.
`audioscribe doctor` zeigt an, welcher Weg aktiv ist.

```bash
# einmalig: das SDK installieren (zusammen mit dem Rechen-Backend)
uv sync --extra cu124 --extra review --extra agent
claude            # einmal starten und mit dem Claude-Abo anmelden, dann beenden

# welche Skills gibt es? (* = Vorauswahl aus AUDIOSCRIBE_AGENT_SKILLS)
.venv/bin/audioscribe analyze --list-skills

# Analyse starten: Quelle ist der Ergebnisordner eines 'run' (oder der Videopfad)
.venv/bin/audioscribe analyze output/demo \
    --name "Rechnungsprüfung Kreditoren" \
    --out ~/Analysen \
    --context-text "Zielgruppe: neue Kollegen in der Kreditorenbuchhaltung" \
    --context glossar.md \
    --skill transkript-normalisierung --skill prozessrekonstruktion --skill prozessdoku-qs
```

Fehlen `--name` oder `--out`, fragt der Befehl im Terminal nach. Ohne `--skill` gilt die
Vorauswahl, mit `--no-skills` arbeitet der Agent ohne Skills. Weitere Schalter:
`--model` (Default `claude-opus-5`), `--max-turns N`, `--no-bash` (Skill-Skripte nicht
ausführen) und `--skills-dir` (Default `~/.claude/skills`, rekursiv durchsucht, also
auch die mit claude.ai synchronisierten Skills).

**In der Browser-Oberfläche** (`audioscribe ui`) steht die Analyse im Reiter
„KI-Analyse“. Dort wählst du eine fertige Transkription aus dem Ausgangsordner, gibst
Prozessname, Ausgabeordner und Kontext ein (optional mit Kontextdateien) und kreuzt die
Skills an. Während des Laufs zeigt die Seite den Fortschritt:
- den Plan des Agenten als abhakbare Schrittliste mit Balken („Schritt 3 von 7“)
- den aktiven Skill
- wie viele Standbilder er schon angesehen hat
- die bisher geschriebenen Dokumente

Einen Prozentwert gibt es bewusst nicht: Der Balken zählt die Schritte des Agenten, und
ergänzt er Schritte, läuft der Balken auch zurück. Am Ende stehen Ergebnisordner und
`INDEX.md` in der Seite.

**Ergebnis** in `<out>/<prozessname>/`:

```
INDEX.md                  # vom Agenten: Übersicht aller Dokumente, offene Punkte, Annahmen
prozessdokumentation.md   # … je nach Skills und Kontext
material/                 # Kopie von Transkript, frames/, marks.json (Dokumente verweisen hierauf)
kontext/                  # Kopie der Kontextdateien
analyse.json              # Protokoll: Skills, Modell, Session-ID, Dauer, Token-Gegenwert (kosten_usd)
agent-log.txt             # vollständiger Verlauf
.claude/skills/           # die verwendeten Skills (Stand zum Zeitpunkt der Analyse)
```

**Abgrenzung:** Der Agent schreibt **nur** in diesen Ordner. Schreibversuche außerhalb
werden abgelehnt und im Protokoll als `[Verweigert]` vermerkt. Der audioscribe-Ergebnisordner
bleibt unverändert, weil der Agent auf einer Kopie arbeitet. Deine übrigen Claude-Code-Skills,
MCP-Server und die globale `CLAUDE.md` fließen **nicht** in den Lauf ein.

**Kosten:** Mit Abo-Anmeldung fallen keine zusätzlichen Kosten an; der Lauf zählt auf die
Nutzungslimits des Abos. `kosten_usd` in `analyse.json` ist nur der Gegenwert zu API-Preisen,
den Claude Code immer mitliefert. Die Oberfläche zeigt ihn deshalb nicht an.

**Nutzungslimits:** Jedes Standbild, das der Agent ansieht, kostet Tokens. Bei
Aufnahmen mit Hunderten Bildern kann eine Analyse einen spürbaren Teil des Abo-Kontingents
belegen. Dann hilft es, mit `--frame-sensitivity grob` oder `--frame-min-gap` weniger Bilder
zu erzeugen.

**Nachbessern (experimentell):** `analyze … --resume --context-text "Ergänze …"` setzt
die gespeicherte Sitzung fort; der Agent kennt dabei den bisherigen Verlauf. Das ist die
Grundlage für einen späteren Dialogmodus.

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

## GPU-Betrieb (CUDA)

```bash
uv sync --extra cu124 --extra review     # CUDA-Wheels installieren (einmalig)

.venv/bin/audioscribe run input/meeting.mp4      # Windows: .venv\Scripts\audioscribe.exe
.venv/bin/audioscribe ui

# mit uv: die Extras MÜSSEN mit — sonst synct uv die CUDA-Wheels wieder weg
uv run --extra cu124 --extra review audioscribe ui
```

- `--device auto` (Default) nimmt CUDA, sonst CPU. `--device cuda` erzwingt sie (bricht
  ohne CUDA ab), `--device cpu` schaltet sie aus. Dasselbe über `AUDIOSCRIBE_DEVICE`.
- `--compute-type` folgt dem Gerät (`cuda → float16`, `cpu → int8`); bei knappem VRAM
  `--compute-type int8_float16`, notfalls `AUDIOSCRIBE_BATCH_SIZE=4` (kein CLI-Flag).
- Prüfen mit `audioscribe doctor`: dort muss `torch …+cu124 -> auto=cuda (<GPU-Name>)`
  stehen. Steht da `+cpu`, hat ein `uv run` ohne Extras die Wheels ersetzt.

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

- Das gewählte Extra gehört **auch an `uv run`** — ohne Extra synct uv die Umgebung
  zurück auf das PyPI-torch. Unter Linux ist das das CUDA-Bundle (~3 GB mehr, läuft
  auch auf CPU), unter Windows ein reiner CPU-Build (dann ist die GPU weg). Wer das
  umgehen will, startet die Skripte direkt aus dem venv.

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
übergeordnete Meeting-Protokoll-Pipeline; die Auswertung übernimmt optional der
Claude-Agent (`audioscribe analyze`, PRD §16).

## Befehle auf einen Blick

Alle Befehle im Projektordner ausführen (`cd ~/develop/git/audioscribe`). Starte sie
direkt aus `.venv/bin/`, **nicht** mit `uv run`: Ohne Extras würde `uv run` die
CUDA-Pakete, die Oberfläche und das Agent SDK aus der Umgebung entfernen.

**Einrichten (einmalig bzw. nach Updates)**

```bash
uv sync --extra cu124 --extra review --extra agent   # GPU-Rechner
uv sync --extra cpu   --extra review --extra agent   # Rechner ohne NVIDIA-Karte
claude                                               # einmal mit dem Claude-Abo anmelden (für analyze)
.venv/bin/audioscribe doctor                         # Umgebung prüfen
```

**Browser-Oberfläche (Transkription + KI-Analyse)**

```bash
.venv/bin/audioscribe ui                   # http://127.0.0.1:8766, Reiter „Transkription“ / „KI-Analyse“
.venv/bin/audioscribe ui --port 9000       # anderer Port
.venv/bin/audioscribe ui --no-browser      # Browser nicht automatisch öffnen
```

Beenden mit Strg+C. Unter WSL die Adresse notfalls selbst im Windows-Browser öffnen.

**Transkribieren (einzelne Datei)**

```bash
.venv/bin/audioscribe run input/meeting.m4a                  # -> output/meeting/transkript.md
.venv/bin/audioscribe run input/demo.mp4 --frames            # Bildschirmaufnahme: + Standbilder
.venv/bin/audioscribe run input/demo.mp4 --frames --pdf      # zusätzlich PDF
.venv/bin/audioscribe run input/x.mp3 --no-diarize --language auto
.venv/bin/audioscribe run input/x.mp3 --num-speakers 3 --device cpu
```

**KI-Analyse per Claude-Agent**

```bash
.venv/bin/audioscribe analyze --list-skills                  # verfügbare Skills (* = Vorauswahl)
.venv/bin/audioscribe analyze output/demo                    # fragt Prozessname + Ausgabeordner ab
.venv/bin/audioscribe analyze output/demo --name "Rechnungsprüfung" --out ~/Analysen \
    --context-text "Zielgruppe: neue Kollegen" --context glossar.md \
    --skill prozessrekonstruktion --skill prozessdoku-qs
.venv/bin/audioscribe analyze output/demo --name "Rechnungsprüfung" --out ~/Analysen \
    --resume --context-text "Ergänze die Ausnahmefälle"      # Sitzung fortsetzen (experimentell)
```

Weitere Schalter: `--no-skills`, `--skills-dir PFAD`, `--model claude-sonnet-5`,
`--max-turns N`, `--no-bash`.

**Standbilder von Hand markieren und exportieren**

```bash
.venv/bin/audioscribe review output/demo                     # http://127.0.0.1:8765
.venv/bin/audioscribe export output/demo --pdf               # -> transkript.annotiert.md (+ PDF)
```

**Hilfe und Tests**

```bash
.venv/bin/audioscribe --help                                 # alle Befehle
.venv/bin/audioscribe analyze --help                         # alle Optionen eines Befehls
uv run --extra cu124 --extra review --extra agent pytest     # Unit-Tests
```
