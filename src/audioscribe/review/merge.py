"""Merge von Transkript + Bild-Markierungen zu angereichertem Markdown/PDF (FR-18).

Liest die maschinenlesbaren ``transcript.json``-Daten und die ``marks.json`` und bettet
jedes Bild hinter dem Absatz mit naechstem ``start <= t`` ein (PRD §13.7). Die
Einfuege-Position wird hier aus ``t`` berechnet – nicht in ``marks.json`` gespeichert.
"""

from __future__ import annotations

from bisect import bisect_right
from pathlib import Path

from audioscribe.models import format_timecode
from audioscribe.review.marks import Mark


def _insertion_index(starts: list[float], t: float) -> int:
    """Index des Absatzes mit groesstem ``start <= t`` (0, falls ``t`` davor liegt)."""
    return max(0, bisect_right(starts, t) - 1)


def group_marks_by_paragraph(paragraphs: list[dict], marks: list[Mark]) -> dict[int, list[Mark]]:
    """Ordnet jede Markierung dem Absatz mit naechstem ``start <= t`` zu (PRD §13.7).

    Markierungen vor dem ersten Absatz haengen am ersten Absatz (Index 0).
    """
    starts = [p["start"] for p in paragraphs]
    grouped: dict[int, list[Mark]] = {}
    for m in sorted(marks, key=lambda m: m.t):
        idx = _insertion_index(starts, m.t) if starts else 0
        grouped.setdefault(idx, []).append(m)
    return grouped


def _image_line(m: Mark) -> str:
    tc = format_timecode(m.t)
    alt = f"Markierter Bildschirm {tc}" + (f" – {m.note}" if m.note else "")
    return f"![{alt}]({m.png})"


def render_markdown_with_marks(data: dict, marks: list[Mark]) -> str:
    """Erzeugt Markdown aus ``transcript.json``-Daten mit eingebetteten Bildern.

    Hat das Transkript keine Absaetze (leeres Transkript), werden die Bilder am Ende
    ausgegeben.
    """
    paragraphs = data.get("paragraphs", [])
    by_para = group_marks_by_paragraph(paragraphs, marks)

    lines = [
        f"# Transkript: {data['source']}",
        "",
        "| | |",
        "|---|---|",
        f"| Datei | {data['source']} |",
        f"| Laenge | {format_timecode(data['duration_s'])} |",
        f"| Sprache | {data['language']} |",
        f"| Sprecher | {data['num_speakers']} |",
        f"| Modell | {data['model']} (WhisperX) |",
    ]
    if data.get("created"):
        lines.append(f"| Erstellt | {data['created']} |")
    lines += ["", "---", ""]

    for i, p in enumerate(paragraphs):
        lines.append(f"**[{format_timecode(p['start'])}] {p['speaker']}:** {p['text']}")
        lines.append("")
        for m in by_para.get(i, []):
            lines.append(_image_line(m))
            lines.append("")

    if not paragraphs:  # leeres Transkript: Markierungen trotzdem ausgeben
        for m in sorted(marks, key=lambda m: m.t):
            lines.append(_image_line(m))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_annotated_pdf(
    data: dict, marks: list[Mark], out_path: str | Path, *, base_dir: str | Path
) -> Path:
    """Rendert das annotierte Transkript als PDF mit eingebetteten Standbildern (FR-18).

    ``base_dir`` ist der Ausgabeordner, relativ zu dem die PNG-Pfade aufgeloest werden.
    Fehlende Bilddateien werden uebersprungen (kein Abbruch).
    """
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    from audioscribe.export import _unicode_fonts

    base_dir = Path(base_dir)
    paragraphs = data.get("paragraphs", [])
    by_para = group_marks_by_paragraph(paragraphs, marks)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    fonts = _unicode_fonts()
    if fonts:
        reg, bold = fonts
        pdf.add_font("body", "", reg)
        pdf.add_font("body", "B", bold)
        family = "body"
        enc = lambda s: s  # noqa: E731
    else:
        family = "Helvetica"
        enc = lambda s: s.encode("latin-1", "replace").decode("latin-1")  # noqa: E731

    def line(text: str, size: int, style: str = "") -> None:
        pdf.set_font(family, style, size)
        pdf.multi_cell(0, size * 0.5 + 1, enc(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def put_image(m: Mark) -> None:
        path = base_dir / m.png
        if not path.exists():
            return
        try:
            pdf.image(str(path), w=140)
        except Exception:  # noqa: BLE001 - defektes Bild nicht den ganzen Export kippen lassen
            return
        line(f"[{format_timecode(m.t)}]" + (f" {m.note}" if m.note else ""), 9)
        pdf.ln(2)

    line(f"Transkript: {data['source']}", 16, "B")
    pdf.ln(2)
    line(
        f"Laenge {format_timecode(data['duration_s'])}  |  Sprache {data['language']}  |  "
        f"Sprecher {data['num_speakers']}  |  Modell {data['model']} (WhisperX)",
        10,
    )
    pdf.ln(4)

    for i, p in enumerate(paragraphs):
        line(f"[{format_timecode(p['start'])}] {p['speaker']}:", 11, "B")
        line(p["text"], 11)
        pdf.ln(1)
        for m in by_para.get(i, []):
            put_image(m)
        pdf.ln(1)
    if not paragraphs:
        for m in sorted(marks, key=lambda m: m.t):
            put_image(m)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return out_path
