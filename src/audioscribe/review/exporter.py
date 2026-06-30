"""Export-Orchestrierung: transcript.json + marks.json -> annotiertes Markdown/PDF (FR-18).

Schreibt bewusst eigene Dateien (``transkript.annotiert.md`` / ``.pdf``) und laesst das
handeditierbare ``transkript.md`` unberuehrt – so kann die Transkription jederzeit neu
laufen, ohne die Annotation zu verlieren (PRD §13, NFR-6).
"""

from __future__ import annotations

import json
from pathlib import Path

from audioscribe.review.marks import load_marks
from audioscribe.review.merge import render_markdown_with_marks


def _load_transcript(out_dir: Path) -> dict:
    tj = out_dir / "transcript.json"
    if not tj.exists():
        raise FileNotFoundError(
            f"transcript.json nicht gefunden in {out_dir}. "
            "Zuerst 'audioscribe run <video>' ausfuehren."
        )
    return json.loads(tj.read_text(encoding="utf-8"))


def export_annotated(out_dir: str | Path, *, make_pdf: bool = False) -> Path:
    """Erzeugt ``transkript.annotiert.md`` (+ optional PDF) und liefert den Markdown-Pfad."""
    out_dir = Path(out_dir)
    data = _load_transcript(out_dir)
    marks = load_marks(out_dir)

    out_md = out_dir / "transkript.annotiert.md"
    out_md.write_text(render_markdown_with_marks(data, marks), encoding="utf-8")

    if make_pdf:
        from audioscribe.review.merge import write_annotated_pdf

        write_annotated_pdf(data, marks, out_dir / "transkript.annotiert.pdf", base_dir=out_dir)

    return out_md
