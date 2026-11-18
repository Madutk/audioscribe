# AudioScribe – Techstack und Funktionsumfang

Stand: 2026-11-11, Version 0.1.0 (Branch `main`, Commit `8ad4b64`).
Grundlage: Quellcode unter `src/audioscribe/`, `pyproject.toml`, `.env.example`, `README.md` und die Commit-Historie.

**In einem Satz:** AudioScribe transkribiert Meetings lokal mit Sprecher-Trennung – aus einer Datei oder live – sichert Bildschirminhalte als Standbilder, gleicht das Gesagte während des Meetings mit einem LLM-Wiki ab (Souffleur) und lässt einen KI-Agenten daraus Prozessdokumentation, Prozessbild und BPMN erzeugen.

---

## Was AudioScribe im Ganzen leistet

Über die Einzelfunktionen hinaus ergeben sich diese übergeordneten Fähigkeiten:

| Fähigkeit | Was das heißt |
|---|---|
| **Wissenskreislauf über Meetings hinweg** | Vorbereiten (Leitfaden mit Wiki-Bezug) → live begleiten (Souffleur) → ablegen (Rohquelle) → einarbeiten (Agent pflegt die Wiki-Seiten) → das nächste Meeting startet mit den offenen Punkten. Das Wiki wächst mit jedem Meeting, und jedes Meeting profitiert vom Wiki. |
| **Projektgedächtnis im Gespräch** | Der dokumentierte Stand ist im Meeting präsent: Widersprüche zu früheren Festlegungen und schon beantwortete Fragen fallen auf, solange alle noch im Raum sind – nicht erst beim Protokoll. |
| **Gesprächsführung nach Agenda** | Der Moderator sieht laufend, was geklärt, nur angesprochen oder noch offen ist, und wird ans Nachhaken erinnert. Am Ende steht fest, was vertagt wurde. |
| **Prozessaufnahme aus Vorführungen (Task Mining)** | Jemand zeigt seine Arbeit am Bildschirm und erklärt sie; daraus entstehen Prozessdokumentation, Prozessbild, BPMN-Modell und Arbeitsanweisung – ohne dass jemand mitschreibt. |
| **Ton und Bild als gemeinsame Quelle** | Gesagtes und Gezeigtes liegen zeitlich verknüpft vor. Eine KI kann beides zusammen auswerten; was nur auf dem Bildschirm stand, geht nicht verloren. |
| **Belegprinzip** | Quelle und KI-Erzeugtes bleiben getrennt. Hinweise brauchen wörtliche Zitate, die lokal geprüft werden; der Wortlaut des Transkripts wird nie verändert; KI-Texte sind gekennzeichnet und gelten nicht als Quelle. |
| **Mensch entscheidet** | Der Souffleur urteilt nicht, wer recht hat. Ins Wiki geht nur, was ausgelöst oder ausdrücklich auf „immer“ gestellt wurde; der Agent stellt Rückfragen, statt zu raten. |
| **Datensouveränität** | Transkription läuft immer lokal. Die KI ist wählbar (Cloud oder lokal), und eine eigene Variante schließt Cloud-KI technisch aus – für Umgebungen mit Compliance-Auflagen. |
| **Offene Formate, kein Lock-in** | Alles liegt als Markdown, JSON, WAV, JPG, Mermaid und BPMN 2.0 in normalen Ordnern. Projekte ziehen mit ihrem Ordner um, lassen sich mit Git versionieren und in anderen Werkzeugen weiterverarbeiten. |
| **Erweiterbar ohne Code** | Skills bestimmen, was die Analyse erzeugt und nach welchem Maßstab; das Wiki bringt eigene Regeln für die Einarbeitung mit; KI-Dienst und Modell sind austauschbar. |
| **Messbar und reproduzierbar** | Latenz, Rechenzeit und jede Filter-Entscheidung werden protokolliert. Replay von WAV und Transkript erlaubt Vergleiche von Modellen und Einstellungen ohne echtes Meeting. |
| **Ausfallsicher** | Ein Absturz kostet höchstens Sekunden; Sitzungen und Agenten-Aufträge lassen sich fortsetzen. |
| **Ein Werkzeug für mehrere Arbeitsweisen** | Datei oder live, Online-Call oder Vor-Ort-Runde, mit oder ohne Projekt, Oberfläche oder Kommandozeile, Windows, macOS oder Linux, Deutsch oder Englisch. |

