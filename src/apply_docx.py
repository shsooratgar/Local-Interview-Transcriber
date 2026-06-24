#!/usr/bin/env python3
"""Apply accepted review decisions to a COPY of the base .docx, producing a
corrected document. The original is never modified.

decisions map (from the viewer): { "c<i>": {"s": "keep"|"drop"|"", "e": "<edit>"}, "o<i>": {...} }
where c<i> indexes review["disagreements"][i] and o<i> indexes review["omissions"][i].

v1 scope:
  - corrections  -> replace the first occurrence of base_text with your text
  - omissions    -> best-effort insert after the preceding-context anchor
Anything that can't be located is reported as 'skipped' (so you can do it by hand).
"""
from __future__ import annotations

import json
from pathlib import Path

from docx import Document


def _final_text(flag, dec):
    edit = (dec.get("e") or "").strip()
    return edit or (flag.get("llm") or {}).get("correction") or flag.get("audio_text") or ""


def _rewrite(p, new_full):
    """Replace a paragraph's text, keeping its style (collapses runs)."""
    if p.runs:
        p.runs[0].text = new_full
        for r in p.runs[1:]:
            r.text = ""
    else:
        p.add_run(new_full)


def _dedup_boundary(before, new, after):
    """Drop a boundary word of `new` if it just repeats the adjacent transcript
    word, so replacing 'reinforced film' with 'reinforcement learning' next to an
    existing 'learning' doesn't produce '...learning learning'."""
    nw, bw, aw = new.split(), before.split(), after.split()
    if nw and aw and nw[-1].lower().strip(".,!?") == aw[0].lower().strip(".,!?"):
        nw = nw[:-1]
    if nw and bw and nw[0].lower().strip(".,!?") == bw[-1].lower().strip(".,!?"):
        nw = nw[1:]
    return " ".join(nw)


def _replace_first(paragraphs, old, new):
    if not old:
        return False
    for p in paragraphs:
        idx = p.text.find(old)
        if idx == -1:
            continue
        full = p.text
        before, after = full[:idx], full[idx + len(old):]
        _rewrite(p, before + _dedup_boundary(before, new, after) + after)
        return True
    return False


def _insert_after_anchor(paragraphs, before_ctx, text):
    anchor = " ".join((before_ctx or "").split()[-4:]).strip()
    if not anchor:
        return False
    for p in paragraphs:
        if anchor in p.text:
            _rewrite(p, p.text.replace(anchor, f"{anchor} {text}", 1))
            return True
    return False


def apply_decisions(base_docx, review, decisions, out_path):
    doc = Document(str(base_docx))
    paras = doc.paragraphs
    applied, skipped = 0, 0

    for i, d in enumerate(review.get("disagreements", [])):
        dec = decisions.get(f"c{i}")
        if not dec or dec.get("s") != "keep":
            continue
        new = _final_text(d, dec)
        if new and _replace_first(paras, d.get("base_text", ""), new):
            applied += 1
        else:
            skipped += 1

    for i, o in enumerate(review.get("omissions", [])):
        dec = decisions.get(f"o{i}")
        if not dec or dec.get("s") != "keep":
            continue
        text = (dec.get("e") or "").strip() or o.get("audio_text", "")
        if text and _insert_after_anchor(paras, (o.get("base_ctx") or {}).get("before", ""), text):
            applied += 1
        else:
            skipped += 1

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return {"applied": applied, "skipped": skipped, "out": str(out_path)}


if __name__ == "__main__":
    import sys
    review = json.loads(Path(sys.argv[2]).read_text())
    decisions = json.loads(Path(sys.argv[3]).read_text())
    print(apply_decisions(sys.argv[1], review, decisions, sys.argv[4]))
