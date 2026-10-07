# AudioScribe

Lokale **Audio-Transkription mit Sprecher-Trennung**. Aus einer Meeting-Aufnahme (Audio
oder Video) entsteht ein zeitgestempeltes Markdown-Transkript mit `Sprecher 1 / 2 / 3`.
Alles läuft **auf dem eigenen Rechner**; online geht nur der einmalige Download der
Modellgewichte.

**Was AudioScribe kann**

| Funktion | Kurz gesagt | Details |
|---|---|---|
| Projekte | Ein Projekt je LLM-Wiki mit eigenen Ordnern und Einstellungen; beendete Sitzungen gehen als neue Quelle ins Wiki | [→](#projekte-und-ablage-ins-wiki) |
| Aufnahme transkribieren | Audio- oder Videodatei → `transkript.md` (+ PDF), Sprecher getrennt | [Kommandozeile](#kommandozeile), [Oberfläche](#browser-oberfläche) |
| Bildwechsel-Erkennung | Bei Bildschirmaufnahmen je Folien-/Fensterwechsel ein Standbild im Transkript | [→](#bildwechsel-automatisch-erkennen) |
| Bild-Annotation | Standbilder von Hand markieren und ins Transkript einfügen | [→](#bild-annotation-von-hand) |
| KI-Analyse | Claude-Agent macht aus Transkript und Bildern Prozessdoku, Prozessbild, BPMN | [→](#ki-analyse-per-claude-agent) |
| Live-Transkription | Monitor, System-Audio und Mikrofon live mitschneiden (Windows, macOS); nach einem Absturz fortsetzbar | [→](#live-transkription-windows-und-macos), [Wiederaufnahme](#absturzsicherung-und-wiederaufnahme) |
| Souffleur | Live-Abgleich des Gesagten mit einem LLM-Wiki: Widersprüche, offene Punkte, Fragen mit Antwort aus dem Wiki, Essenz der letzten Minuten – nur für den Moderator | [→](#souffleur-live-abgleich-mit-dem-wiki) |
| Lokale KI | Souffleur (und experimentell die KI-Analyse) mit einem lokalen Modell über Ollama statt Claude – nichts verlässt den Rechner | [→](#lokale-ki-ollama) |

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
`uv sync` von Hand aufruft, setzt vorher `$env:UV_PROJECT_ENVIRONMENT = '.venv-win'` und
`$env:UV_LINK_MODE = 'copy'`.

`start.ps1` setzt `UV_LINK_MODE=copy`: uv kopiert Pakete aus seinem Cache, statt sie per
Hardlink zu verknüpfen. Hat ein anderes Projekt in einem OneDrive-Ordner seine `.venv` per
Hardlink aus demselben Cache gefüllt, macht OneDrive die Cache-Dateien zu Cloud-Dateien –
`uv sync` scheitert dann mit `os error 396` („inkompatible feste Links“) oder `os error 32`
(Datei in Benutzung). Abhilfe: `.venv-win` löschen, die betroffenen Cache-Einträge entfernen
(`uv cache clean <paket>` oder ganz `uv cache clean`) und neu starten. Damit es nicht
wiederkommt, `UV_LINK_MODE=copy` dauerhaft setzen:
`[Environment]::SetEnvironmentVariable('UV_LINK_MODE','copy','User')`.

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
Bildschirmaufnahme wirkt erst, nachdem diese App neu gestartet wurde. `doctor` und die
Live-Ansicht sagen, was fehlt und wo es steht (Systemeinstellungen › Datenschutz &
Sicherheit).

**Was wo rechnet:** faster-whisper/CTranslate2 kennt kein Metal und liefe auf dem Mac nur
auf der CPU. Darum rechnet Whisper über **mlx-whisper** auf der GPU (Live, `run` und
Nachschärfen), Sprecher-Modelle und Alignment über **PyTorch/MPS**. `--device auto` wählt
`mps`, `--backend auto` wählt `mlx`; `--backend faster-whisper` erzwingt die CPU-Variante
zum Vergleich. Die Umgebung heißt `.venv-mac` – aus demselben Grund wie `.venv-win`.

---

## Browser-Oberfläche

`audioscribe ui` startet eine schlanke lokale Oberfläche (nur `localhost`, kein Upload).
Alle Läufe laufen **im Server weiter**, der Browser-Tab darf geschlossen werden; beendet
wird mit „Abbrechen“ oder Strg+C im Terminal.

```bash
.venv/bin/audioscribe ui                      # http://127.0.0.1:8766
.venv/bin/audioscribe ui --port 9000 --no-browser
```

Die Oberfläche beginnt auf der **Startseite** mit vier Einstiegen; jede Karte hat unter
„Worum geht es?“ eine kurze Erklärung.

| Einstieg | Wofür | Was du danach siehst |
|---|---|---|
| **Neues Projekt** | Ein eigener Ordner für Meetings mit Souffleur – auf Wunsch mit LLM-Wiki | Assistent in vier Schritten mit Strukturvorschau, dann der Arbeitsbereich des Projekts |
| **Projekt öffnen** | Ein vorhandenes Projekt weiterführen | Liste „Zuletzt geöffnet“ oder Wahl des Projektordners |
| **Aufnahme transkribieren** | Eine einzelne Audio- oder Videodatei in Text umwandeln, ohne Projekt | Nur die Transkription, dazu die KI-Analyse als nächster Schritt |
| **Demo abspielen** | Vorführung mit Beispiel-Meeting und Beispiel-Wiki | Live-Ansicht mit Zeitstrahl der bisherigen Meetings und einem Knopf „Demo starten“ |

Der Kopf zeigt, wo du bist (Projektname, „Aufnahme transkribieren“ oder „Demo“); der Knopf
daneben führt zurück zur Startseite. Läuft noch eine Sitzung, Transkription oder Analyse,
bleibt der Wechsel gesperrt, bis sie beendet ist. Der Server merkt sich, was geöffnet ist:
Ein Neuladen der Seite ändert nichts, nach einem Neustart von AudioScribe beginnst du wieder
auf der Startseite.

**Neues Projekt** – der Assistent führt in vier Schritten durch; eine Strukturvorschau
unter den Schritten zeigt jederzeit, welche Ordner am Ende entstehen:

1. **Projekt:** Projektname, Speicherort und Name des Projektordners (vorbelegt aus dem
   Namen). AudioScribe legt den Projektordner an; darin liegen die Projekteinstellungen
   (`.audioscribe/`), die Sitzungen und auf Wunsch das Wiki – das Projekt zieht mit seinem
   Ordner um.
2. **Wiki (optional):** **Ohne Wiki** (Transkription, Essenz und erkannte Fragen des
   Souffleurs, aber keine Belege und keine Ablage ins Wiki), **neues Wiki im Projektordner**
   (`llm-wiki/` mit dem Gerüst aus `raw/`, `wiki/`, Startseiten und Glossar) oder
   **vorhandenes Wiki verknüpfen** (es bleibt, wo es ist, und wird sofort geprüft: Name,
   Seiten, Glossar).
3. **Sitzungen:** der **Ordner für Sitzungen** (Mitschnitte, Transkripte, Standbilder und
   KI-Analysen; Vorgabe `sitzungen/` im Projektordner – Mitschnitte sind groß, eine andere
   Platte geht auch). Mit Wiki dazu, was nach einer Sitzung geschehen soll: nachfragen,
   immer ins Wiki speichern oder nicht anbieten. Unter „Weitere Optionen“ eingeklappt:
   Bilder und Markierungen mit übertragen und der **Ordner für Bilder im Wiki** (Assets;
   vorgeschlagen `raw/assets`).
4. **KI und Sprache:** Vorgabe sind die globalen Einstellungen; hier legst du nur fest, was
   für dieses Projekt anders sein soll.

Ein Wiki lässt sich jederzeit im Bereich „Projekt“ nachrüsten, gegen ein anderes tauschen
oder wieder lösen – Dateien werden dabei nie gelöscht.

**Im Projekt** gibt es drei Bereiche:

- **Live-Sitzung** – Mitschnitt mit Transkript, Screenshots und Souffleur, siehe
  [Live-Transkription](#live-transkription-windows-und-macos) und
  [Souffleur](#souffleur-live-abgleich-mit-dem-wiki). Nach dem Stopp erscheint die Karte
  **„Wie geht es weiter?“**: „Ins Wiki speichern“ und/oder „Mit KI nachbereiten“.
- **Nachbereitung** – alle Sitzungen des Projekts mit Marken (*im Wiki*, *nachbereitet*,
  *unterbrochen*). Je Sitzung: ins Wiki speichern, Transkript ansehen, die
  [KI-Analyse](#ki-analyse-per-claude-agent) starten und deren Ergebnis ebenfalls ins Wiki
  legen.
- **Projekt** – Name, Projektordner, Wiki (anlegen, verknüpfen, lösen), Ordner, Wiki-Ablage
  sowie KI und Sprache dieses Projekts.

**Aufnahme transkribieren** – „Dateien wählen“ öffnet einen Dialog, der die Audio- und
Videodateien eines Ordners zeigt; weitere Dateien desselben Ordners lassen sich danach
ankreuzen. Dann Speicherort und Optionen (Modell, Sprache, Gerät, Sprecher-Trennung,
Bildwechsel-Erkennung). Je Datei ein Fortschrittsbalken, dazu Gesamtbalken und **Restzeit**
(geschätzt aus den bereits fertigen Dateien, erscheint also ab der zweiten). Schlägt eine
Datei fehl, läuft der Rest weiter; das Protokoll klappt dann von selbst auf. Je fertiger
Aufnahme – auch einer früher schon transkribierten – erscheint eine Ergebniskarte mit dem
Speicherort, „Transkript ansehen“ und „Ordner öffnen“. Darunter führt **„Mit KI
weiterverarbeiten“** in die KI-Analyse; die Aufnahme ist dort schon als Quelle gewählt.

**Demo abspielen** – spielt das Beispiel-Meeting aus `demo/llm-wiki` ab, als liefe es
gerade; der Souffleur gleicht es mit dem Demo-Wiki ab. Der Fall ist frei erfunden (Firma,
Personen, Regeln und Zahlen); die Demo sagt das mit einem Banner über der Ansicht. Ein Zeitstrahl zeigt die Meetings, die
schon im Wiki stehen, und das heutige; jeder Hinweis nennt das Meeting, aus dem sein Beleg
stammt. Das Abspielen lässt sich mit „Pause“ anhalten und fortsetzen. Es wird nichts
aufgenommen und nichts ins Wiki geschrieben (die Demo-Sitzung liegt nur unter
`~/.cache/audioscribe/demo`).

**Einstellungen** gibt es auf zwei Ebenen:

- **Global** (Zahnrad oben rechts): KI-Dienst, Modell für den Souffleur, Modell für die
  KI-Analyse und Sprache der Aufnahmen. Sie gelten für alle Projekte, die nichts Eigenes
  festlegen, und für „Aufnahme transkribieren“. Die Karte **Umgebung** zeigt die Prüfzeilen
  von `audioscribe doctor` (ffmpeg, Gerät, WhisperX, HF-Token, Live-Geräte) direkt in der
  Seite.
- **Je Projekt** (Bereich „Projekt“): Jeder dieser Werte lässt sich überschreiben oder
  wieder auf „Globale Einstellung“ stellen.

Änderungen gelten sofort. Globale Einstellungen und die Liste der zuletzt geöffneten Projekte
liegen auf dem Rechner (Windows `%APPDATA%\audioscribe\einstellungen.json`, macOS
`~/Library/Application Support/audioscribe/`), die Projekteinstellungen im Projektordner
(`.audioscribe/projekt.json`).
Pfade aus dem Explorer (`C:\Users\…`) lassen sich überall direkt einfügen; „Wählen“ öffnet
einen Ordner-Browser mit Schnellzielen (Laufwerke, Home, Desktop, Downloads, Videos).

Die Ansichten sind per Adresse erreichbar (`#/`, `#/projekt/live`,
`#/projekt/nachbereitung`, `#/projekt/einstellungen`, `#/datei`, `#/datei/ki`, `#/demo`,
`#/einstellungen`); passt eine Adresse nicht zu dem, was gerade geöffnet ist, landest du auf
der passenden Startansicht. Der Knopf oben rechts schaltet das Design (System / Hell /
Dunkel).

**Unter WSL** die Adresse im Windows-Browser öffnen; WSL2 leitet `127.0.0.1` durch. Pfade
werden in beide Richtungen umgesetzt (`C:\Users\…` ↔ `/mnt/c/Users/…`). Medien auf dem
WSL-Dateisystem werden spürbar schneller gelesen als unter `/mnt/c`.

---

## Projekte und Ablage ins Wiki

Ein Projekt ist ein **eigener Ordner**, den du beim Anlegen wählst. Darin liegen die
Projekteinstellungen und – als Vorgabe – die Sitzungen; das Projekt zieht mit seinem Ordner
um (anderer Rechner, Git). Dazu kann das Projekt **ein LLM-Wiki** haben – einen
Markdown-Ordner mit `wiki/` (die Seiten) und `raw/` (die Rohquellen) – entweder neu angelegt
im Projektordner oder als vorhandenes Wiki verknüpft, wo immer es liegt. Die Seiten unter
`wiki/` verändert AudioScribe nie. Ohne Wiki arbeitet der Souffleur ohne Belege, und es gibt
keine Ablage ins Wiki.

```
bahnbuchung/                        # Projektordner (vom Nutzer gewählt)
  .audioscribe/projekt.json         # Projekteinstellungen (Pfade relativ, wo möglich)
  sitzungen/                        # Ordner für Sitzungen (Vorgabe; änderbar)
    live-2026-10-06_14-30-05/       # Mitschnitt, Transkript, frames/, Begleitdateien
    analysen/<prozessname>/         # Ergebnisse der KI-Analyse
  llm-wiki/                         # nur bei „Neues Wiki anlegen“ – sonst wiki_dir = <vorhandenes Wiki>
    wiki/                           # Wiki-Seiten – werden nur gelesen (Souffleur)
    raw/                            # Rohquellen – hier legt AudioScribe Sitzungen ab
      2026-10-06_workshop-reisebuchung/
        transkript.md               # Wortlaut unverändert (byte-gleiche Kopie)
        transcript.json             # dasselbe maschinenlesbar
        transkript.annotiert.md     # mit Bildern an der passenden Stelle (nur mit Bildern)
        marks.json                  # Zeitstempel → Bild (nur mit Bildern)
        markierungen.json / .md     # Markierungen des Souffleurs (nur auf Wunsch)
        README.md
        nachbereitung-ki/<analyse>/ # optional: Dokumente der KI-Analyse, als KI-erzeugt gekennzeichnet
      assets/                       # Assets-Ordner (Vorschlag) für die Bilder
        2026-10-06_workshop-reisebuchung/0001_00-01-23.jpg …
```

**Projekte aus früheren Versionen** (Projektdatei im Wiki-Ordner, `<wiki>/.audioscribe/`)
öffnen sich unverändert: Dort ist der Wiki-Ordner zugleich der Projektordner. Bei der ersten
Änderung wird die Projektdatei auf das neue Format gehoben; Dateien werden nicht bewegt.

**Ins Wiki speichern** (Karte „Wie geht es weiter?“ nach der Sitzung oder Bereich
„Nachbereitung“): Du vergibst einen Titel – daraus und aus dem Datum entsteht der
Ordnername – und entscheidest, ob die Bilder und die Markierungen des Souffleurs mitgehen.
Die Markierungen sind KI-erzeugt und zitieren das Wiki; unter `raw/` könnte der Ingest sie
als Quelle lesen. Deshalb ist der Haken standardmäßig aus, und sie bleiben im Sitzungsordner.
Mit Bildern werden die Standbilder
in den Assets-Ordner kopiert, und `transkript.annotiert.md` verweist an derselben Stelle
auf jedes Bild wie im Sitzungsordner (`![Bild #0001 – 00:01:23](../assets/…/0001_00-01-23.jpg)`).
„Künftig immer so speichern“ stellt das Projekt auf **immer** und merkt sich beide Haken:
Jede beendete Sitzung geht dann nach dem Nachschärfen ohne Nachfrage ins Wiki (änderbar im
Bereich „Projekt“).

**Nachbereitung ins Wiki:** Das Ergebnis einer fertigen KI-Analyse lässt sich unter
`nachbereitung-ki/` zur Sitzung legen. Die Dokumente sind dort als **KI-erzeugt** und nicht
als Quelle gekennzeichnet; Bildverweise zeigen auf die Bilder im Assets-Ordner. Liegt die
Sitzung noch nicht im Wiki, wird sie dabei zuerst gespeichert.

Die Ablage ist **rein anhängend**: Es wird nichts überschrieben (ein zweites Speichern
hängt `-2` an), geschrieben wird nur nach `raw/` und in den Assets-Ordner, und nur, wenn du
es auslöst oder „immer“ gewählt hast. Was aus einer Quelle im Wiki wird, entscheidet dessen
eigener Ingest- bzw. Lint-Prozess. Die KI-Analyse arbeitet weiter auf dem Sitzungsordner,
nicht auf der Kopie im Wiki.

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
16-kHz-Mono-WAV nach `work/` extrahiert und nach dem Laden wieder gelöscht. Unterstützt:
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
aus. Das Transkript ist zu diesem Zeitpunkt schon geschrieben; bricht die Erkennung ab,
bleibt es erhalten. Ein erneuter Lauf ersetzt die automatischen Bilder und lässt von Hand gesetzte
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

**In der Oberfläche:** im Projekt der Bereich „Nachbereitung“ (Sitzung wählen), bei
„Aufnahme transkribieren“ die Lasche „KI-Analyse“ (fertige Transkription wählen). Dann
Prozessname und Kontext eingeben, Skills ankreuzen. Im Projekt landen die Ergebnisse unter
`<Sitzungsordner>/analysen/<prozessname>/`, ohne Projekt im Ausgabeordner, den die Karte
„Optionen“ zeigt. Das vorgewählte Modell kommt aus den Einstellungen. Der Fortschritt zeigt
den Plan des Agenten als Schrittliste, den aktiven Skill, angesehene Standbilder und
geschriebene Dokumente. Einen Prozentwert gibt es bewusst nicht; ergänzt der Agent Schritte,
läuft der Balken auch zurück. Im Projekt lässt sich das fertige Ergebnis mit
„Nachbereitung ins Wiki speichern“ zur Sitzung ins Wiki legen
(siehe [Projekte](#projekte-und-ablage-ins-wiki)).

**Abrechnung:** Die Anbindung läuft über das
[Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk) und nutzt die Anmeldung von
Claude Code. Mit Pro-/Max-Abo braucht es keinen API-Key und es fallen keine zusätzlichen
Kosten an. **Achtung:** Ein gesetzter `ANTHROPIC_API_KEY` hat Vorrang und rechnet über
das API-Guthaben ab; `audioscribe doctor` zeigt, welcher Weg aktiv ist. Jedes angesehene
Standbild kostet Tokens; bei Hunderten Bildern helfen `--frame-sensitivity grob` oder ein
größerer `--frame-min-gap`. Mit dem KI-Dienst „Lokal (Ollama)“ läuft derselbe Agent
experimentell über ein lokales Modell, siehe [Lokale KI](#lokale-ki-ollama).

**KI-Verbrauch:** Sobald eine KI außer Haus gearbeitet hat (Souffleur, KI-Analyse), steht
oben rechts neben dem Zahnrad der Verbrauch seit Programmstart: Tokens und ungefährer Preis
in US-Dollar. Ein Klick zeigt die Aufteilung nach Souffleur-Sitzung und Analyse-Lauf. Der
Preis („≈“) ist der Gegenwert zu API-Preisen, den der KI-Dienst selbst meldet – mit Abo ist
das keine Rechnung. Lokale Arbeit (Transkription, Sprechertrennung) zählt nicht. Im Terminal
nennt `audioscribe analyze` den Verbrauch in der Zeile `[Verbrauch]`.

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
  analyse.json              # Protokoll: Skills, Modell, Session-ID, Dauer, tokens, kosten_usd (nur Gegenwert)
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
.\start.ps1                                                  # Oberfläche: Projekt öffnen › „Live-Sitzung“
.venv-win\Scripts\audioscribe.exe doctor                     # Zeile „Live“: Mikrofone, Loopback, Monitore
.venv-win\Scripts\audioscribe.exe live --list-devices        # ohne Oberfläche: Geräte, Monitore, Fenster (HWND)
.venv-win\Scripts\audioscribe.exe live --monitor 1 --mic 23  # Ende mit Strg+C oder "stop" + Enter
.venv-win\Scripts\audioscribe.exe live --window 592902       # nur dieses Fenster
.venv-win\Scripts\audioscribe.exe live --monitor 1 --loopback none   # ohne System-Audio (sonst Standardgerät oder Geräteindex)
#   während der Aufnahme eintippen: "bild monitor 2", "bild fenster 592902" oder "bild aus" + Enter
.venv-win\Scripts\audioscribe.exe refine output\live-2026-09-19_14-30-05 --model large-v3-turbo
```

```bash
./start.sh                                                   # macOS: Oberfläche, Projekt öffnen › „Live-Sitzung“
.venv-mac/bin/audioscribe live --list-devices                # Mikrofone, „System-Audio (ScreenCaptureKit)“, Monitore, Fenster
.venv-mac/bin/audioscribe live --monitor 1                   # Ende mit Strg+C oder "stop" + Enter
.venv-mac/bin/audioscribe refine output/live-2026-09-19_14-30-05
```

**In der Oberfläche** (Projekt › „Live-Sitzung“): optional einen **Sitzungstitel** vergeben
(er benennt später den Ordner im Wiki), Bildquelle wählen (Monitor mit Vorschaubild,
Anwendungsfenster oder „nur Ton“), Mikrofon und System-Audio wählen, „Aufnahme starten“.
Die Bildquelle lässt sich **während der Aufnahme wechseln**: einfach eine andere Kachel
anklicken – das erste Bild der neuen Quelle wird gesichert, die Bildnummern laufen weiter,
der Ton läuft ungestört durch. Oben laufen Laufzeit, **Verzögerung** (Ende des Gesprochenen bis zur Anzeige) und
**Rückstand** mit. Rückstand ist fertig gesprochenes Audio, das auf die Transkription
*wartet*; der Abschnitt, der gerade gerechnet wird, zählt nicht mit. Screenshots erscheinen
rechts als Thumbnails. Gespeichert wird im Ordner für Sitzungen des Projekts (auf der
Kommandozeile unter `--output`, Default `output/`):

```
<Sitzungsordner>/live-2026-09-19_14-30-05/
  transkript.md  transcript.json  transkript.annotiert.md  marks.json  frames/
  transkript.txt                                  # reiner Text ohne Zeitstempel/Sprecher (WER-Vergleich)
  transkript.live.md  transcript.live.json  transkript.live.txt   # Live-Fassung (nach dem Stopp)
  audio/mikrofon.wav  audio/system.wav            # 16 kHz mono
  bilanz.json                                     # Fazit: Rechendauer und Latenz (live + nachschaerfen)
  diagnose.jsonl                                  # je Abschnitt und Vorschau eine Zeile (Zeiten, Qualitaet)
  sitzung.json  sitzung.journal.jsonl  sitzung.lock  sprecher.json   # Absturzsicherung (siehe unten)
```

Nach dem Stopp zeigt die Karte **„Wie geht es weiter?“** die beiden nächsten Schritte: „Ins
Wiki speichern“ und „Mit KI nachbereiten“ (siehe [Projekte](#projekte-und-ablage-ins-wiki)).

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
auf Stoppen bricht hart ab. Danach zeigt die Ansicht ein **Fazit**: Aufnahmedauer, Ladezeit,
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

## Absturzsicherung und Wiederaufnahme

Eine Live-Sitzung wird laufend gesichert. Stürzt AudioScribe ab, fällt der Strom aus oder
wird das Serverfenster geschlossen, geht höchstens verloren, was in diesem Moment noch nicht
transkribiert war – und auch das steht noch im Mitschnitt.

Beim nächsten Start zeigt die Startseite ein Banner **„Unterbrochene Sitzung …“**; ein Klick
öffnet das Projekt. In der Live-Ansicht stehen dann drei Wege zur Wahl:

| Weg | Was geschieht |
|---|---|
| **Fortsetzen** | Das bisherige Transkript, die Standbilder und die Hinweise des Souffleurs erscheinen sofort wieder; die Aufnahme läuft mit den links gewählten Geräten im selben Sitzungsordner weiter. Zeitstempel, Abschnitts- und Bildnummern zählen fort. |
| **Abschließen** | Keine weitere Aufnahme: Aus dem Gesicherten entsteht das Transkript, danach läuft – wenn eingeschaltet – das Nachschärfen über den Mitschnitt. Anschließend wie nach jeder Sitzung: ins Wiki speichern, nachbereiten. |
| **Verwerfen** | Die Sitzung wird nicht mehr angeboten. Mitschnitt und bisheriges Transkript bleiben im Sitzungsordner liegen. |

Eine Aufnahme startet nie von selbst – auch „Fortsetzen“ ist ein bewusster Klick. Verliert
nur der Browser die Verbindung (AudioScribe wurde beendet), zeigt die Seite einen Hinweis
und verbindet sich von selbst wieder.

```powershell
.venv-win\Scripts\audioscribe.exe live --resume output\live-2026-10-06_09-00-00 --mic 23   # fortsetzen
.venv-win\Scripts\audioscribe.exe live --finalize output\live-2026-10-06_09-00-00          # ohne Aufnahme abschließen
.venv-win\Scripts\audioscribe.exe live --monitor 1 --titel "Workshop Reisebuchung"          # Sitzungstitel setzen
```

<details>
<summary>Was gesichert wird und wo die Grenzen liegen</summary>

Im Sitzungsordner liegen dafür `sitzung.json` (Zustand `laeuft`, `unterbrochen`, `beendet`
oder `verworfen`, Titel, Sprache, Modell, Aufnahme-Teile), `sitzung.journal.jsonl` (jeder
fertige Abschnitt sofort, jedes Standbild, alle paar Sekunden die Sitzungszeit),
`sitzung.lock` (zeigt, ob der Aufnahmeprozess noch lebt) und `sprecher.json` (Stimmprofile,
damit „Sprecher 1/2“ nach dem Fortsetzen dieselben bleiben). Der Mitschnitt wird fortlaufend
geschrieben und ist auch nach einem Absturz lesbar. Beim Fortsetzen entstehen neue
Teil-Dateien (`audio/mikrofon.teil2.wav` …); eine vorhandene Aufnahme wird nie überschrieben.
Nach dem sauberen Ende werden die Teile je Spur wieder zu einer WAV zusammengesetzt.

Grenzen: Was beim Absturz gesprochen, aber noch nicht transkribiert war, fehlt im
Live-Transkript; das Nachschärfen holt es aus dem Mitschnitt nach. Aussagen, die der
Souffleur noch nicht beurteilt hatte, werden nicht nachträglich beurteilt. Ein abgespieltes
Transkript (Demo, Testmodus) wird nicht fortgesetzt. `--resume` und `--finalize` lehnen
Sitzungen ab, die schon beendet oder verworfen sind oder noch in einem anderen Prozess
laufen.
</details>

---

## Souffleur: Live-Abgleich mit dem Wiki

Der Souffleur hört während einer Live-Sitzung über das Transkript mit, gleicht das Gesagte
mit dem **LLM-Wiki des Projekts** (Markdown-Ordner, nur lesend) ab und zeigt **nur dem
Moderator** Hinweise in der rechten Spalte der Live-Ansicht:

| Hinweis | Was er bedeutet |
|---|---|
| **Widerspruch** (rot, Blitz) | Eine Aussage weicht klar von einer Wiki-Stelle ab. Beide Seiten stehen nebeneinander: *gesagt* und *im Wiki* (Datei › Überschrift, wörtliches Zitat). Wer recht hat, entscheidet der Souffleur nicht. |
| **Frage** (blau, Fragezeichen) | Eine echte Frage wurde gestellt. Steht im Wiki etwas dazu, kommt der Antwortvorschlag mit Fundstelle; sonst „Im Wiki liegt dazu nichts vor“ und die Frage zählt als offener Punkt. |
| **Offener Punkt** (gelb, gestrichelt) | Etwas wurde als ungeklärt benannt oder fehlt im Wiki. Die Liste offener Punkte steht unten in der Karte und bleibt nach dem Meeting erhalten. |
| **Essenz 2 / 5 min** | Auf Knopfdruck fasst die KI genau das gewählte Zeitfenster zusammen. Als **KI** gekennzeichnet, nicht Teil der Quelle fürs Wiki. |

Belegtes und KI-Erzeugtes bleiben sichtbar getrennt: Wiki-Zitate tragen eine Fundstelle,
alles, was die KI selbst formuliert, ist mit „KI“ markiert (gestrichelter Rahmen). Der
Wortlaut des Transkripts wird nie verändert; Markierungen liegen als Begleitdateien daneben.
Die Wiki-Seiten werden ausschließlich gelesen.

**1. Wiki verknüpfen:** Das Wiki gehört zum **Projekt** – du gibst es beim Anlegen an
(siehe [Browser-Oberfläche](#browser-oberfläche)). Im Bereich „Projekt“ steht das
Prüfergebnis: *verbunden* (Name, Seiten, Glossar-Einträge, Lesezeitpunkt) oder *nicht
erreichbar* mit Grund. Änderungen am Wiki gelten ab der nächsten Sitzung. Erwartet wird ein
Markdown-Ordner im Karpathy-Muster (`wiki/` mit den Seiten, `raw/` mit Quellen); ohne
`wiki/` werden alle `*.md` unter dem Pfad gelesen. Ein Glossar bestätigter Fehlerkennungen
(Datei `glossar.md` oder eine Seite mit „Glossar“ in der Überschrift, Tabelle
`Fehlerkennung | Korrekt | Kontext`) nutzt der Souffleur automatisch, damit verstümmelte
Fachbegriffe keine falschen Widersprüche auslösen. KI-Dienst und **Modell für den
Souffleur** stehen in den Einstellungen (global, je Projekt überschreibbar).

**2. Souffleur starten:** In der Live-Ansicht läuft er automatisch mit jeder Sitzung
(Schalter in der Souffleur-Karte; „Ausblenden“ oder Alt+S klappt die Spalte samt
Markierungen weg, etwa beim Bildschirmteilen). Die Statuszeile zeigt, mit welchem Wiki
abgeglichen wird. Ohne lesbares Wiki oder ohne KI-Dienst läuft die Transkription normal
weiter; der Souffleur meldet seinen Zustand („ohne Wiki – nur Fragen und Essenz“, „KI nicht
verfügbar“).

**3. Transkript abspielen (Testmodus, ohne Audio):** In der Live-Ansicht die Kachel
*Transkript abspielen* wählen, eine gespeicherte `transcript.json`, ein `transkript.md` oder
einen ganzen Sitzungsordner angeben, Tempo 1× bis 20× wählen, *Abspielen starten*. Die
Absätze erscheinen zu ihren Zeitstempeln, als kämen sie live; Souffleur, Sitzungsordner und
Fazit verhalten sich wie im Betrieb. Auf der Kommandozeile:

```bash
.venv-win\Scripts\audioscribe.exe live --transcript output\meeting\transcript.json --speed 5
.venv-win\Scripts\audioscribe.exe live --transcript output\live-2026-10-06_09-00-00 --replay-delay 2
.venv-win\Scripts\audioscribe.exe live --transcript output\meeting\transkript.md --raffen   # ohne Gesprächspausen (so läuft die Demo)
```

**4. Ergebnis ablesen:** Je Sitzung entstehen Begleitdateien neben dem Transkript:
`souffleur.json` (Markierungen mit Zeitbezug, Fundstellen, KI-Feldern, Bilanz),
`souffleur-protokoll.md` (Abnahmetabelle: Zeitstempel, Art, Aussage, Fundstelle, Wiki-Zitat,
KI-Text, Verzögerung „Hinweis nach“ inklusive Anteil des KI-Prozessstarts, reale
Verzögerung), `souffleur-diagnose.jsonl` (je Fenster: Treffer, Suchzeit, KI-Zeiten,
verworfene Befunde), `souffleur-essenz.jsonl` (Essenzen, KI-erzeugt). Ins Wiki gelangen
die Markierungen nur auf Wunsch: mit dem Haken „Markierungen des Souffleurs mit übertragen“
in **„Ins Wiki speichern“** (`markierungen.json`, `markierungen.md` in der Quelle unter
`raw/`, siehe [Projekte](#projekte-und-ablage-ins-wiki)). Ohne Haken bleiben sie hier. Die Essenzen gehen nicht mit – sie sind
KI-erzeugt und keine Quelle. Einen eigenen Übergabeordner gibt es nicht mehr.

<details>
<summary>Wie der Abgleich arbeitet, KI-Dienst, Verzögerung</summary>

Segmente werden zu Fenstern gebündelt (bis 20 s Sprechzeit, 4 Segmente oder 5 s Pause).
Je Fenster sucht der Souffleur lokal im Wiki (lexikalisch über Abschnitte, Glossar
korrigiert den Suchtext) und ruft die KI **einmal** mit Fenster, Kontext der letzten
Minute, den gefundenen Auszügen und dem Glossar. Die Antwort wird lokal geprüft: Die
Aussage muss wörtlich im Segment stehen, das Zitat wörtlich im gelieferten Auszug, ein
Widerspruch ohne Zitat wird verworfen, Dubletten werden unterdrückt, unsichere Befunde
nur mit Einstellung `souffleur_sensibel`. Erst dann wird markiert.

**KI-Dienst:** austauschbar; in den Einstellungen stehen „Claude (Agent SDK)“, das die
Anmeldung von Claude Code nutzt, und „Lokal (Ollama auf diesem Rechner)“, siehe
[Lokale KI](#lokale-ki-ollama). `AUDIOSCRIBE_SOUFFLEUR_BACKEND=attrappe` schaltet für Tests
auf einen regelbasierten Ersatz ohne Netz. Dienst und Modell stehen in den Einstellungen
(global, je Projekt überschreibbar); in der Souffleur-Karte selbst heißt es nur „KI“. Bei
Claude läuft jeder Aufruf ohne Werkzeuge in einem leeren Arbeitsordner unter
`~/.cache/audioscribe/souffleur`, Sitzungsdateien des KI-Prozesses werden abgeschaltet bzw.
gelöscht: keine Transkript- oder Wiki-Auszüge bleiben außerhalb des Sitzungsordners liegen.
Beim lokalen Dienst geht je Fenster ein Chat-Aufruf mit Schema-Zwang an Ollama; nichts verlässt
den Rechner, und der Verbrauchszähler bleibt bei null.

**Verzögerung:** Je Hinweis wird gemessen (Sitzungsuhr): Sprachende → Hinweis, mit den
Anteilen Spracherkennung, Warten im Fenster, Wiki-Suche, **Prozessstart der KI** und
KI-Antwort; dazu die reale Verzögerung ab Empfang des Segments. Mittel, Median und Maximum
stehen in `souffleur.json` und im Protokoll. Beim Abspielen mit Tempo > 1 sind die
Sitzungswerte gestreckt, die reale Spalte bleibt vergleichbar. Einen festen Grenzwert gibt
es noch nicht; als Richtwert gilt: unter 15 s ist ein Hinweis noch im Raum.

**Einstellungen** der Installation liegen im Konfigurationsordner der Plattform
(Windows `%APPDATA%\audioscribe\einstellungen.json`, macOS
`~/Library/Application Support/audioscribe/`); eine ältere `ui-state.json` aus
`~/.cache/audioscribe` wird beim ersten Start übernommen. `audioscribe doctor` zeigt die
Zeile „Souffleur“ mit dem Wiki-Zustand der zuletzt geöffneten Projekte, dem KI-Dienst und
dem Pfad der Einstellungsdatei. `AUDIOSCRIBE_WIKI_DIR` wirkt nur noch, solange kein Projekt
geöffnet ist (Tests, direkte Aufrufe der Server-Schnittstelle), und belegt den Assistenten
„Neues Projekt“ vor.
</details>

---

## Lokale KI (Ollama)

Statt Claude kann ein **lokales Sprachmodell** über [Ollama](https://ollama.com) arbeiten.
Ollama läuft als eigener Dienst auf dem Rechner (auf Apple Silicon mit Apples MLX),
audioscribe spricht ihn über `localhost:11434` an. Es ist die einzige Komponente außerhalb
von `uv`; audioscribe selbst braucht dafür kein weiteres Paket.

```bash
brew install ollama                                   # oder das Paket von ollama.com
OLLAMA_CONTEXT_LENGTH=65536 ollama serve              # Dienst starten (Kontext für die KI-Analyse)
ollama pull qwen3.6:35b-a3b-nvfp4                     # Modell laden (~24 GB, einmalig)
./start.sh --doctor                                   # Zeile „KI lokal“: Dienst, Version, Modelle
```

Dann in der Oberfläche **Einstellungen → KI-Dienst → „Lokal (Ollama auf diesem Rechner)“**
wählen – global oder nur für ein Projekt. Die Modell-Listen wechseln mit dem Dienst; beim
Umschalten wird jeweils das erste passende Modell eingetragen. Vorschläge für 48 GB RAM:

| Modell | Größe | Hinweis |
|---|---|---|
| `qwen3.6:35b-a3b-nvfp4` | ~24 GB | Vorgabe: Mixture-of-Experts, 3 B aktiv, schnell, MLX |
| `gemma4:26b-mlx` | ~18 GB | ebenfalls schnell, stark in Deutsch, MLX |
| `qwen3.6:27b-mlx` | ~19 GB | dichtes Modell, beste Qualität, spürbar langsamer |
| `qwen3.6:35b-a3b` | ~24 GB | GGUF-Rückfall über llama.cpp, falls der MLX-Pfad hakt |

**Souffleur:** produktiv nutzbar. Je Fenster geht ein Chat-Aufruf mit JSON-Schema an Ollama
(`format`, Denken aus, Temperatur 0); die Antwort wird wie bei Claude lokal geprüft. Läuft
der Dienst nicht oder fehlt das Modell, sagt die Souffleur-Karte, was zu tun ist, und die
Sitzung läuft ohne KI weiter. Nach dem letzten Aufruf bleibt das Modell
`AUDIOSCRIBE_OLLAMA_KEEP_ALIVE` (Vorgabe 30 min) im Speicher; danach dauert der erste
Aufruf wieder einige Sekunden.

**KI-Analyse (experimentell):** Claude Code wird über die Anthropic-kompatible Schnittstelle
von Ollama auf das lokale Modell umgeleitet (`ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`);
Werkzeuge, Skills und Leitplanken bleiben gleich. Auf der Kommandozeile:
`audioscribe analyze … --ki-dienst ollama --model qwen3.6:35b-a3b-nvfp4`. Erwartungen
dämpfen: Werkzeugaufrufe lokaler Modelle sind weniger zuverlässig, ein zweistündiges
Transkript dauert lange, Standbilder kann je nach Build nicht jedes Modell lesen (der Agent
wird angewiesen, dann ohne Bilder weiterzuarbeiten), und Claude Code braucht beim Dienst
mindestens 32k Kontext (`OLLAMA_CONTEXT_LENGTH`). Das Protokoll beginnt mit einer
`[experimentell]`-Zeile.

**Verbrauch und Datenschutz:** Lokale Aufrufe zählen nicht (die Anzeige oben rechts bleibt
bei null, im Protokoll steht „lokal, zählt nicht“). Transkript- und Wiki-Auszüge gehen nur
an den Dienst auf demselben Rechner. Ein gesetzter `ANTHROPIC_API_KEY` spielt lokal keine
Rolle. Adresse und Verweildauer: `AUDIOSCRIBE_OLLAMA_URL`, `AUDIOSCRIBE_OLLAMA_KEEP_ALIVE`.

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

# Oberfläche (Startseite: Neues Projekt | Projekt öffnen | Aufnahme transkribieren | Demo)
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
.venv/bin/audioscribe analyze output/demo --name "Rechnungsprüfung" --out ~/Analysen \
    --ki-dienst ollama --model qwen3.6:35b-a3b-nvfp4         # lokales Modell (experimentell)
.venv/bin/audioscribe prozessbild ~/Analysen/rechnungspruefung          # Prozessbild neu rendern
.venv/bin/audioscribe bpmn ~/Analysen/rechnungspruefung [--pruefen|--neu]

# Live (Windows)
.venv-win\Scripts\audioscribe.exe live --transcript output\meeting\transcript.json --speed 5   # Souffleur-Testmodus ohne Audio
.venv-win\Scripts\audioscribe.exe live --list-devices
.venv-win\Scripts\audioscribe.exe live --monitor 1 --mic 23 --titel "Workshop Reisebuchung"
.venv-win\Scripts\audioscribe.exe live --resume output\live-… --mic 23     # unterbrochene Sitzung fortsetzen
.venv-win\Scripts\audioscribe.exe live --finalize output\live-…            # unterbrochene Sitzung ohne Aufnahme abschließen
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

Basisstufe gemäß `PRD.md`: eine Datei pro CLI-Aufruf (die Oberfläche arbeitet mehrere
gewählte Dateien nacheinander ab), Markdown-Ausgabe mit optionalem PDF, Sprecher als
„Sprecher N“ ohne Personen-Identifikation. AudioScribe ist die Transkriptions-Basis für die
übergeordnete Meeting-Protokoll-Pipeline; die Auswertung übernimmt optional der
Claude-Agent. Alle Anforderungen und Designentscheidungen stehen nummeriert (FR-1 … FR-78)
in `PRD.md`. Offen ist jeweils die Abnahme auf dem Gerät: die macOS-Portierung (PRD §19,
Akzeptanzkriterien §19.5) sowie echte Aufnahme- und Absturztests der Projekte und der
Wiederaufnahme (PRD §21.5).