---

## 1. Techstack

### 1.1 Überblick

| Schicht | Technik |
|---|---|
| Sprache, Laufzeit | Python 3.12 (gepinnt `>=3.12,<3.13`) |
| Paketverwaltung, Build | `uv` (Lockfile `uv.lock`, Extras je Plattform), Build-Backend `hatchling` |
| Spracherkennung (ASR) | WhisperX mit faster-whisper / CTranslate2 (`large-v3`); auf Apple Silicon `mlx-whisper` (Metal) |
| Wort-Alignment | wav2vec2 (über WhisperX) |
| Sprecher-Trennung | pyannote `speaker-diarization-3.1` + `segmentation-3.0`; live: Stimm-Embedding mit Online-Clustering |
| Sprachaktivität (VAD) | Silero-VAD (ONNX, aus faster-whisper) |
| ML-Framework | PyTorch / torchaudio 2.4–2.6 (CUDA 12.4, MPS oder CPU) |
| Medien | gebündeltes ffmpeg (`imageio-ffmpeg`), kein System-ffmpeg nötig |
| Audio-Aufnahme | Windows: WASAPI-Loopback (`PyAudioWPatch`); macOS: ScreenCaptureKit (System-Audio) + `sounddevice`/PortAudio (Mikrofon) |
| Bildschirm-Aufnahme | `mss`, Pillow, numpy, scipy; macOS zusätzlich Quartz / ScreenCaptureKit über PyObjC |
| Texterkennung (OCR) | macOS Vision (`VNRecognizeTextRequest`, Deutsch und Englisch), lokal |
| Webserver | FastAPI + uvicorn, nur `127.0.0.1` (Haupt-UI Port 8766, Review-UI Port 8765) |
| Frontend | HTML, CSS und JavaScript als ES-Module ohne Framework und ohne Build-Schritt |
| Cloud-KI | Claude Agent SDK (`claude-agent-sdk`), nutzt die Anmeldung von Claude Code (Abo, kein API-Key nötig) |
| Lokale KI | Ollama über HTTP (`localhost:11434`, nur Standardbibliothek `urllib`), JSON-Schema-Ausgabe |
| Diagramme | Mermaid (im Paket gebündelt, offline), gerendert über Edge/Chrome im Hintergrund; eigener BPMN-2.0-Generator mit Auto-Layout |
| PDF | `fpdf2` (reines Python) |
| Tests | pytest, 39 Testmodule (reine Logik, ohne Modell-Downloads) |
| Lint | ruff |

### 1.2 Plattformen und Rechen-Backends

| Plattform | ASR | Alignment / Diarisierung | Live-Aufnahme |
|---|---|---|---|
| Windows + NVIDIA-GPU | faster-whisper auf CUDA (`float16`) | PyTorch CUDA | ja (WASAPI) |
| Windows / Linux ohne GPU | faster-whisper auf CPU (`int8`) | PyTorch CPU | Windows ja, Linux/WSL nur WAV-Replay |
| macOS Apple Silicon | mlx-whisper (Metal) | PyTorch MPS | ja (ScreenCaptureKit) |
| WSL2 | wie Linux | wie Linux | nur WAV-Replay; Pfade Windows ↔ WSL werden umgesetzt |

Die Backend-Wahl fällt über uv-Extras: `cpu` oder `cu124` (schließen sich aus), dazu `review` (Oberflächen), `agent` (Claude), `live` (Aufnahme), `mac` (Apple Silicon).

