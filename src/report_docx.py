#!/usr/bin/env python3
"""Write an annotated .docx report from an Option-A review result.

We only ADD to the document; the original transcript text and table are left
intact:
  - an 'LLM Summary' row is appended to the top table (existing rows untouched)
  - a clearly-labelled review section is appended at the end: overview, a clean
    suggested-corrections table, possible omissions, and overlaps to verify.
"""
from __future__ import annotations

from pathlib import Path

from docx import Document


def _mmss(s):
    if s is None:
        return "—"
    s = int(s)
    return f"{s // 60:02d}:{s % 60:02d}"


def _fill_cell_bullets(cell, items):
    cell.text = ""
    cell.paragraphs[0].text = ("• " + items[0]) if items else "(none)"
    for it in items[1:]:
        cell.add_paragraph("• " + it)


def _add_summary_row(doc, topics):
    if not doc.tables:
        doc.add_heading("LLM Summary", level=2)
        for t in topics:
            doc.add_paragraph("• " + t)
        return
    table = doc.tables[0]
    row = table.add_row()
    row.cells[0].text = "LLM Summary"
    _fill_cell_bullets(row.cells[min(1, len(row.cells) - 1)], topics)


def _grid(doc, headers, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    try:
        t.style = "Table Grid"
    except Exception:
        pass
    for i, h in enumerate(headers):
        cell = t.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(h)
        run.bold = True
    return t


def write_docx_report(base_docx, review, out_path):
    doc = Document(str(base_docx))
    summary = review.get("summary", {}) or {}
    _add_summary_row(doc, summary.get("topics", []))

    doc.add_page_break()
    doc.add_heading("LLM review — automatic suggestions, please verify", level=1)
    if summary.get("summary"):
        doc.add_paragraph(summary["summary"])
    doc.add_paragraph(f"(transcript/audio match coverage: {review.get('match_coverage', '?')}. "
                      f"Times refer to the audio; use the .html viewer to hear each one.)")

    doc.add_heading("Suggested corrections", level=2)
    corr = review.get("disagreements", [])
    if corr:
        t = _grid(doc, ["Time", "Speaker", "In transcript", "Suggested (from audio)"])
        for d in corr:
            c = t.add_row().cells
            c[0].text = _mmss(d.get("start"))
            c[1].text = str(d.get("speaker") or "")
            c[2].text = d.get("base_text", "")
            c[3].text = (d.get("llm", {}).get("correction") or d.get("audio_text", ""))
    else:
        doc.add_paragraph("None found.")

    doc.add_heading("Recovered passages (transcript dropped these — often another speaker)", level=2)
    rec = review.get("recovered", [])
    if rec:
        t = _grid(doc, ["Time", "Speaker", "In transcript", "Recovered (from audio)", "Other speaker?"])
        for d in rec:
            c = t.add_row().cells
            c[0].text = _mmss(d.get("start"))
            c[1].text = str(d.get("speaker") or "")
            c[2].text = d.get("base_text", "")
            c[3].text = (d.get("llm", {}).get("correction") or d.get("audio_text", ""))
            c[4].text = "yes" if d.get("other_speaker") else ""
    else:
        doc.add_paragraph("None found.")

    doc.add_heading("Possible omissions (heard in audio, missing from transcript)", level=2)
    oms = review.get("omissions", [])
    if oms:
        t = _grid(doc, ["Time", "Heard in audio"])
        for o in oms:
            c = t.add_row().cells
            c[0].text = _mmss(o.get("start"))
            c[1].text = o.get("audio_text", "")
    else:
        doc.add_paragraph("None found.")

    doc.add_heading("Overlapping speech to verify (//…// in the transcript)", level=2)
    ovs = review.get("overlaps", [])
    if ovs:
        for o in ovs[:60]:
            doc.add_paragraph(f"• [{o.get('speaker')}] {o.get('text', '')}")
    else:
        doc.add_paragraph("None marked.")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    return out


if __name__ == "__main__":
    import json
    import sys
    review = json.loads(Path(sys.argv[2]).read_text())
    print("saved ->", write_docx_report(sys.argv[1], review, sys.argv[3]))
