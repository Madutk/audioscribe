"""BPMN-Modell mit Lanes aus der Fachlogik des Agenten (FR-36).

Ein "Mermaid fuer BPMN" gibt es nicht; das editierbare Standardformat ist BPMN 2.0
XML (``.bpmn``) - und das braucht neben der Fachlogik exakte Koordinaten (DI), die ein
Sprachmodell unzuverlaessig schreibt. Darum die Arbeitsteilung:

* Der Agent schreibt nur die **Fachlogik** nach ``bpmn-modell.json`` (Lanes, Knoten
  mit S-/E-Nummern, Fluesse).
* audioscribe **validiert** sie, berechnet ein **Swimlane-Layout** (Lanes als Zeilen,
  Ablauf von links nach rechts) und schreibt daraus ``bpmn-modell.bpmn`` (oeffnen und
  weiterbearbeiten in Camunda Modeler, demo.bpmn.io, Signavio, ADONIS ...) sowie
  ``bpmn-modell.svg``; das PNG entsteht ueber den Browser-Weg aus ``prozessbild``.

Bewusst ohne ``bpmn-auto-layout`` (ordnet laut Doku nur den ersten Pool, keine Lanes)
und ohne bpmn-js zum Zeichnen (Lizenz verlangt ein sichtbares Wasserzeichen) - das
Layout ist hier ohnehin bekannt.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

from audioscribe import __version__

JSON_NAME = "bpmn-modell.json"
BPMN_NAME = "bpmn-modell.bpmn"
SVG_NAME = "bpmn-modell.svg"
PNG_NAME = "bpmn-modell.png"
EXPORTER = "audioscribe"

TYPEN = ("start", "ende", "aufgabe", "entscheidung", "zusammenfuehrung")
ARTEN = ("user", "manual", "service")
_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")  # XML-NCName, wie BPMN es verlangt
_NUMMER_RE = re.compile(r"^[SE]\d+(\.\d+)*$")  # S3, E1, S2.4 -> Nummer ins Label

# --- Geometrie (px) ------------------------------------------------------------------
POOL_X, POOL_Y, POOL_HEAD, LANE_HEAD = 10, 10, 30, 30
X0 = POOL_X + POOL_HEAD + LANE_HEAD + 30  # linker Rand der ersten Spalte
COL_W = 170  # Spaltenabstand
TASK_W, TASK_H = 120, 80
GW, EV = 50, 36
LINE_H = 14  # Zeilenhoehe der Beschriftung
LANE_PAD = 15  # Innenabstand oben in einer Lane
CHANNEL = 12  # Abstand je Rueckkante im Kanal am Lane-Boden
CHAR_W = 6.6  # geschaetzte mittlere Zeichenbreite bei 12 px Arial
# Gateway-Beschriftung links oberhalb der Raute: so breit wie die Luecke zur Vorspalte.
GW_LABEL_W = COL_W - TASK_W / 2 - GW / 2 - 8
EV_LABEL_W = 110

_NS = {
    "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
    "dc": "http://www.omg.org/spec/DD/20100524/DC",
    "di": "http://www.omg.org/spec/DD/20100524/DI",
}
for _prefix, _uri in _NS.items():
    ET.register_namespace(_prefix, _uri)


# --- Modell ------------------------------------------------------------------------


@dataclass
class Lane:
    id: str
    name: str


@dataclass
class Knoten:
    id: str
    typ: str
    lane: str
    text: str = ""
    art: str | None = None
    unsicher: bool = False

    @property
    def label(self) -> str:
        """Beschriftung im Diagramm: Nummer vorn (Abgleich mit der Schrittliste)."""
        text = self.text
        if _NUMMER_RE.match(self.id):
            # Hat der Agent die Nummer doch in den Text geschrieben: nicht doppelt zeigen.
            text = re.sub(rf"^{re.escape(self.id)}\s*:\s*", "", text)
        text = f"⚠ {text}" if self.unsicher else text
        if _NUMMER_RE.match(self.id):
            return f"{self.id}: {text}".strip()
        return text


@dataclass
class Fluss:
    von: str
    nach: str
    text: str = ""
    id: str = ""


@dataclass
class Modell:
    lanes: list[Lane]
    knoten: list[Knoten]
    fluesse: list[Fluss]
    lanes_art: str = ""
    lanes_begruendung: str = ""

    def knoten_by_id(self) -> dict[str, Knoten]:
        return {k.id: k for k in self.knoten}


class ModellFehler(ValueError):
    def __init__(self, fehler: list[str]) -> None:
        super().__init__("; ".join(fehler))
        self.fehler = fehler


def _str(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def parse_modell(data: object) -> Modell:
    """JSON-Daten -> ``Modell``; sammelt ALLE Fehler und wirft ``ModellFehler``."""
    fehler: list[str] = []
    if not isinstance(data, dict):
        raise ModellFehler(["Oberste Ebene muss ein JSON-Objekt sein."])

    lanes: list[Lane] = []
    for i, raw in enumerate(data.get("lanes") or []):
        lid = _str(raw.get("id")) if isinstance(raw, dict) else ""
        name = _str(raw.get("name")) if isinstance(raw, dict) else ""
        if not lid or not _ID_RE.match(lid):
            fehler.append(f"lanes[{i}]: ungueltige id {lid!r}")
            continue
        if any(lane.id == lid for lane in lanes):
            fehler.append(f"lanes[{i}]: doppelte id {lid!r}")
            continue
        lanes.append(Lane(lid, name or lid))
    if not lanes:
        fehler.append("Mindestens eine Lane noetig (lanes).")
    lane_ids = {lane.id for lane in lanes}

    knoten: list[Knoten] = []
    for i, raw in enumerate(data.get("knoten") or []):
        if not isinstance(raw, dict):
            fehler.append(f"knoten[{i}]: kein Objekt")
            continue
        kid, typ, lane = _str(raw.get("id")), _str(raw.get("typ")), _str(raw.get("lane"))
        where = f"knoten[{i}] ({kid or '?'})"
        if not kid or not _ID_RE.match(kid):
            fehler.append(f"{where}: ungueltige id (Buchstabe am Anfang, keine Leerzeichen)")
            continue
        if any(k.id == kid for k in knoten):
            fehler.append(f"{where}: doppelte id")
            continue
        # Falscher Typ / falsche Lane: melden, den Knoten aber behalten - sonst
        # folgen Dutzende Folgefehler ("unbekannter Knoten", "nicht erreichbar").
        if typ not in TYPEN:
            fehler.append(f"{where}: typ {typ!r} unbekannt (erlaubt: {', '.join(TYPEN)})")
        if lane not in lane_ids:
            fehler.append(f"{where}: lane {lane!r} unbekannt")
        art = _str(raw.get("art")) or None
        if art is not None and art not in ARTEN:
            fehler.append(f"{where}: art {art!r} unbekannt (erlaubt: {', '.join(ARTEN)})")
            art = None
        text = _str(raw.get("text"))
        if typ in ("aufgabe", "entscheidung") and not text:
            fehler.append(f"{where}: text fehlt")
        knoten.append(Knoten(kid, typ, lane, text, art, bool(raw.get("unsicher"))))
    ids = {k.id for k in knoten}

    fluesse: list[Fluss] = []
    for i, raw in enumerate(data.get("fluesse") or []):
        von = _str(raw.get("von")) if isinstance(raw, dict) else ""
        nach = _str(raw.get("nach")) if isinstance(raw, dict) else ""
        where = f"fluesse[{i}] ({von or '?'} -> {nach or '?'})"
        if von not in ids or nach not in ids:
            fehler.append(f"{where}: verweist auf unbekannten Knoten")
            continue
        if von == nach:
            fehler.append(f"{where}: Fluss auf sich selbst")
            continue
        fluesse.append(Fluss(von, nach, _str(raw.get("text")), f"Flow_{len(fluesse) + 1}"))

    aus: dict[str, int] = {k: 0 for k in ids}
    ein: dict[str, int] = {k: 0 for k in ids}
    for f in fluesse:
        aus[f.von] += 1
        ein[f.nach] += 1
    starts = [k.id for k in knoten if k.typ == "start"]
    if not starts:
        fehler.append("Mindestens ein Knoten mit typ 'start' noetig.")
    if not any(k.typ == "ende" for k in knoten):
        fehler.append("Mindestens ein Knoten mit typ 'ende' noetig.")
    for k in knoten:
        if k.typ == "start" and ein[k.id]:
            fehler.append(f"{k.id}: ein Start darf keinen eingehenden Fluss haben")
        if k.typ == "ende" and aus[k.id]:
            fehler.append(f"{k.id}: ein Ende darf keinen ausgehenden Fluss haben")
        if k.typ != "ende" and not aus[k.id]:
            fehler.append(f"{k.id}: hat keinen ausgehenden Fluss (Sackgasse)")
        if k.typ == "entscheidung" and aus[k.id] < 2:
            fehler.append(f"{k.id}: eine Entscheidung braucht mindestens zwei Ausgaenge")
    # Erreichbarkeit ab den Starts
    seen, stack = set(starts), list(starts)
    while stack:
        u = stack.pop()
        for f in fluesse:
            if f.von == u and f.nach not in seen:
                seen.add(f.nach)
                stack.append(f.nach)
    for k in knoten:
        if starts and k.id not in seen:
            fehler.append(f"{k.id}: vom Start aus nicht erreichbar")

    if fehler:
        raise ModellFehler(fehler)
    return Modell(
        lanes=lanes,
        knoten=knoten,
        fluesse=fluesse,
        lanes_art=_str(data.get("lanes_art")),
        lanes_begruendung=_str(data.get("lanes_begruendung")),
    )


def lade_modell(path: Path) -> Modell:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise ModellFehler([f"{Path(path).name} nicht lesbar: {exc}"]) from exc
    except ValueError as exc:
        raise ModellFehler([f"{Path(path).name} ist kein gueltiges JSON: {exc}"]) from exc
    return parse_modell(data)


# --- Layout ------------------------------------------------------------------------


def wrap(text: str, width: float) -> list[str]:
    """Greedy-Umbruch auf eine geschaetzte Pixelbreite.

    Ein einzelnes Wort darf die Breite um die Haelfte ueberziehen, bevor es geteilt
    wird - "Freigegeben?" gebrochen als "Freigegebe-/n?" liest sich schlechter.
    """
    max_chars = max(4, int(width / CHAR_W))
    split_at = int(max_chars * 1.5)
    lines: list[str] = []
    line = ""
    for word in text.split():
        while len(word) > split_at:
            if line:
                lines.append(line)
                line = ""
            lines.append(word[: max_chars - 1] + "-")
            word = word[max_chars - 1:]
        if not line:
            line = word
        elif len(line) + 1 + len(word) <= max_chars:
            line += " " + word
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines or [""]


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


@dataclass
class Kante:
    fluss: Fluss
    punkte: list[tuple[float, float]]
    label: Box | None = None


@dataclass
class Layout:
    pool: Box
    lanes: dict[str, Box]
    knoten: dict[str, Box]
    labels: dict[str, Box]  # Beschriftung unter/ueber Ereignissen und Gateways
    kanten: list[Kante]
    spalte: dict[str, int] = field(default_factory=dict)
    zeile: dict[str, int] = field(default_factory=dict)
    rueckkanten: set[str] = field(default_factory=set)  # Fluss-IDs

    @property
    def width(self) -> int:
        return int(self.pool.x + self.pool.w + POOL_X)

    @property
    def height(self) -> int:
        return int(self.pool.y + self.pool.h + POOL_Y)


def _groesse(k: Knoten) -> tuple[float, float]:
    if k.typ == "aufgabe":
        lines = wrap(k.label, TASK_W - 12)
        return TASK_W, max(TASK_H, (32 if k.art else 16) + LINE_H * len(lines))
    if k.typ in ("entscheidung", "zusammenfuehrung"):
        return GW, GW
    return EV, EV


def _label_hoehe(k: Knoten) -> float:
    """Platzbedarf der Beschriftung neben kleinen Formen (Ereignis/Gateway)."""
    if k.typ == "aufgabe" or not k.label:
        return 0
    return LINE_H * len(wrap(k.label, _label_breite(k))) + 6


def _label_breite(k: Knoten) -> float:
    return GW_LABEL_W if k.typ in ("entscheidung", "zusammenfuehrung") else EV_LABEL_W


def layout(m: Modell) -> Layout:
    by_id = m.knoten_by_id()
    out: dict[str, list[Fluss]] = {k.id: [] for k in m.knoten}
    for f in m.fluesse:
        out[f.von].append(f)

    # 1) Rueckkanten per DFS ab den Starts (Kante auf einen Knoten im aktuellen Pfad).
    rueck: set[str] = set()
    order: list[str] = []
    state: dict[str, int] = {}  # 1 = auf dem Pfad, 2 = fertig
    for start in (k.id for k in m.knoten if k.typ == "start"):
        if start in state:
            continue
        stack: list[tuple[str, int]] = [(start, 0)]
        state[start] = 1
        order.append(start)
        while stack:
            u, i = stack[-1]
            if i < len(out[u]):
                stack[-1] = (u, i + 1)
                f = out[u][i]
                if state.get(f.nach) == 1:
                    rueck.add(f.id)
                elif f.nach not in state:
                    state[f.nach] = 1
                    order.append(f.nach)
                    stack.append((f.nach, 0))
            else:
                state[u] = 2
                stack.pop()
    vor = [f for f in m.fluesse if f.id not in rueck]

    # 2) Spalte = laengster Pfad auf dem Vorwaerts-DAG (Kahn).
    indeg = {k.id: 0 for k in m.knoten}
    for f in vor:
        indeg[f.nach] += 1
    spalte = {k: 0 for k in indeg}
    queue = [k for k in order if indeg[k] == 0]
    while queue:
        u = queue.pop(0)
        for f in vor:
            if f.von == u:
                spalte[f.nach] = max(spalte[f.nach], spalte[u] + 1)
                indeg[f.nach] -= 1
                if indeg[f.nach] == 0:
                    queue.append(f.nach)

    # 3) Zeile innerhalb der Lane: Hauptpfad erbt die Zeile des Vorgaengers, weitere
    #    Ausgaenge einer Entscheidung weichen nach unten aus. Belegte Zellen -> naechste Zeile.
    pref: dict[str, int] = {}
    for u in order:
        pref.setdefault(u, 0)
        ausgaenge = [f for f in out[u] if f.id not in rueck]
        nebenzweig = 0
        for f in ausgaenge:
            if f.nach in pref:
                continue
            if by_id[f.nach].lane != by_id[u].lane:
                pref[f.nach] = 0
            else:
                pref[f.nach] = pref[u] + nebenzweig
                if by_id[u].typ == "entscheidung":
                    nebenzweig += 1
    zeile: dict[str, int] = {}
    belegt: set[tuple[str, int, int]] = set()
    rank = {k: i for i, k in enumerate(order)}
    for kid in sorted(by_id, key=lambda k: (spalte[k], rank.get(k, 10**6))):
        lane, col, row = by_id[kid].lane, spalte[kid], pref.get(kid, 0)
        while (lane, col, row) in belegt:
            row += 1
        belegt.add((lane, col, row))
        zeile[kid] = row

    # 4) Masse: einheitliche Zeilenhoehe, Kanal am Lane-Boden fuer Rueckkanten.
    row_h = max(
        [h + _label_hoehe(k) for k in m.knoten for _, h in [_groesse(k)]] + [TASK_H]
    ) + 40
    rueck_je_lane: dict[str, int] = {lane.id: 0 for lane in m.lanes}
    for f in m.fluesse:
        if f.id in rueck:
            rueck_je_lane[by_id[f.von].lane] += 1
    n_cols = max(spalte.values(), default=0) + 1
    lane_boxes: dict[str, Box] = {}
    y = POOL_Y
    lane_x = POOL_X + POOL_HEAD
    content_w = X0 - lane_x + n_cols * COL_W + 20
    for lane in m.lanes:
        rows = max([zeile[k.id] + 1 for k in m.knoten if k.lane == lane.id] + [1])
        channel = (CHANNEL * (rueck_je_lane[lane.id] + 1)) if rueck_je_lane[lane.id] else 0
        h = LANE_PAD + rows * row_h + channel
        lane_boxes[lane.id] = Box(lane_x, y, content_w, h)
        y += h
    pool = Box(POOL_X, POOL_Y, POOL_HEAD + content_w, y - POOL_Y)

    boxes: dict[str, Box] = {}
    labels: dict[str, Box] = {}
    def links_frei(k: Knoten) -> bool:
        return (k.lane, spalte[k.id] - 1, zeile[k.id]) not in belegt

    for k in m.knoten:
        w, h = _groesse(k)
        lb = lane_boxes[k.lane]
        cx = X0 + spalte[k.id] * COL_W + TASK_W / 2
        cy = lb.y + LANE_PAD + zeile[k.id] * row_h + row_h / 2
        boxes[k.id] = Box(cx - w / 2, cy - h / 2, w, h)
        lh = _label_hoehe(k)
        if lh:
            if k.typ in ("entscheidung", "zusammenfuehrung"):
                # links oberhalb der Raute: oben/unten/rechts gehen die Zweige ab
                # breiter, wenn links daneben (gleiche Lane, gleiche Zeile) nichts steht
                lw = EV_LABEL_W if links_frei(k) else GW_LABEL_W
                lh = LINE_H * len(wrap(k.label, lw)) + 6
                labels[k.id] = Box(cx - w / 2 - 4 - lw, cy - h / 2 - lh + 4, lw, lh)
            else:
                labels[k.id] = Box(cx - EV_LABEL_W / 2, cy + h / 2 + 4, EV_LABEL_W, lh)

    # 5) Kanten orthogonal.
    def mitte(kid: str) -> float:
        """x der Gasse rechts neben der Spalte eines Knotens (zwischen zwei Spalten)."""
        return X0 + spalte[kid] * COL_W + TASK_W / 2 + COL_W / 2

    wege: dict[str, list[tuple[float, float]]] = {}
    kanal_idx: dict[str, int] = {lane.id: 0 for lane in m.lanes}
    for f in m.fluesse:
        if f.id in rueck:  # Schleife: unten raus, im Kanal am Lane-Boden zurueck
            s, t, src = boxes[f.von], boxes[f.nach], by_id[f.von]
            lb = lane_boxes[src.lane]
            kanal_idx[src.lane] += 1
            ky = lb.y + lb.h - CHANNEL * kanal_idx[src.lane]
            end_y = t.y + t.h if t.y + t.h < ky else t.y
            wege[f.id] = [(s.cx, s.y + s.h), (s.cx, ky), (t.cx, ky), (t.cx, end_y)]

    for kid, src in by_id.items():
        s = boxes[kid]
        ausgaenge = [f for f in out[kid] if f.id not in rueck]
        if src.typ not in ("entscheidung", "zusammenfuehrung"):
            for f in ausgaenge:
                t = boxes[f.nach]
                if abs(s.cy - t.cy) < 0.5:
                    wege[f.id] = [(s.x + s.w, s.cy), (t.x, t.cy)]
                else:
                    mx = mitte(kid)
                    wege[f.id] = [(s.x + s.w, s.cy), (mx, s.cy), (mx, t.cy), (t.x, t.cy)]
            continue
        # Gateway: jeder Ausgang bekommt einen eigenen Anschluss. Gleiche Hoehe -> rechts;
        # der ENTFERNTESTE Zweig nach oben/unten -> oberer/unterer Anschluss (aussen),
        # naehere Zweige -> rechts raus und in einer eigenen Gasse abbiegen (innen).
        # So liegen die Wege geschachtelt und kreuzen sich nicht. Den unteren Anschluss
        # belegt eine Schleife zuerst.
        unten_frei = not any(f.id in rueck for f in out[kid])
        for richtung in (-1, 1):  # -1 = nach oben, 1 = nach unten
            zweige = sorted(
                (f for f in ausgaenge if (boxes[f.nach].cy - s.cy) * richtung > 0.5),
                key=lambda f: abs(boxes[f.nach].cy - s.cy),
                reverse=True,
            )
            anschluss_frei = unten_frei if richtung == 1 else True
            gasse = 0
            for f in zweige:
                t = boxes[f.nach]
                if anschluss_frei:
                    py = s.y if richtung == -1 else s.y + s.h
                    wege[f.id] = [(s.cx, py), (s.cx, t.cy), (t.x, t.cy)]
                    anschluss_frei = False
                    continue
                mx = mitte(kid) - 10 + 12 * gasse  # entferntere Zweige innen (kleineres x)
                gasse += 1
                wege[f.id] = [(s.x + s.w, s.cy), (mx, s.cy), (mx, t.cy), (t.x, t.cy)]
        for f in ausgaenge:
            if f.id not in wege:  # gleiche Hoehe
                t = boxes[f.nach]
                wege[f.id] = [(s.x + s.w, s.cy), (t.x, t.cy)]

    kanten: list[Kante] = []
    for f in m.fluesse:
        punkte = wege[f.id]
        label = None
        if f.text:
            (x0, y0), (_, y1) = punkte[0], punkte[1]
            w = len(f.text) * CHAR_W + 6
            if abs(y0 - y1) < 0.5:  # erstes Stueck waagerecht -> Text darueber
                label = Box(x0 + 6, y0 - LINE_H - 4, w, LINE_H)
            else:  # erstes Stueck senkrecht -> Text daneben
                label = Box(x0 + 6, (y0 + 4) if y1 > y0 else (y0 - LINE_H - 4), w, LINE_H)
        kanten.append(Kante(f, punkte, label))

    return Layout(pool, lane_boxes, boxes, labels, kanten, spalte, zeile, rueck)


# --- BPMN 2.0 XML ------------------------------------------------------------------

_TAG = {
    "start": "startEvent",
    "ende": "endEvent",
    "entscheidung": "exclusiveGateway",
    "zusammenfuehrung": "exclusiveGateway",
}
_TASK_TAG = {None: "task", "user": "userTask", "manual": "manualTask", "service": "serviceTask"}


def _q(prefix: str, tag: str) -> str:
    return f"{{{_NS[prefix]}}}{tag}"


def _bounds(parent: ET.Element, b: Box) -> None:
    ET.SubElement(
        parent, _q("dc", "Bounds"),
        x=f"{b.x:.0f}", y=f"{b.y:.0f}", width=f"{b.w:.0f}", height=f"{b.h:.0f}",
    )


def to_bpmn_xml(m: Modell, lay: Layout, prozessname: str) -> str:
    defs = ET.Element(
        _q("bpmn", "definitions"),
        id="Definitions_1",
        targetNamespace="http://bpmn.io/schema/bpmn",
        exporter=EXPORTER,
        exporterVersion=__version__,
    )
    collab = ET.SubElement(defs, _q("bpmn", "collaboration"), id="Collaboration_1")
    ET.SubElement(
        collab, _q("bpmn", "participant"),
        id="Participant_1", name=prozessname, processRef="Process_1",
    )
    proc = ET.SubElement(defs, _q("bpmn", "process"), id="Process_1", isExecutable="false")
    if m.lanes_begruendung:
        doc = ET.SubElement(proc, _q("bpmn", "documentation"))
        doc.text = f"Lanes ({m.lanes_art or 'Aufteilung'}): {m.lanes_begruendung}"
    lane_set = ET.SubElement(proc, _q("bpmn", "laneSet"), id="LaneSet_1")
    for lane in m.lanes:
        el = ET.SubElement(lane_set, _q("bpmn", "lane"), id=f"Lane_{lane.id}", name=lane.name)
        for k in m.knoten:
            if k.lane == lane.id:
                ref = ET.SubElement(el, _q("bpmn", "flowNodeRef"))
                ref.text = k.id
    for k in m.knoten:
        tag = _TASK_TAG[k.art] if k.typ == "aufgabe" else _TAG[k.typ]
        el = ET.SubElement(proc, _q("bpmn", tag), id=k.id, name=k.label)
        for f in m.fluesse:
            if f.nach == k.id:
                ET.SubElement(el, _q("bpmn", "incoming")).text = f.id
        for f in m.fluesse:
            if f.von == k.id:
                ET.SubElement(el, _q("bpmn", "outgoing")).text = f.id
    for f in m.fluesse:
        attrs = {"id": f.id, "sourceRef": f.von, "targetRef": f.nach}
        if f.text:
            attrs["name"] = f.text
        ET.SubElement(proc, _q("bpmn", "sequenceFlow"), **attrs)

    diagram = ET.SubElement(defs, _q("bpmndi", "BPMNDiagram"), id="BPMNDiagram_1")
    plane = ET.SubElement(
        diagram, _q("bpmndi", "BPMNPlane"), id="BPMNPlane_1", bpmnElement="Collaboration_1"
    )
    shape = ET.SubElement(
        plane, _q("bpmndi", "BPMNShape"),
        id="Participant_1_di", bpmnElement="Participant_1", isHorizontal="true",
    )
    _bounds(shape, lay.pool)
    for lane in m.lanes:
        shape = ET.SubElement(
            plane, _q("bpmndi", "BPMNShape"),
            id=f"Lane_{lane.id}_di", bpmnElement=f"Lane_{lane.id}", isHorizontal="true",
        )
        _bounds(shape, lay.lanes[lane.id])
    for k in m.knoten:
        attrs = {"id": f"{k.id}_di", "bpmnElement": k.id}
        if k.typ in ("entscheidung", "zusammenfuehrung"):
            attrs["isMarkerVisible"] = "true"
        shape = ET.SubElement(plane, _q("bpmndi", "BPMNShape"), **attrs)
        _bounds(shape, lay.knoten[k.id])
        if k.id in lay.labels:
            _bounds(ET.SubElement(shape, _q("bpmndi", "BPMNLabel")), lay.labels[k.id])
    for kante in lay.kanten:
        edge = ET.SubElement(
            plane, _q("bpmndi", "BPMNEdge"), id=f"{kante.fluss.id}_di", bpmnElement=kante.fluss.id
        )
        for x, y in kante.punkte:
            ET.SubElement(edge, _q("di", "waypoint"), x=f"{x:.0f}", y=f"{y:.0f}")
        if kante.label:
            _bounds(ET.SubElement(edge, _q("bpmndi", "BPMNLabel")), kante.label)

    ET.indent(defs, space="  ")
    xml = ET.tostring(defs, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml + "\n"


# --- SVG ---------------------------------------------------------------------------

_STROKE = "#22242a"
_FILL_TASK = "#ffffff"


def _text_lines(x: float, y_top: float, lines: list[str], *, anchor: str = "middle",
                size: int = 12, weight: str = "normal") -> str:
    out = []
    for i, line in enumerate(lines):
        yy = y_top + (i + 1) * LINE_H - 3
        out.append(
            f'<text x="{x:.1f}" y="{yy:.1f}" text-anchor="{anchor}" font-size="{size}" '
            f'font-weight="{weight}">{escape(line)}</text>'
        )
    return "".join(out)


def _icon(k: Knoten, b: Box) -> str:
    x, y = b.x + 7, b.y + 6
    if k.art == "user":
        return (
            f'<circle cx="{x + 6}" cy="{y + 4}" r="3.2" fill="none" stroke="{_STROKE}"/>'
            f'<path d="M{x} {y + 14} q6 -9 12 0" fill="none" stroke="{_STROKE}"/>'
        )
    if k.art == "service":
        return (
            f'<circle cx="{x + 6}" cy="{y + 7}" r="5.5" fill="none" stroke="{_STROKE}" '
            f'stroke-width="2.5" stroke-dasharray="2.2 1.6"/>'
            f'<circle cx="{x + 6}" cy="{y + 7}" r="2" fill="none" stroke="{_STROKE}"/>'
        )
    if k.art == "manual":
        return (
            f'<path d="M{x} {y + 13} v-6 q0 -2 2 -2 h7 q2 0 2 2 q0 2 -2 2 h-3 v4 z" '
            f'fill="none" stroke="{_STROKE}"/>'
        )
    return ""


def to_svg(m: Modell, lay: Layout, prozessname: str) -> str:
    W, H = lay.width, lay.height
    p: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="Arial, Helvetica, sans-serif" fill="{_STROKE}">',
        '<defs><marker id="pfeil" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="8" '
        f'markerHeight="8" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" '
        f'fill="{_STROKE}"/></marker></defs>',
        f'<rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>',
    ]
    pool = lay.pool
    p.append(
        f'<rect x="{pool.x}" y="{pool.y}" width="{pool.w}" height="{pool.h}" '
        f'fill="none" stroke="{_STROKE}" stroke-width="1.5"/>'
        f'<line x1="{pool.x + POOL_HEAD}" y1="{pool.y}" x2="{pool.x + POOL_HEAD}" '
        f'y2="{pool.y + pool.h}" stroke="{_STROKE}" stroke-width="1.5"/>'
    )
    p.append(_vertical_text(pool.x + POOL_HEAD / 2, pool.y + pool.h / 2, prozessname, pool.h - 10,
                            weight="bold"))
    for i, lane in enumerate(m.lanes):
        b = lay.lanes[lane.id]
        fill = "#f7f8fa" if i % 2 else "#ffffff"
        p.append(
            f'<rect x="{b.x}" y="{b.y}" width="{b.w}" height="{b.h}" fill="{fill}" '
            f'stroke="{_STROKE}"/>'
            f'<line x1="{b.x + LANE_HEAD}" y1="{b.y}" x2="{b.x + LANE_HEAD}" y2="{b.y + b.h}" '
            f'stroke="{_STROKE}"/>'
        )
        p.append(_vertical_text(b.x + LANE_HEAD / 2, b.y + b.h / 2, lane.name, b.h - 10))

    for kante in lay.kanten:
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in kante.punkte)
        dash = ' stroke-dasharray="6 4"' if kante.fluss.id in lay.rueckkanten else ""
        p.append(
            f'<polyline points="{pts}" fill="none" stroke="{_STROKE}" stroke-width="1.4"'
            f'{dash} marker-end="url(#pfeil)"/>'
        )
        if kante.label:
            lb = kante.label
            p.append(
                f'<rect x="{lb.x - 2:.1f}" y="{lb.y:.1f}" width="{lb.w:.1f}" height="{lb.h}" '
                f'fill="#ffffff" opacity="0.85"/>'
                + _text_lines(lb.x, lb.y, [kante.fluss.text], anchor="start", size=11)
            )

    for k in m.knoten:
        b = lay.knoten[k.id]
        dash = ' stroke-dasharray="5 3"' if k.unsicher else ""
        if k.typ == "aufgabe":
            p.append(
                f'<rect x="{b.x}" y="{b.y}" width="{b.w}" height="{b.h}" rx="10" '
                f'fill="{"#fbf6e9" if k.unsicher else _FILL_TASK}" stroke="{_STROKE}" '
                f'stroke-width="1.5"{dash}/>'
            )
            p.append(_icon(k, b))
            lines = wrap(k.label, TASK_W - 12)
            top = b.cy - len(lines) * LINE_H / 2
            if k.art:  # Platz fuer das Typ-Icon oben links
                top = max(top, b.y + 24)
            p.append(_text_lines(b.cx, top, lines))
        elif k.typ in ("entscheidung", "zusammenfuehrung"):
            cx, cy, r = b.cx, b.cy, b.w / 2
            p.append(
                f'<polygon points="{cx},{cy - r} {cx + r},{cy} {cx},{cy + r} {cx - r},{cy}" '
                f'fill="#ffffff" stroke="{_STROKE}" stroke-width="1.5"{dash}/>'
                f'<path d="M{cx - 9} {cy - 9} L{cx + 9} {cy + 9} M{cx + 9} {cy - 9} '
                f'L{cx - 9} {cy + 9}" stroke="{_STROKE}" stroke-width="3"/>'
            )
        else:
            breite = 1.5 if k.typ == "start" else 4
            p.append(
                f'<circle cx="{b.cx}" cy="{b.cy}" r="{b.w / 2 - breite / 2}" fill="#ffffff" '
                f'stroke="{_STROKE}" stroke-width="{breite}"/>'
            )
        if k.id in lay.labels:
            lb = lay.labels[k.id]
            if k.typ in ("entscheidung", "zusammenfuehrung"):  # rechtsbuendig an die Raute
                # Breite aus dem Layout (je nach freier Nachbarzelle)
                p.append(_text_lines(lb.x + lb.w, lb.y, wrap(k.label, lb.w), anchor="end"))
            else:
                p.append(_text_lines(lb.cx, lb.y, wrap(k.label, lb.w)))
    p.append("</svg>")
    return "".join(p) + "\n"


def _vertical_text(cx: float, cy: float, text: str, max_len: float, *, weight: str = "normal") -> str:
    chars = max(4, int(max_len / CHAR_W))
    shown = text if len(text) <= chars else text[: chars - 1] + "…"
    return (
        f'<text x="{cx:.1f}" y="{cy:.1f}" transform="rotate(-90 {cx:.1f} {cy:.1f})" '
        f'text-anchor="middle" dominant-baseline="central" font-size="12" '
        f'font-weight="{weight}">{escape(shown)}</text>'
    )


# --- Einstieg ----------------------------------------------------------------------


def ist_von_audioscribe(bpmn_path: Path) -> bool:
    """True, wenn die ``.bpmn`` von uns stammt (und nicht in einem Werkzeug bearbeitet wurde).

    BPMN-Werkzeuge wie der Camunda Modeler setzen beim Speichern ihr eigenes
    ``exporter``-Attribut - daran erkennen wir eine Nachbearbeitung.
    """
    try:
        head = Path(bpmn_path).read_text(encoding="utf-8")[:2000]
    except (OSError, UnicodeDecodeError):
        return False
    return f'exporter="{EXPORTER}"' in head


def erzeuge_bpmn(
    workspace: Path,
    prozessname: str,
    *,
    log: Callable[[str], None] = print,
    browser: Path | None = None,
    neu: bool = False,
) -> list[Path]:
    """``bpmn-modell.json`` -> ``.bpmn`` + ``.svg`` + ``.png``; Probleme nur protokollieren."""
    ws = Path(workspace)
    quelle = ws / JSON_NAME
    if not quelle.is_file():
        log(f"[BPMN] Kein {JSON_NAME} - kein BPMN-Modell erzeugt.")
        return []
    bpmn_path = ws / BPMN_NAME
    if bpmn_path.exists() and not neu and not ist_von_audioscribe(bpmn_path):
        log(
            f"[BPMN] {BPMN_NAME} wurde in einem BPMN-Werkzeug bearbeitet und bleibt unveraendert "
            "(Neuaufbau aus dem JSON nur mit --neu)."
        )
        return []
    try:
        modell = lade_modell(quelle)
    except ModellFehler as exc:
        for f in exc.fehler[:12]:
            log(f"[BPMN] Fehler in {JSON_NAME}: {f}")
        if len(exc.fehler) > 12:
            log(f"[BPMN] ... und {len(exc.fehler) - 12} weitere")
        return []

    lay = layout(modell)
    bpmn_path.write_text(to_bpmn_xml(modell, lay, prozessname), encoding="utf-8")
    svg_path = ws / SVG_NAME
    svg = to_svg(modell, lay, prozessname)
    svg_path.write_text(svg, encoding="utf-8")
    erzeugt = [bpmn_path, svg_path]

    from audioscribe.agent.prozessbild import find_browser, svg_to_png

    browser = browser or find_browser()
    if browser is None:
        log("[BPMN] Kein Edge/Chrome gefunden - PNG fehlt (AUDIOSCRIBE_BROWSER setzen).")
    else:
        try:
            erzeugt.append(svg_to_png(svg, ws / PNG_NAME, browser))
        except RuntimeError as exc:
            log(f"[BPMN] {exc}")
    log(
        f"[BPMN] {', '.join(p.name for p in erzeugt)} "
        f"({len(modell.lanes)} Lane(s), {len(modell.knoten)} Knoten)"
    )
    return erzeugt


def pruefe(workspace: Path) -> list[str]:
    """Nur validieren (fuer den Agenten und ``audioscribe bpmn --pruefen``)."""
    quelle = Path(workspace) / JSON_NAME
    if not quelle.is_file():
        return [f"{JSON_NAME} nicht gefunden in {workspace}"]
    try:
        lade_modell(quelle)
    except ModellFehler as exc:
        return exc.fehler
    return []
