"""Export des Transkripts als Markdown (Primaerformat, FR-7) und optional PDF (FR-8).

Zusaetzlich wird eine maschinenlesbare ``transcript.json`` geschrieben (FR-12) – die
Eingabe fuer die nachgelagerte Review-/Bild-Annotations-Schicht (PRD §13).
"""

from __future__ import annotations

import json
from pathlib import Path

from audioscribe.models import TranscriptResult, format_timecode

# Unicode-faehige TTF-Fonts (fuer deutsche Umlaute im PDF). (regular, bold); erster Treffer gewinnt.
_FONT_CANDIDATES = (
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
)


def render_markdown(result: TranscriptResult) -> str:
    """Erzeugt das Markdown-Dokument: Metadaten-Kopf + zeitgestempelte Sprecherabsaetze."""
    m = result.meta
    lines = [
        f"# Transkript: {m.source.name}",
        "",
        "| | |",
        "|---|---|",
        f"| Datei | {m.source.name} |",
        f"| Laenge | {format_timecode(m.duration_s)} |",
        f"| Sprache | {m.language} |",
        f"| Sprecher | {m.num_speakers} |",
        f"| Modell | {m.model} (WhisperX) |",
    ]
    if m.created:
        lines.append(f"| Erstellt | {m.created} |")
    lines += ["", "---", ""]

    for p in result.paragraphs:
        lines.append(f"**[{format_timecode(p.start)}] {p.speaker}:** {p.text}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_markdown(result: TranscriptResult, out_dir: Path) -> Path:
    """Schreibt ``<out_dir>/<stem>/transkript.md`` und liefert den Pfad."""
    stem = result.meta.source.stem
    target_dir = Path(out_dir) / stem
    target_dir.mkdir(parents=True, exist_ok=True)
    out_md = target_dir / "transkript.md"
    out_md.write_text(render_markdown(result), encoding="utf-8")
    return out_md


# Schema-Version der transcript.json; bei inkompatiblen Aenderungen hochzaehlen.
TRANSCRIPT_JSON_VERSION = 1


def transcript_to_dict(result: TranscriptResult) -> dict:
    """Maschinenlesbare Repraesentation des Transkripts fuer die Review-Schicht (FR-12).

    Enthaelt die Absaetze (Einfuege-Einheit fuer Bild-Markierungen) samt Zeitstempeln
    sowie den **absoluten Pfad zum Original-Medium** – das extrahierte WAV enthaelt
    keine Bilder, die Review-UI braucht das Originalvideo (PRD §13.8).
    """
    m = result.meta
    return {
        "version": TRANSCRIPT_JSON_VERSION,
        "source": m.source.name,
        "source_path": str(Path(m.source).resolve()),
        "duration_s": m.duration_s,
        "language": m.language,
        "num_speakers": m.num_speakers,
        "model": m.model,
        "created": m.created,
        "paragraphs": [
            {
                "index": i,
                "start": p.start,
                "end": p.end,
                "speaker": p.speaker,
                "text": p.text,
            }
            for i, p in enumerate(result.paragraphs)
        ],
    }


def write_transcript_json(result: TranscriptResult, out_dir: Path) -> Path:
    """Schreibt ``<out_dir>/<stem>/transcript.json`` und liefert den Pfad (FR-12)."""
    stem = result.meta.source.stem
    target_dir = Path(out_dir) / stem
    target_dir.mkdir(parents=True, exist_ok=True)
    out_json = target_dir / "transcript.json"
    out_json.write_text(
        json.dumps(transcript_to_dict(result), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return out_json


def _unicode_fonts() -> tuple[str, str] | None:
    """Liefert (regular, bold) TTF-Pfade fuer ein Unicode-faehiges PDF oder ``None``."""
    for reg, bold in _FONT_CANDIDATES:
        if Path(reg).exists():
            return reg, (bold if Path(bold).exists() else reg)
    # matplotlib (Transitiv-Dep des ML-Stacks) buendelt DejaVuSans -> Umlaute ohne Extra-Download.
    try:
        import matplotlib

        ttf = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        reg, bold = ttf / "DejaVuSans.ttf", ttf / "DejaVuSans-Bold.ttf"
        if reg.exists():
            return str(reg), str(bold if bold.exists() else reg)
    except Exception:  # noqa: BLE001
        pass
    return None


def write_pdf(result: TranscriptResult, out_path: Path) -> Path:
    """Rendert das Transkript als einfaches, lesbares PDF (FR-8).

    Nutzt fpdf2 rein in Python. Findet sich ein Unicode-TTF, werden deutsche
    Umlaute korrekt dargestellt; andernfalls Fallback auf Latin-1 (Ersatzzeichen).
    """
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    m = result.meta
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    fonts = _unicode_fonts()
    if fonts:
        reg, bold_path = fonts
        pdf.add_font("body", "", reg)
        pdf.add_font("body", "B", bold_path)
        family = "body"
        encode = lambda s: s  # noqa: E731
    else:
        family = "Helvetica"
        encode = lambda s: s.encode("latin-1", "replace").decode("latin-1")  # noqa: E731

    def line(text: str, size: int, style: str = "") -> None:
        pdf.set_font(family, style, size)
        # new_x/new_y: Cursor zurueck an den linken Rand, damit die naechste Zeile
        # die volle Breite bekommt (sonst FPDFException "not enough horizontal space").
        pdf.multi_cell(0, size * 0.5 + 1, encode(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    line(f"Transkript: {m.source.name}", 16, "B")
    pdf.ln(2)
    line(
        f"Laenge {format_timecode(m.duration_s)}  |  Sprache {m.language}  |  "
        f"Sprecher {m.num_speakers}  |  Modell {m.model} (WhisperX)",
        10,
    )
    pdf.ln(4)

    for p in result.paragraphs:
        line(f"[{format_timecode(p.start)}] {p.speaker}:", 11, "B")
        line(p.text, 11)
        pdf.ln(2)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return out_path
