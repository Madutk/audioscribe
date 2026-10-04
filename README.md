# AudioScribe

Lokale **Audio-Transkription mit Sprecher-Trennung**. Aus einer Meeting-Aufnahme (Audio
oder Video) entsteht ein zeitgestempeltes Markdown-Transkript mit `Sprecher 1 / 2 / 3`.
Alles läuft **auf dem eigenen Rechner**; online geht nur der einmalige Download der
Modellgewichte.

**Was AudioScribe kann**

| Funktion | Kurz gesagt | Details |
|---|---|---|
| Offline-Transkription | Datei oder ganzer Ordner → `transkript.md` (+ PDF), Sprecher getrennt | [Kommandozeile](#kommandozeile), [Oberfläche](#browser-oberfläche) |
| Bildwechsel-Erkennung | Bei Bildschirmaufnahmen je Folien-/Fensterwechsel ein Standbild im Transkript | [→](#bildwechsel-automatisch-erkennen) |
| Bild-Annotation | Standbilder von Hand markieren und ins Transkript einfügen | [→](#bild-annotation-von-hand) |
| KI-Analyse | Claude-Agent macht aus Transkript und Bildern Prozessdoku, Prozessbild, BPMN | [→](#ki-analyse-per-claude-agent) |
| Live-Transkription | Monitor, System-Audio und Mikrofon live mitschneiden (Windows, macOS) | [→](#live-transkription-windows-und-macos) |

**Technik:** WhisperX mit faster-whisper `large-v3` (Transkription) → wav2vec2
(Wort-Alignment) → pyannote `speaker-diarization-3.1` (Sprecher). Die Modelle laufen
nacheinander; der VRAM wird zwischen den Stufen freigegeben (Ziel: RTX 3080, 8 GB).
Läuft auf **NVIDIA-GPU** (schnell), **Apple Silicon** (MLX für Whisper, MPS für den Rest,
siehe [macOS](#macos-startsh--audioscribecommand)) oder **nur CPU** (deutlich langsamer).

---

## Schnellstart

Voraussetzungen: Linux oder WSL2 (Ubuntu 24.04), Python 3.12, [uv](https://docs.astral.sh/uv/).
`ffmpeg` ist gebündelt, kein System-Paket nötig. Unter Windows siehe
[Windows](#windows-startps1), auf dem Mac [macOS](#macos-startsh--audioscribecommand)
(dort erledigt `start.sh` die Schritte 1, 2 und 4).

```bash
# 1) uv installieren (einmalig)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2) Abhängigkeiten – GENAU EINE Backend-Variante wählen
uv sync --extra cu124 --extra review --extra agent   # Rechner MIT NVIDIA-GPU
uv sync --extra cpu   --extra review --extra agent   # Rechner OHNE NVIDIA-Karte (~3 GB kleiner)
uv sync --extra cpu --extra mac --extra review --extra agent --extra live   # Mac mit Apple Silicon

# 3) HuggingFace-Token für die Sprecher-Trennung hinterlegen
cp .env.example .env            # HF_TOKEN=... eintragen, Modell-Bedingungen einmalig akzeptieren:
                                # https://huggingface.co/pyannote/speaker-diarization-3.1
                                # https://huggingface.co/pyannote/segmentation-3.0

# 4) Umgebung prüfen und loslegen
.venv/bin/audioscribe doctor
.venv/bin/audioscribe ui                        # Browser-Oberfläche, http://127.0.0.1:8766
.venv/bin/audioscribe run input/meeting.m4a     # oder direkt eine Datei
```

Die Extras: `review` = Browser-Oberflächen (FastAPI), `agent` = KI-Analyse (Claude Agent
SDK), `live` = Live-Transkription (Windows, macOS), `mac` = Apple Silicon (mlx-whisper,
sounddevice, PyObjC). Für `analyze` einmal `claude` starten und mit dem Claude-Abo anmelden.

> **Wichtig: `uv run` ohne Extras zerstört die Umgebung.** `uv run` synct vor jedem Start,
> und ohne `--extra …` ersetzt es die CUDA-Wheels durch die von PyPI und entfernt
> Oberfläche und Agent SDK. Darum entweder immer `uv run --extra cu124 --extra review
> --extra agent …` schreiben oder, kürzer, die Programme **direkt aus `.venv/bin/`**
> starten. Diese README verwendet durchgehend `.venv/bin/audioscribe`.

Beim ersten Lauf werden die Modelle einmalig geladen und unter `~/.cache` abgelegt:
Whisper `large-v3` (~3 GB), das deutsche Alignment-Modell (~360 MB), die pyannote-Modelle.
Danach läuft alles offline.

### Windows (`start.ps1`)

```powershell
.\start.ps1                     # wählt cpu|cu124 selbst, synct .venv-win, startet die Oberfläche
.\start.ps1 -Torch cpu -Port 8800 -NoBrowser
.venv-win\Scripts\audioscribe.exe doctor
```

`start.ps1` legt die Windows-Umgebung bewusst in `.venv-win` an: Wird das Repo auch aus WSL
benutzt, gehört `.venv` dem Linux-Python, und Windows-`uv` würde daran scheitern. Wer
`uv sync` von Hand aufruft, setzt vorher `$env:UV_PROJECT_ENVIRONMENT = '.venv-win'`.

### macOS (`start.sh` / `AudioScribe.command`)

MacBook Pro mit M4 oder M5 (M1–M3 laufen, langsamer), macOS 14 oder neuer. Alles bleibt in
Python: kein Homebrew, kein virtuelles Audiogerät, nur `uv`-Pakete.

> **Stand:** implementiert und mit Attrappen getestet, auf einem echten Mac aber noch nicht
> geprüft. Die Abnahme-Checkliste steht in PRD §19.5; der erste Schritt ist
> `./start.sh --doctor`, der zweite der ScreenCaptureKit-Spike (unten bei den Befehlen).

```bash
./start.sh                      # installiert uv und Python 3.12 bei Bedarf, synct .venv-mac, startet die Oberfläche
./start.sh --doctor             # Umgebung prüfen: macOS-Version, Chip, mps, mlx-whisper, Berechtigungen
./start.sh --devices            # Mikrofone, System-Audio (ScreenCaptureKit), Monitore, Fenster
.venv-mac/bin/audioscribe run input/meeting.m4a   # direkt, ohne uv run
```

`AudioScribe.command` ist dasselbe für den **Doppelklick im Finder** (öffnet Terminal.app).
Kommt das Repo als ZIP statt per `git clone`, blockt Gatekeeper die Datei einmal:
`xattr -d com.apple.quarantine AudioScribe.command`.

**Berechtigungen:** Beim ersten „Aufnahme starten“ fragt macOS nach **Mikrofon** und
**Bildschirmaufnahme** (letztere liefert über ScreenCaptureKit auch das System-Audio).
Beide gehören der *startenden App* (Terminal, iTerm, VS Code), nicht „Python“, und die
Bildschirmaufnahme wirkt erst, nachdem diese App neu gestartet wurde. `doctor` und der
Live-Reiter sagen, was fehlt und wo es steht (Systemeinstellungen › Datenschutz &
Sicherheit).

**Was wo rechnet:** faster-whisper/CTranslate2 kennt kein Metal und liefe auf dem Mac nur
auf der CPU. Darum rechnet Whisper über **mlx-whisper** auf der GPU (Live, `run` und
Nachschärfen), Sprecher-Modelle und Alignment über **PyTorch/MPS**. `--device auto` wählt
`mps`, `--backend auto` wählt `mlx`; `--backend faster-whisper` erzwingt die CPU-Variante
zum Vergleich. Die Umgebung heißt `.venv-mac` – aus demselben Grund wie `.venv-win`.

---

## Browser-Oberfläche

`audioscribe ui` startet eine schlanke lokale Oberfläche (nur `localhost`, kein Upload) mit
vier Reitern. Alle Läufe laufen **im Server weiter**, der Browser-Tab darf geschlossen
werden; beendet wird mit „Abbrechen“ oder Strg+C im Terminal.

```bash
.venv/bin/audioscribe ui                      # http://127.0.0.1:8766
.venv/bin/audioscribe ui --port 9000 --no-browser
```

**Einstellungen** – die drei Standardordner für alle Reiter: Eingangsordner,
Ausgabeordner Transkription (gemeinsam für Offline und Live) und Ausgabeordner Analysen.
Pfade aus dem Explorer (`C:\Users\…`) lassen sich direkt einfügen; „Wählen“ öffnet einen
Ordner-Browser mit Schnellzielen (Laufwerke, Home, Desktop, Downloads, Videos). Alle
Einstellungen werden **serverseitig gemerkt** und überleben Neustart und Adresswechsel.
Die Karte **Umgebung** zeigt die Prüfzeilen von `audioscribe doctor` (ffmpeg, Gerät,
WhisperX, HF-Token, Live-Geräte) direkt in der Seite.

**Offline Transcription** – Stapelverarbeitung des Eingangsordners. Die Dateiliste zeigt
alle Medien mit Länge und Größe; vorausgewählt sind die noch offenen („Alle“, „Nur offene“,
„Keine“). Optionen: Modell, Sprache, Gerät, Sprecher-Trennung, Bildwechsel-Erkennung.
Je Datei ein Fortschrittsbalken, dazu Gesamtbalken und **Restzeit** (geschätzt aus den
bereits fertigen Dateien, erscheint also ab der zweiten). Schlägt eine Datei fehl, läuft
der Stapel weiter; das Protokoll klappt dann von selbst auf.

**Live Transcription** – siehe [Live-Transkription](#live-transkription-nur-windows).

**KI-Analyse** – siehe [KI-Analyse](#ki-analyse-per-claude-agent).

Die Reiter sind auch per Adresse erreichbar (`#trans`, `#live`, `#ana`, `#set`). Der Knopf
oben rechts schaltet das Design (System / Hell / Dunkel).

**Unter WSL** die Adresse im Windows-Browser öffnen; WSL2 leitet `127.0.0.1` durch. Pfade
werden in beide Richtungen umgesetzt (`C:\Users\…` ↔ `/mnt/c/Users/…`). Medien auf dem
WSL-Dateisystem werden spürbar schneller gelesen als unter `/mnt/c`.

---

## Kommandozeile

```bash
.venv/bin/audioscribe run input/meeting.m4a                 # -> output/meeting/transkript.md
.venv/bin/audioscribe run input/meeting.mp4                 # Video: Tonspur wird vorab extrahiert
.venv/bin/audioscribe run input/meeting.m4a --pdf           # zusätzlich PDF
.venv/bin/audioscribe run input/meeting.m4a --no-diarize --language auto   # ohne Sprecher, Sprache erkennen
.venv/bin/audioscribe run input/meeting.m4a --num-speakers 3               # oder --min-speakers 2 --max-speakers 5
.venv/bin/audioscribe run input/meeting.m4a --sentences-per-timestamp 3    # Zeitstempel alle N Sätze (Default 2, 0 = ganzer Beitrag)
.venv/bin/audioscribe run input/meeting.m4a --device cpu                   # Default auto: CUDA falls da, sonst CPU
.venv/bin/audioscribe run input/demo.mkv --frames                          # Bildschirmaufnahme: Standbilder je Bildwechsel
```

**Video** wird wie Audio behandelt: Die Tonspur wird mit dem gebündelten ffmpeg als
16-kHz-Mono-WAV nach `work/<name>.16k.wav` geschrieben und bleibt dort liegen. Unterstützt:
`mp4 mkv mov avi webm m4v wmv flv mpg mpeg ts m2ts 3gp ogv`. Ohne Tonspur bricht der Lauf
mit klarer Meldung ab; Ton ohne Sprache ergibt ein leeres Transkript.

**Ausgabe** `output/<name>/transkript.md`:

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

**[00:01:23] Sprecher 1:** Guten Morgen, fangen wir an. Schön, dass alle da sind.
**[00:01:31] Sprecher 1:** Heute geht es um das Quartalsergebnis. Ich teile gleich den Bildschirm.
**[00:01:44] Sprecher 2:** Ja, einverstanden …
```

Alle zwei Sätze steht ein neuer Zeitstempel, auch innerhalb eines langen Beitrags; die Zeit
stammt aus dem Wort-Alignment (ohne `--no-align` fällt sie auf Segment-Ebene zurück). Namen
trägt man im Markdown von Hand nach; es ist das editierbare Primärformat, PDF wird daraus
erzeugt. Fortschrittszeilen im Terminal: `AUDIOSCRIBE_PROGRESS=1`.

---

## Bildwechsel automatisch erkennen

Für **Bildschirmaufnahmen**: AudioScribe erkennt Wechsel des Bildschirminhalts und sichert
je Wechsel ein Standbild. Mausbewegungen lösen nichts aus.

```bash
.venv/bin/audioscribe run input/demo.mkv --frames
    --frame-sensitivity grob|mittel|fein   # Default mittel
    --frame-format jpg-1600|jpg-1280|png   # Default jpg-1600 (~150 KB je Bild)
    --frame-fps 1                          # Abtastungen/s, Default 2
    --frame-min-gap 8                      # Mindestabstand in s, Default 4
```

Ergebnis: `output/<name>/frames/0001_00-01-23.jpg …` und `transkript.annotiert.md`, in dem
jedes Bild mit seiner ID am passenden Absatz steht. Über die ID („Bild #0001“) lassen sich
Transkript und Bilder gemeinsam einer KI vorlegen.

```
**[00:01:20] Sprecher 1:** Hier seht ihr die Auswertung …

![Bild #0001 – 00:01:23](frames/0001_00-01-23.jpg)
```

<details>
<summary>Wie es arbeitet und was es kostet</summary>

Ein ffmpeg-Durchlauf verkleinert das Video auf 192×108 Graustufen; verglichen wird über ein
Raster aus 16×9 Blöcken. Ein Mauszeiger belegt einen Block und bleibt unter der Schwelle,
ein Fenster- oder Folienwechsel betrifft Dutzende. Zusammenhängende Trefferserien
(Animationen, Scrollen) ergeben **ein** Bild, aufgenommen am Ende der Serie.

Kosten: grob ein Achtel der Videolänge (80 Minuten ≈ 10 Minuten), deshalb standardmäßig
aus. Ein erneuter Lauf ersetzt die automatischen Bilder und lässt von Hand gesetzte
Markierungen unberührt. In der Oberfläche stehen Checkbox, Empfindlichkeit und Bildformat
in der Karte „Optionen“; `--frame-fps` und `--frame-min-gap` gibt es nur auf der
Kommandozeile.
</details>

---

## Bild-Annotation von Hand

Nach der Transkription wichtige Standbilder (Folien, geteilte Bildschirme) selbst markieren
und an der zeitlich passenden Stelle ins Transkript einfügen.

```bash
.venv/bin/audioscribe run input/meeting.mp4        # schreibt zusätzlich transcript.json
.venv/bin/audioscribe review output/meeting        # Review-Oberfläche, http://127.0.0.1:8765
.venv/bin/audioscribe export output/meeting --pdf  # -> transkript.annotiert.md (+ PDF)
```

<details>
<summary>Ablauf und Artefakte</summary>

Das Video ist scrubbar, das Transkript läuft synchron mit (Klick auf eine Zeile springt im
Video dorthin). **„Frame markieren“** greift den aktuellen Zeitpunkt abzüglich eines
**Lag-Offsets** (Default −2,5 s, justierbar), extrahiert per ffmpeg ein framegenaues PNG
und legt eine Markierung an, optional mit Notiz. Markierungen erscheinen als
Thumbnail-Liste und lassen sich einzeln löschen.

`export` fügt Transkript und Markierungen zu `transkript.annotiert.md` zusammen; das
editierbare `transkript.md` bleibt unberührt. Artefakte: `transcript.json`,
`frames/<HH-MM-SS>.png`, `marks.json`. Die Markierungen überstehen erneute
Transkriptionsläufe, weil die Einfügeposition beim Export aus dem Zeitstempel berechnet
wird.
</details>

---

## KI-Analyse per Claude-Agent

Ein Claude-Agent wertet einen fertigen Ergebnisordner aus (Transkript und Standbilder) und
schreibt Dokumente in einen Ordner deiner Wahl. Du gibst ihm einen **Prozessnamen**, freien
**Kontext** und **Skills** mit; die Skills legen Aufbau und Qualitätsmaßstab fest, etwa
`prozessrekonstruktion`, `prozessdoku-qs`, `arbeitsanweisung-ableiten`.

```bash
claude                                                  # einmalig: mit dem Claude-Abo anmelden, dann beenden
.venv/bin/audioscribe analyze --list-skills             # verfügbare Skills (* = Vorauswahl)
.venv/bin/audioscribe analyze output/demo \
    --name "Rechnungsprüfung Kreditoren" --out ~/Analysen \
    --context-text "Zielgruppe: neue Kollegen in der Kreditorenbuchhaltung" \
    --context glossar.md \
    --skill transkript-normalisierung --skill prozessrekonstruktion --skill prozessdoku-qs
```

Fehlen `--name` oder `--out`, fragt der Befehl nach. Weitere Schalter: `--no-skills`,
`--skills-dir PFAD` (Default `~/.claude/skills`, rekursiv), `--model` (Default
`claude-opus-5`), `--max-turns N`, `--no-bash`, `--no-prozessbild`, `--no-bpmn`.

**In der Oberfläche** (Reiter „KI-Analyse“): fertige Transkription aus dem Ausgabeordner
wählen, Prozessname und Kontext eingeben, Skills ankreuzen. Der Ausgabeordner kommt aus
den Einstellungen. Der Fortschritt zeigt den Plan des Agenten als Schrittliste, den aktiven
Skill, angesehene Standbilder und geschriebene Dokumente. Einen Prozentwert gibt es bewusst
nicht; ergänzt der Agent Schritte, läuft der Balken auch zurück.

**Abrechnung:** Die Anbindung läuft über das
[Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk) und nutzt die Anmeldung von
Claude Code. Mit Pro-/Max-Abo braucht es keinen API-Key und es fallen keine zusätzlichen
Kosten an. **Achtung:** Ein gesetzter `ANTHROPIC_API_KEY` hat Vorrang und rechnet über
das API-Guthaben ab; `audioscribe doctor` zeigt, welcher Weg aktiv ist. Jedes angesehene
Standbild kostet Tokens; bei Hunderten Bildern helfen `--frame-sensitivity grob` oder ein
größerer `--frame-min-gap`.

<details>
<summary>Ergebnisordner</summary>

```
<out>/<prozessname>/
  INDEX.md                  # vom Agenten: Übersicht aller Dokumente, offene Punkte, Annahmen
  prozessdokumentation.md   # … je nach Skills und Kontext
  prozessbild.png / .svg    # Prozessdiagramm als Bild (Word, PowerPoint, Confluence)
  prozessbild.mmd           # dessen Mermaid-Quelltext
  bpmn-modell.bpmn          # BPMN 2.0 mit Lanes (Camunda Modeler, bpmn.io, Signavio …)
  bpmn-modell.png / .svg    # BPMN-Modell als Bild
  bpmn-modell.json          # dessen Fachlogik vom Agenten
  material/                 # Kopie von Transkript, frames/, marks.json
  kontext/                  # Kopie der Kontextdateien
  analyse.json              # Protokoll: Skills, Modell, Session-ID, Dauer, kosten_usd (nur Gegenwert)
  agent-log.txt             # vollständiger Verlauf
  .claude/skills/           # die verwendeten Skills (Stand der Analyse)
```

Der Agent schreibt **nur** in diesen Ordner; Schreibversuche außerhalb werden abgelehnt und
als `[Verweigert]` protokolliert. Er arbeitet auf einer Kopie, der audioscribe-Ergebnisordner
bleibt unverändert. Deine übrigen Claude-Code-Skills, MCP-Server und die globale
`CLAUDE.md` fließen nicht ein.
</details>

<details>
<summary>Prozessbild (Mermaid → PNG/SVG)</summary>

Enthält die Prozessdoku ein Mermaid-Diagramm, erzeugt audioscribe daraus `prozessbild.png`
(doppelte Auflösung, weißer Hintergrund) und `prozessbild.svg`; bei mehreren Prozessen
`prozessbild-2.png` usw. Gerendert wird mit dem vorhandenen **Edge oder Chrome** im
Hintergrund (unter WSL der Windows-Browser), die Mermaid-Bibliothek liegt im Paket, es
funktioniert offline. Nach einer Handkorrektur von `prozessbild.mmd`:

```bash
.venv/bin/audioscribe prozessbild ~/Analysen/rechnungspruefung
```

Fehlt ein Browser oder hat das Diagramm einen Syntaxfehler, steht das im Protokoll, und die
Analyse gilt trotzdem als fertig. `AUDIOSCRIBE_BROWSER=<pfad>` legt einen anderen Browser
fest.
</details>

<details>
<summary>BPMN-Modell mit Lanes</summary>

`bpmn-modell.bpmn` ist ein BPMN-2.0-Modell für
[Camunda Modeler](https://camunda.com/download/modeler/), https://demo.bpmn.io, Signavio
oder ADONIS, dazu `.png` und `.svg`.

- **Lanes** sind Rollen, wenn mehrere Beteiligte erkennbar sind (etwa aus deinem Kontext),
  sonst die verwendeten Systeme. Die Begründung steht in der Doku.
- **Nummern** (S1, E1 …) sind dieselben wie in Doku und Prozessbild.
- **Arbeitsteilung:** Der Agent liefert nur die Fachlogik (`bpmn-modell.json`) und prüft
  sie mit `audioscribe bpmn . --pruefen`; Layout, XML und Bild erzeugt audioscribe.
- **Grenzen:** Layout automatisch, aber nicht perfekt; ein Modell je Prozess, ohne
  Unterprozesse und parallele Gateways.
- **Nach dem Bearbeiten** im BPMN-Werkzeug ist die `.bpmn` maßgeblich; `audioscribe bpmn
  <ordner>` baut sie nur mit `--neu` aus dem JSON neu auf.

```bash
.venv/bin/audioscribe bpmn ~/Analysen/rechnungspruefung --pruefen   # nur prüfen
.venv/bin/audioscribe bpmn ~/Analysen/rechnungspruefung             # -> .bpmn + .png + .svg
.venv/bin/audioscribe bpmn ~/Analysen/rechnungspruefung --neu       # auch bearbeitete .bpmn ersetzen
```

`--no-bpmn` bzw. `AUDIOSCRIBE_AGENT_BPMN=0` schaltet das Modell ab.
</details>

<details>
<summary>Nachbessern (experimentell)</summary>

`analyze … --resume --context-text "Ergänze die Ausnahmefälle"` setzt die gespeicherte
Sitzung fort; der Agent kennt den bisherigen Verlauf. Grundlage für einen späteren
Dialogmodus.
</details>

---

## Live-Transkription (Windows und macOS)

Proof of Concept: schneidet eine laufende Sitzung mit, also einen Monitor **oder ein
Anwendungsfenster**, das System-Audio und das Mikrofon. Das Transkript erscheint mit
wenigen Sekunden Verzögerung, jeder Bildwechsel wird als Screenshot gesichert, und am Ende
liegt ein Ordner im Format eines Offline-Laufs, den die KI-Analyse direkt auswerten kann.
Braucht natives Windows-Python (WASAPI-Loopback) oder macOS (ScreenCaptureKit liefert das
System-Audio, sounddevice das Mikrofon – ohne BlackHole oder andere Treiber); unter WSL geht
nur das WAV-Replay. Designentscheidungen: PRD §17 und §19.

```powershell
.\start.ps1                                                  # Oberfläche, Reiter „Live Transcription“
.venv-win\Scripts\audioscribe.exe doctor                     # Zeile „Live“: Mikrofone, Loopback, Monitore
.venv-win\Scripts\audioscribe.exe live --list-devices        # ohne Oberfläche: Geräte, Monitore, Fenster (HWND)
.venv-win\Scripts\audioscribe.exe live --monitor 1 --mic 23  # Ende mit Strg+C oder "stop" + Enter
.venv-win\Scripts\audioscribe.exe live --window 592902       # nur dieses Fenster
.venv-win\Scripts\audioscribe.exe refine output\live-2026-09-19_14-30-05 --model large-v3-turbo
```

```bash
./start.sh                                                   # macOS: Oberfläche, Reiter „Live Transcription“
.venv-mac/bin/audioscribe live --list-devices                # Mikrofone, „System-Audio (ScreenCaptureKit)“, Monitore, Fenster
.venv-mac/bin/audioscribe live --monitor 1                   # Ende mit Strg+C oder "stop" + Enter
.venv-mac/bin/audioscribe refine output/live-2026-09-19_14-30-05
```

**Im Reiter:** Bildquelle wählen (Monitor mit Vorschaubild, Anwendungsfenster oder „nur
Ton“), Mikrofon und System-Audio wählen, „Aufnahme starten“. Oben laufen Laufzeit,
**Verzögerung** (Ende des Gesprochenen bis zur Anzeige) und **Rückstand** mit. Rückstand ist
fertig gesprochenes Audio, das auf die Transkription *wartet*; der Abschnitt, der gerade
gerechnet wird, zählt nicht mit. Screenshots erscheinen rechts als Thumbnails. Gespeichert
wird im Ausgabeordner Transkription aus den Einstellungen:

```
output/live-2026-09-19_14-30-05/
  transkript.md  transcript.json  transkript.annotiert.md  marks.json  frames/
  transkript.txt                                  # reiner Text ohne Zeitstempel/Sprecher (WER-Vergleich)
  transkript.live.md  transcript.live.json  transkript.live.txt   # Live-Fassung (nach dem Stopp)
  audio/mikrofon.wav  audio/system.wav            # 16 kHz mono
  bilanz.json                                     # Fazit: Rechendauer und Latenz (live + nachschaerfen)
  diagnose.jsonl                                  # je Abschnitt und Vorschau eine Zeile (Zeiten, Qualitaet)
```

**Zwei Fallstricke:** Mit Lautsprechern statt Headset hört das Mikrofon die Gegenseite mit,
dann stehen Textstellen doppelt. Und bei Monitoraufnahme gehört die AudioScribe-Oberfläche
nicht auf den überwachten Monitor, sonst lösen neue Thumbnails selbst Bildwechsel aus.

<details>
<summary>Modelle, Sprecher, Nachschärfen</summary>

**Modell:** `auto` nimmt `large-v3-turbo` auf der GPU und auf Apple Silicon (MLX) und
`small` auf der CPU. Das Modell fürs **Nachschärfen** wird getrennt gewählt (Standard
`large-v3`): live zählt das Tempo, danach die Genauigkeit.

**Verzögerung:** Ein Abschnitt ist frühestens ~1 s nach dem letzten Wort fertig (Pause
0,6 s plus Puffer und VAD-Takt), dann kommt die Rechenzeit dazu. Erwartung je Abschnitt:
NVIDIA-GPU 2–5 s, M4 Pro/Max und M5 etwa 1,8–2,5 s, Basis-M4 2,5–3,5 s, CPU 5–15 s. Wer
auf GPU oder MLX noch näher heran will: `AUDIOSCRIBE_LIVE_PAUSE_S=0.45`,
`AUDIOSCRIBE_LIVE_PARTIAL_INTERVAL_S=1.0`, `AUDIOSCRIBE_LIVE_VAD_EVERY_TICK=1` (mehr
Schnitte mitten im Satz, mehr Rechenlast). Die Werte stehen nach jeder Sitzung in
`bilanz.json`; Messläufe gehen reproduzierbar per WAV-Replay (unten).

**Sprecher:** Das Mikrofon ist „Ich“. Das System-Audio wird per Stimm-Embedding in
„Sprecher 1/2/3“ getrennt (braucht den `HF_TOKEN`); ohne Token heißt die Spur
„Gegenseite“. Das Sprecher-Modell lädt im Hintergrund, Mikrofon-Text erscheint sofort, der
erste System-Abschnitt sobald das Protokoll „Sprecher-Modell bereit“ meldet. Kurze Einwürfe
und Durcheinanderreden trennt erst das Nachschärfen sauber.

**Nach dem Stopp** bleibt die Live-Fassung als `transkript.live.md` erhalten. Mit „nach
Stopp nachschärfen“ läuft die Offline-Pipeline (Alignment, Diarisierung der System-Spur)
über den Mitschnitt und ersetzt `transkript.md`; die Screenshots bleiben. Ein zweiter Klick
auf Stoppen bricht hart ab. Danach zeigt der Reiter ein **Fazit**: Aufnahmedauer, Ladezeit,
Rechenzeit und Tempo (Rechenzeit je Audiosekunde, nur das Dekodieren; daneben „inkl.
Vorschau“), Verzögerung (Ø, Median, max), Abschnitte (davon zusammengelegt bzw. sparsam
dekodiert), höchster Rückstand und Zeit im Aufholmodus, nach dem Nachschärfen die Dauer je
Stufe. Dieselben Zahlen stehen im Protokoll und in `bilanz.json`.

**Diagnose-Log:** Das Fazit ist aus `diagnose.jsonl` abgeleitet, einer JSON-Lines-Datei mit
einer Zeile je fertigem Abschnitt (`art: "abschnitt"`): Lage im Audio, Zeitpunkte auf der
Sitzungsuhr, `wartezeit_s`, `rechenzeit_s`, `sprecher_s`, `latenz_s`, Modell, `eco`
(sparsam dekodiert), Wortzahl, `schluss` (`pause`, `zeitlimit`, `flush`) und je
Whisper-Segment `avg_logprob`, `compression_ratio`, `no_speech_prob`, `temperature` (> 0
heißt: der Fallback hat gegriffen). Vorschauen stehen als eigene Zeilen, das Nachschärfen
hängt je Segment und je Stufe eine Zeile an. Für Messläufe erzwingt `audioscribe live --eco`
den Sparmodus für alle Abschnitte.

**Zurücksetzen** leert nach Rückfrage Transkript, Screenshots und Protokoll. Während einer
Aufnahme heißt der Knopf „Verwerfen und neu beginnen“: Die Sitzung wird hart beendet (ohne
Nachschärfen) und mit denselben Einstellungen neu gestartet; der alte Ordner bleibt liegen.
</details>

<details>
<summary>Vorschau, Aufholmodus, CPU-Tuning</summary>

Grauer Kursivtext ist die Vorschau des gerade gesprochenen Abschnitts; sie pausiert ab 3 s
Rückstand. Ab 5 s Rückstand schaltet die Sitzung in den **Aufholmodus**: wartende
Abschnitte derselben Spur werden zu Stücken bis 25 s zusammengelegt und sparsamer dekodiert
(Beam 1). Die Segmente sind dann gröber, der Rückstand pendelt sich aber auch auf der CPU
ein. Der Tooltip der Rückstand-Anzeige zeigt das gemessene Tempo (Rechenzeit je
Audiosekunde); liegt es dauerhaft über 1× Echtzeit, ist das Modell für den Rechner zu groß.
`AUDIOSCRIBE_CPU_THREADS` bzw. `--cpu-threads` setzt die Rechen-Threads; sinnvoll ist die
Zahl physischer Kerne.
</details>

<details>
<summary>Messläufe ohne Aufnahme (WAV-Replay)</summary>

`live --wav DATEI` schickt eine WAV-Datei als System-Audio durch dieselbe Pipeline, als käme
sie gerade aus dem Lautsprecher: derselbe Schnitt, dieselbe Warteschlange, dasselbe Fazit und
Diagnose-Log. `--wav-mic DATEI` spielt eine zweite Datei als Mikrofon. Standbilder gibt es
dabei nicht, und es läuft auch unter Linux. Die Sitzung endet von selbst, sobald die Datei
durch ist. So lassen sich Modelle und Schnitt-Einstellungen reproduzierbar gegen ein
Referenztranskript messen, etwa mit `transkript.txt` und einem WER-Werkzeug. `--speed 4`
lässt die Sitzungsuhr viermal so schnell laufen; das taugt für Funktionstests, nicht für
Latenzwerte.

```powershell
.venv-win\Scripts\audioscribe.exe live --wav referenz.wav --model base --device cpu --no-speakers --no-partials
.venv-win\Scripts\audioscribe.exe live --wav referenz.wav --model base --device cpu --no-speakers --eco
```
</details>

<details>
<summary>Anwendungsfenster statt Monitor</summary>

Die Kachel **Anwendungsfenster** öffnet eine Auswahl mit Vorschaubildern, nach Anwendung
gebündelt und filterbar. Aufgenommen wird nur dieses Fenster, auch wenn andere davor
liegen; die Oberfläche darf auf demselben Monitor bleiben. Minimiert pausieren die
Standbilder, geschlossen endet nur die Bildaufnahme, der Ton läuft weiter. Grenzen: Erhöhte
(Admin-)Prozesse und exklusive DirectX-Vollbilder liefern kein Fensterbild; dann fällt
AudioScribe auf den Bildschirmausschnitt am Fensterrechteck zurück, inklusive allem, was
davor liegt.
</details>

---

## Betrieb: GPU, CPU, Konfiguration

| | GPU (CUDA) | Apple Silicon (MPS + MLX) | CPU |
|---|---|---|---|
| Installation | `uv sync --extra cu124 …` | `uv sync --extra cpu --extra mac …` | `uv sync --extra cpu …` |
| `--device auto` wählt | `cuda`, `compute_type=float16` | `mps`; Whisper über MLX (`--backend auto`), torch über MPS | `cpu`, `compute_type=int8` |
| Tempo | Bruchteil der Aufnahmedauer | Bruchteil der Aufnahmedauer (Whisper), Diarisierung etwas langsamer als CUDA | Mehrfaches der Aufnahmedauer |
| Wichtigster Hebel | bei knappem VRAM `--compute-type int8_float16`, `AUDIOSCRIBE_BATCH_SIZE=4` | `--backend faster-whisper` nur zum Vergleich (CPU); `PYTORCH_ENABLE_MPS_FALLBACK=1` (setzt `start.sh`) | kleineres Modell: `--model medium` oder `small` |
| `doctor` zeigt | `torch …+cu124 -> auto=cuda (<GPU>)` | `torch 2.6.0 -> auto=mps (Apple M4 …)`, `ASR-Backend mlx-whisper …` | `torch …+cpu -> auto=cpu` |

`--device cuda` erzwingt die GPU (bricht ohne CUDA ab), `--device mps` Metal (nur Apple
Silicon), `--device cpu` schaltet beides aus, auch auf einem GPU-Rechner zum Testen.
`--backend auto|faster-whisper|mlx` (bzw. `AUDIOSCRIBE_ASR_BACKEND`) wählt die
Whisper-Implementierung; `mlx` gibt es nur auf Apple Silicon. Steht in `doctor` unerwartet `+cpu` auf einem
GPU-Rechner, hat ein `uv run` ohne Extras die Wheels ersetzt (siehe
[Schnellstart](#schnellstart)). Die Sprecher-Trennung läuft auf CPU ebenfalls entsprechend
länger.

**Konfiguration:** Alle Defaults stehen in `src/audioscribe/config.py` und lassen sich per
`AUDIOSCRIBE_*`-Umgebungsvariablen oder `.env` überschreiben; `.env.example` listet sie mit
Erklärung.

<details>
<summary>Kompatibilität WhisperX + PyTorch 2.6</summary>

Zwei bekannte Reibungspunkte behandelt `src/audioscribe/compat.py` automatisch:

- **cuDNN** (nur CUDA-Pfad): WhisperX pinnt `ctranslate2<4.5` (gegen cuDNN 8 gebaut), torch
  2.6 bringt cuDNN 9 mit. AudioScribe lädt die cuDNN-8-Bibliotheken einmalig nach
  (`~/.cache/audioscribe/cudnn8/`) und macht sie via `LD_LIBRARY_PATH` auffindbar, ohne
  torchs cuDNN 9 zu stören. Im CPU-Betrieb entfällt der Schritt.
- **`torch.load`:** PyTorch 2.6 lädt standardmäßig mit `weights_only=True`; die
  pyannote-Checkpoints lassen sich damit nicht entpacken. Da alle Gewichte aus
  vertrauenswürdiger lokaler Quelle stammen, wird `weights_only=False` erzwungen.
</details>

---

## Befehle auf einen Blick

Alle Befehle im Projektordner, direkt aus `.venv/bin/` (Windows: `.venv-win\Scripts\…exe`,
macOS: `.venv-mac/bin/…`).

```bash
# Einrichten
uv sync --extra cu124 --extra review --extra agent   # GPU-Rechner; CPU: --extra cpu
claude                                               # einmal mit dem Claude-Abo anmelden (für analyze)
.venv/bin/audioscribe doctor                         # Umgebung prüfen (--json für Maschinen)

# Oberfläche
.venv/bin/audioscribe ui                             # http://127.0.0.1:8766
.venv/bin/audioscribe ui --port 9000 --no-browser

# Transkribieren
.venv/bin/audioscribe run input/meeting.m4a                  # -> output/meeting/transkript.md
.venv/bin/audioscribe run input/demo.mp4 --frames --pdf      # Bildschirmaufnahme + PDF
.venv/bin/audioscribe run input/x.mp3 --no-diarize --language auto
.venv/bin/audioscribe run input/x.mp3 --num-speakers 3 --device cpu

# Standbilder von Hand
.venv/bin/audioscribe review output/demo                     # http://127.0.0.1:8765
.venv/bin/audioscribe export output/demo --pdf               # -> transkript.annotiert.md (+ PDF)

# KI-Analyse
.venv/bin/audioscribe analyze --list-skills
.venv/bin/audioscribe analyze output/demo --name "Rechnungsprüfung" --out ~/Analysen \
    --context-text "Zielgruppe: neue Kollegen" --context glossar.md \
    --skill prozessrekonstruktion --skill prozessdoku-qs
.venv/bin/audioscribe analyze output/demo --name "Rechnungsprüfung" --out ~/Analysen \
    --resume --context-text "Ergänze die Ausnahmefälle"      # Sitzung fortsetzen (experimentell)
.venv/bin/audioscribe prozessbild ~/Analysen/rechnungspruefung          # Prozessbild neu rendern
.venv/bin/audioscribe bpmn ~/Analysen/rechnungspruefung [--pruefen|--neu]

# Live (Windows)
.venv-win\Scripts\audioscribe.exe live --list-devices
.venv-win\Scripts\audioscribe.exe live --monitor 1 --mic 23
.venv-win\Scripts\audioscribe.exe refine output\live-…

# macOS (Apple Silicon)
./start.sh                                                   # Oberfläche; --doctor | --devices | --port N | --no-browser
.venv-mac/bin/audioscribe live --monitor 1                   # System-Audio über ScreenCaptureKit, Whisper über MLX
.venv-mac/bin/audioscribe run input/meeting.m4a --device mps # Whisper über MLX, Alignment/Diarisierung über MPS
.venv-mac/bin/python -m audioscribe.live.capture.sck --probe 5   # Spike: 5 s System-Audio nach /tmp/sck.wav

# Hilfe und Tests
.venv/bin/audioscribe --help                                 # alle Befehle; <befehl> --help für Optionen
.venv/bin/python -m pytest                                   # Unit-Tests (reine Logik, keine Modell-Downloads; Mac: .venv-mac/bin/python)
```

---

## Status

Basisstufe gemäß `PRD.md`: eine Datei pro CLI-Aufruf (die Oberfläche arbeitet Ordner
nacheinander ab), Markdown-Ausgabe mit optionalem PDF, Sprecher als „Sprecher N“ ohne
Personen-Identifikation. AudioScribe ist die Transkriptions-Basis für die übergeordnete
Meeting-Protokoll-Pipeline; die Auswertung übernimmt optional der Claude-Agent. Alle
Anforderungen und Designentscheidungen stehen nummeriert (FR-1 … FR-55) in `PRD.md`; die
macOS-Portierung (PRD §19) ist implementiert und wartet auf die Validierung auf dem Gerät
(Akzeptanzkriterien §19.5).