---

## 2. Funktionen

### 2.1 Aufnahme transkribieren (offline)

- Audio- oder Videodatei → `transkript.md` mit Zeitstempeln und `Sprecher 1 / 2 / 3`; dazu `transcript.json` und optional PDF.
- Video-Formate: `mp4 mkv mov avi webm m4v wmv flv mpg mpeg ts m2ts 3gp ogv`; die Tonspur wird vorab als 16-kHz-Mono-WAV extrahiert.
- Sprecher-Trennung mit fester Zahl oder Spanne (`--num-speakers`, `--min-speakers`, `--max-speakers`), abschaltbar.
- Sprache fest (Standard Deutsch) oder automatisch erkannt.
- Zeitstempel alle N Sätze aus dem Wort-Alignment (Standard 2).
- Modelle laufen nacheinander, der VRAM wird zwischen den Stufen freigegeben (Ziel: 8 GB).
- In der Oberfläche: mehrere Dateien nacheinander, Fortschritt je Datei, Gesamtbalken und Restzeit; ein Fehler stoppt die übrigen Dateien nicht.

### 2.2 Bildwechsel-Erkennung

- Für Bildschirmaufnahmen: je Folien- oder Fensterwechsel ein Standbild, eingefügt an der passenden Stelle in `transkript.annotiert.md`.
- Mausbewegungen lösen nichts aus (Vergleich über ein Raster aus 16×9 Blöcken auf 192×108 Graustufen).
- Animationen und Scrollen ergeben ein Bild am Ende der Serie.
- Einstellbar: Empfindlichkeit (grob, mittel, fein), Format (JPG 1600, JPG 1280, PNG), Abtastrate, Mindestabstand.
- Jedes Bild hat eine ID („Bild #0001“), über die Transkript und Bilder gemeinsam einer KI vorgelegt werden können.

### 2.3 Bild-Annotation von Hand (Review-Oberfläche)

- Video scrubben, das Transkript läuft synchron mit; Klick auf eine Zeile springt im Video.
- „Frame markieren“ sichert ein framegenaues PNG mit justierbarem Lag-Offset und optionaler Notiz.
- `export` führt Transkript und Markierungen zusammen (Markdown, optional PDF); Markierungen überstehen erneute Transkriptionsläufe.

### 2.4 Live-Transkription (Windows und macOS)

**Aufnahme**
- Mitschnitt von Monitor oder einzelnem Anwendungsfenster, System-Audio und Mikrofon; auch „nur Ton“.
- Transkript erscheint mit wenigen Sekunden Verzögerung, mit Vorschau des gerade Gesprochenen.
- Bildquelle lässt sich während der Aufnahme wechseln; ein offenes Teams-Fenster wird in der Auswahl vorgezogen.
- Fensteraufnahme erfasst nur das Fenster, auch wenn andere davor liegen.
- Screenshots aus der Zwischenablage (macOS ⌘⇧⌃4, Windows Win+Shift+S) werden automatisch zu Standbildern der Sitzung.

**Sprecher**
- Mikrofon = „Ich“; das System-Audio wird live per Stimm-Embedding in „Sprecher 1/2/3“ getrennt.
- Vor-Ort-Modus: mehrere Personen am selben Mikrofon werden ebenfalls in „Sprecher N“ getrennt.
- Übersprech-Filter: Mikrofon-Abschnitte, die nur das Lautsprecher-Echo der Gegenseite sind, werden vor der Transkription verworfen (Hüllkurven-Korrelation, Schwelle einstellbar).

**Leistung und Messung**
- Anzeige von Laufzeit, Verzögerung und Rückstand.
- Aufholmodus bei Rückstand: wartende Abschnitte werden zusammengelegt und sparsamer dekodiert.
- Getrennte Modelle für live (Tempo) und Nachschärfen (Genauigkeit).
- Fazit nach der Sitzung (`bilanz.json`) und Diagnose-Log je Abschnitt (`diagnose.jsonl`).
- WAV-Replay für reproduzierbare Messläufe ohne Aufnahme, auch unter Linux.

**Nach dem Stopp**
- Nachschärfen: die Offline-Pipeline läuft über den Mitschnitt und ersetzt das Live-Transkript; die Live-Fassung bleibt erhalten.
- Ergebnisordner im Format eines Offline-Laufs, direkt nutzbar für die KI-Analyse.
- Zusätzlich ein fertiger `LLM-Wiki/`-Ordner je Sitzung (Transkript plus Bilder); der Titel ist nachträglich änderbar.

**Sofort aufnehmen**
- Aufnahme ohne Projekt mit den zuletzt benutzten Geräten, per Desktop-Verknüpfung oder systemweitem Tastenkürzel.
- Die Sitzung lässt sich später einem Projekt zuordnen oder über „Speichern unter …“ ablegen.

### 2.5 Absturzsicherung und Wiederaufnahme

- Laufende Sicherung über Journal, Zustandsdatei, Lock-Datei und Stimmprofile.
- Nach Absturz oder Stromausfall: Fortsetzen (gleicher Ordner, Nummern und Sprecher zählen fort), Abschließen (Transkript aus dem Gesicherten) oder Verwerfen.
- Eine vorhandene Aufnahme wird nie überschrieben; Teil-Dateien werden am Ende zusammengesetzt.
- Der Browser verbindet sich nach einem Verbindungsverlust von selbst wieder.

### 2.6 Souffleur: Live-Abgleich mit dem LLM-Wiki

Zeigt nur dem Moderator Hinweise, während das Meeting läuft.

| Hinweis | Bedeutung |
|---|---|
| Widerspruch | Aussage weicht von einer Wiki-Stelle ab; „gesagt“ und „im Wiki“ stehen mit wörtlichem Zitat nebeneinander |
| Frage | Echte Frage erkannt; Antwortvorschlag mit Fundstelle aus dem Wiki, sonst offener Punkt |
| Offener Punkt | Als ungeklärt benannt oder im Wiki nicht vorhanden; die Liste bleibt nach dem Meeting erhalten |
| Essenz 2 / 5 min | KI-Zusammenfassung des gewählten Zeitfensters auf Knopfdruck |
| Mitdenken (zuschaltbar) | Zweite Spur mit Nachdenken: Karten „Bestätigung“ (aus dem Wiki, mit Zitat), „Erkenntnis“ und „Gedanke“ (Idee weitergedacht), je mit Herkunft Wiki / Gespräch / KI-Wissen |

- Belegtes und KI-Erzeugtes bleiben sichtbar getrennt; der Wortlaut des Transkripts wird nie verändert.
- Lokale Prüfung jeder KI-Antwort: Aussage muss wörtlich im Segment stehen, Zitat wörtlich im Wiki-Auszug; Dubletten werden unterdrückt.
- Wiki-Suche lokal und lexikalisch; ein Glossar bestätigter Fehlerkennungen verhindert falsche Widersprüche.
- Arbeitet auch ohne Wiki (nur Fragen und Essenz) und meldet seinen Zustand, wenn die KI fehlt.
- Mitdenken läuft alle ein bis zwei Minuten neben dem Abgleich, ohne ihn zu bremsen; Karten bleiben im Sitzungsordner und gehen nicht ins Wiki. Vorerst nicht mit der lokalen KI.
- Auskoppeln in ein kleines Fenster, das immer im Vordergrund liegt (Document Picture-in-Picture, Chrome/Edge), mit Start- und Stopp-Knopf.
- Fokus-Ansicht mit kompaktem Kopf; Spalte per Alt+S ausblendbar, etwa beim Bildschirmteilen.
- Verzögerung je Hinweis wird gemessen und aufgeschlüsselt (Spracherkennung, Wiki-Suche, KI-Start, KI-Antwort).
- Testmodus: ein gespeichertes Transkript abspielen (Tempo 1× bis 20×), ohne Audio.

**Leitfaden (Meeting-Vorbereitung)**
- Checkliste aus einer Markdown-Datei (`- [ ]`-Punkte, Pflichtpunkte unter „Muss“).
- Der Souffleur setzt Punkte auf *angesprochen* oder *geklärt*, nur mit wörtlichem Beleg; der Status ist von Hand überschreibbar.
- „Nachhaken“, wenn ein Punkt angesprochen, aber nicht geklärt wurde und das Gespräch weitergezogen ist.
- Wiki-Bezug je Punkt über Kennungen wie `ENT-003`; Abweichungen vom Wiki werden gemeldet.
- Bildschirm als zweite Belegquelle: Text auf Standbildern wird per OCR gelesen und als „gezeigt, nicht gesagt“ gekennzeichnet (macOS).
- Offene Punkte aus dem Meeting lassen sich als Leitfaden-Punkt übernehmen; das Ergebnis ist der Startpunkt fürs Folgemeeting.

### 2.7 KI-Analyse per Agent

- Ein Claude-Agent wertet Transkript und Standbilder aus und schreibt Dokumente in einen Ergebnisordner.
- Steuerung über Prozessname, freien Kontext, Kontextdateien und Skills (z. B. `transkript-normalisierung`, `prozessrekonstruktion`, `prozessdoku-qs`, `arbeitsanweisung-ableiten`).
- Ergebnisse: `INDEX.md`, Prozessdokumentation, Prozessbild (Mermaid → PNG/SVG), BPMN-2.0-Modell mit Lanes (`.bpmn`, PNG, SVG), Protokoll und Agent-Log.
- BPMN: der Agent liefert nur die Fachlogik als JSON; Validierung, Layout, XML und Bild erzeugt AudioScribe. Nutzbar in Camunda Modeler, bpmn.io, Signavio.
- Sicherheit: der Agent schreibt nur im Arbeitsordner und arbeitet auf einer Kopie; Schreibversuche außerhalb werden abgelehnt und protokolliert. Bash ist abschaltbar.
- Fortschritt als Schrittliste des Agenten mit aktivem Skill, angesehenen Bildern und geschriebenen Dokumenten.
- Nachbessern einer Analyse in derselben Sitzung (`--resume`, experimentell).

### 2.8 Projekte und Ablage ins Wiki

- Ein Projekt ist ein eigener Ordner mit Einstellungen, Sitzungen und optional einem LLM-Wiki (neu angelegt oder verknüpft, Karpathy-Muster `wiki/` + `raw/`).
- Assistent „Neues Projekt“ in vier Schritten mit Strukturvorschau; ein Projekt kann als Vorlage dienen.
- Ablage ist rein anhängend: geschrieben wird nur nach `raw/` und in den Assets-Ordner, nie unter `wiki/`; nichts wird überschrieben.
- Zwei Ablageformate: Ordner je Sitzung oder eine Datei je Meeting nach dem Schema `<Datum>_<Art>_<Thema>`.
- Wahlweise mit Bildern, Markierungen des Souffleurs und Leitfaden-Stand; „Speichern unter …“ in beliebige Ordner.
- Automatik je Projekt: nachfragen, immer speichern oder nicht anbieten.
- Ergebnisse der KI-Analyse lassen sich als KI-erzeugt gekennzeichnet zur Sitzung ins Wiki legen.

**Ins Wiki einarbeiten (Ingest)**
- Der KI-Agent arbeitet eine abgelegte Sitzung nach den Regeln des Wikis (`CLAUDE.md`, Skills des Wikis) in die Seiten ein.
- Schreibrecht nur unter `wiki/`; `raw/` und `CLAUDE.md` bleiben unberührt, Bash ist aus.
- Warteschlange im Hintergrund, unabhängig vom geöffneten Projekt; System-Mitteilungen bei fertig, Fehler und Rückfrage.
- Rückfragen des Agenten im Dialog beantworten, nach dem Lauf in derselben Sitzung nachfassen.
- Unterbrochene Aufträge werden nach einem Neustart fortgesetzt.

### 2.9 Lokale KI und Variante cloud-compliant

- KI-Dienst umschaltbar zwischen Claude und Ollama, global oder je Projekt.
- Souffleur mit lokalem Modell produktiv nutzbar; KI-Analyse lokal experimentell (Claude Code wird auf Ollama umgeleitet).
- AudioScribe startet den Ollama-Dienst bei Bedarf selbst.
- Variante `cloud-compliant` (eigener Branch, ein Schalter in `variante.py`): nur lokale KI, Ollama nur auf `localhost`, keine KI-Analyse, Claude weder installiert noch gestartet. Nicht per Umgebungsvariable oder Einstellung umstellbar.

### 2.10 Oberfläche und Bedienung

- Startseite mit fünf Einstiegen: Sofort aufnehmen, Neues Projekt, Projekt öffnen, Aufnahme transkribieren, Demo abspielen.
- Im Projekt drei Bereiche: Live-Sitzung, Nachbereitung, Projekt.
- Läufe arbeiten im Server weiter, auch wenn der Browser-Tab geschlossen wird.
- Einstellungen auf zwei Ebenen (global, je Projekt überschreibbar).
- Deutsche und englische Oberfläche, inklusive englischer Prompts und englischem Demo-Wiki.
- Design System / Hell / Dunkel; Ansichten per Adresse erreichbar (`#/projekt/live` usw.).
- Umgebungs-Check (`audioscribe doctor`, auch als Karte in den Einstellungen): Python, ffmpeg, Rechengerät, WhisperX, ASR-Backend, Diarisierung, Live-Geräte, KI-Dienste, Souffleur, Variante.
- Hugging-Face-Diagnose: unterscheidet einen ungültigen Token von nicht akzeptierten Modell-Bedingungen.
- macOS: prüft die Berechtigungen für Mikrofon und Bildschirmaufnahme und sagt, was fehlt und wo es steht.
- Das Wiki lässt sich in der laufenden Sitzung wechseln oder lösen.
- Nativer Ordnerdialog (Finder, Explorer), sonst eingebauter Ordner-Browser.
- KI-Verbrauch im Kopf: Tokens und ungefährer Preis in US-Dollar, aufgeteilt nach Souffleur-Sitzung und Analyse-Lauf; lokale Aufrufe zählen nicht.
- Demo-Modus: erfundenes Beispiel-Meeting mit Beispiel-Wiki, Zeitstrahl der bisherigen Meetings, Pause-Knopf; nichts wird aufgenommen.

---

## 3. Datenschutz und Datenfluss

| Schritt | Wo gerechnet wird | Was den Rechner verlässt |
|---|---|---|
| Transkription, Alignment, Sprecher-Trennung | lokal | nichts (nur der einmalige Download der Modellgewichte) |
| Bildwechsel-Erkennung, OCR | lokal | nichts |
| Souffleur mit Ollama | lokal | nichts |
| Souffleur mit Claude | Anthropic | Transkript-Fenster und Wiki-Auszüge; ohne Werkzeuge, in leerem Arbeitsordner, ohne Sitzungsdateien |
| Mitdenken mit Claude (nur wenn eingeschaltet) | Anthropic | je Lauf bis zu fünf Minuten Transkript, Wiki-Auszüge, bisherige Karten und Hinweise; sonst wie der Souffleur |
| KI-Analyse, Wiki-Einarbeitung mit Claude | Anthropic | Transkript, angesehene Standbilder, Kontext |
| Variante cloud-compliant | lokal | nichts |

Die Oberflächen binden nur an `127.0.0.1`; es gibt keinen Upload.
