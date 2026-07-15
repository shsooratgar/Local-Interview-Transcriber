#!/usr/bin/env python3
"""Apply accepted review decisions to a COPY of the base .docx, producing a
corrected document. The original is never modified.

decisions map (from the viewer): { "<key>": {"s": "keep"|"drop"|"", "e": "<edit>"} }
where  c<i> -> review["disagreements"][i]
       r<i> -> review["recovered"][i]   (replace the dropped remnant)
       o<i> -> review["omissions"][i]   (insert the missing passage IN PLACE)
       b<i> -> review["base_only"][i]   (keep = remove the never-heard passage)

Flag spans are punctuation-stripped word sequences, so spans are located with a
word-bounded regex that tolerates any punctuation/pause markers between words
(e.g. span "it s part" matches "it's part"). Replacements are targeted to the
exact paragraph (via each flag's segment index), falling back to a first-match
search. Anything that can't be located is reported as 'skipped' so you can do
it by hand.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from docx import Document
from docx.shared import RGBColor

from transcript_io import _parse_turn


def _span_regex(span_text):
    """Find a token span inside RAW paragraph text: the words in order, any
    punctuation/whitespace between them, and word boundaries at both ends —
    so 'laps' never matches inside 'collapses'."""
    toks = re.findall(r"\w+", span_text or "", re.UNICODE)
    if not toks:
        return None
    return re.compile(r"(?<!\w)" + r"\W+".join(re.escape(t) for t in toks) + r"(?!\w)")


def _accepted(dec):
    """A row is applied if you typed an override (mode 'txt') or clicked keep."""
    return bool((dec.get("m") == "txt" and (dec.get("e") or "").strip()) or dec.get("s") == "keep")


def _final_text(flag, dec):
    # your typed override wins only when it's the active choice (mode 'txt')
    if dec.get("m") == "txt":
        e = (dec.get("e") or "").strip()
        if e:
            return e
    return (flag.get("llm") or {}).get("correction") or flag.get("audio_text") or ""


def _rewrite(p, new_full):
    """Replace a paragraph's text, keeping its style (collapses runs)."""
    if p.runs:
        p.runs[0].text = new_full
        for r in p.runs[1:]:
            r.text = ""
    else:
        p.add_run(new_full)


def _dedup_boundary(before, new, after, max_overlap=4):
    """Drop boundary words of `new` that just repeat the adjacent transcript words.
    Handles MULTI-word overlaps: alignment fragments can end a suggestion with the
    same 2-3 words the paragraph continues with; naive insertion would duplicate
    them ("gives it action" + "it action We could…")."""
    def norm(w):
        return w.lower().strip(".,!?;:")

    nw, bw, aw = new.split(), before.split(), after.split()
    for k in range(min(max_overlap, len(nw), len(aw)), 0, -1):
        if [norm(w) for w in nw[-k:]] == [norm(w) for w in aw[:k]]:
            nw = nw[:-k]
            break
    for k in range(min(max_overlap, len(nw), len(bw)), 0, -1):
        if [norm(w) for w in nw[:k]] == [norm(w) for w in bw[-k:]]:
            nw = nw[k:]
            break
    return " ".join(nw)


def _tidy(text):
    return re.sub(r"\s{2,}", " ", text).strip()


def _replace_in_para(p, old, new):
    rx = _span_regex(old)
    if not rx:
        return False
    m = rx.search(p.text)
    if not m:
        return False
    before, after = p.text[:m.start()], p.text[m.end():]
    body = _dedup_boundary(before, new, after)
    if not body:  # deletion: swallow the orphaned punctuation at the seam
        after = re.sub(r"^\s*[,.;:!?]+", "", after)
    _rewrite(p, _tidy(before + body + after))
    return True


def _insert_in_para(p, text, ctx):
    """Insert `text` where the alignment located the gap — right before the
    after-context anchor (or after the before-anchor); appends at the end only
    when neither anchor can be found in this paragraph."""
    full = p.text
    pos = None
    rx = _span_regex((ctx or {}).get("after"))
    m = rx.search(full) if rx else None
    if m:
        pos = m.start()
    else:
        rx = _span_regex((ctx or {}).get("before"))
        m = rx.search(full) if rx else None
        if m:
            pos = m.end()
    if pos is None:
        _rewrite(p, _tidy(full + " " + text))
        return
    body = _dedup_boundary(full[:pos], text, full[pos:])
    _rewrite(p, _tidy(full[:pos].rstrip() + " " + body + " " + full[pos:].lstrip()))


# ---------- change-tracked rendering (the "changes" copy) ----------

_ADD_COLOR = RGBColor(0x13, 0x7A, 0x3E)  # green, same as the review cockpit
_DEL_COLOR = RGBColor(0x99, 0x99, 0x99)  # grey + strikethrough


def _rewrite_marked(p, pieces):
    """Rebuild a paragraph from (text, kind) pieces; kind: plain | del | add."""
    for r in p.runs:
        r.text = ""
    for text, kind in pieces:
        if not text:
            continue
        r = p.add_run(text)
        if kind == "del":
            r.font.strike = True
            r.font.color.rgb = _DEL_COLOR
        elif kind == "add":
            r.font.color.rgb = _ADD_COLOR
            r.font.bold = True


class _Marker:
    """Collects strike/green edits per paragraph and renders each paragraph ONCE
    at the end — several edits in the same turn must not wipe each other."""

    def __init__(self):
        self._state = {}  # id(paragraph xml element) -> (paragraph, pieces)

    def _pieces(self, p):
        key = id(p._p)
        if key not in self._state:
            self._state[key] = (p, [[p.text, "plain"]])
        return self._state[key][1]

    def replace(self, p, old, new):
        rx = _span_regex(old)
        if not rx:
            return False
        pieces = self._pieces(p)
        for idx, (text, kind) in enumerate(pieces):
            if kind != "plain":
                continue
            m = rx.search(text)
            if not m:
                continue
            before, after = text[:m.start()], text[m.end():]
            body = _dedup_boundary(before, new, after)
            repl = [[before, "plain"], [m.group(0), "del"]]
            if body:
                repl += [[" ", "plain"], [body, "add"]]
            repl.append([after, "plain"])
            pieces[idx:idx + 1] = repl
            return True
        return False

    def insert(self, p, text, ctx):
        pieces = self._pieces(p)
        for rx, at_start in ((_span_regex((ctx or {}).get("after")), True),
                             (_span_regex((ctx or {}).get("before")), False)):
            if not rx:
                continue
            for idx, (ptext, kind) in enumerate(pieces):
                if kind != "plain":
                    continue
                m = rx.search(ptext)
                if not m:
                    continue
                pos = m.start() if at_start else m.end()
                body = _dedup_boundary(ptext[:pos], text, ptext[pos:])
                repl = [[ptext[:pos].rstrip() + " ", "plain"], [body, "add"],
                        [" " + ptext[pos:].lstrip(), "plain"]]
                pieces[idx:idx + 1] = repl
                return True
        pieces += [[" ", "plain"], [text, "add"]]  # fallback: end of the turn
        return True

    def render(self):
        for p, pieces in self._state.values():
            _rewrite_marked(p, pieces)


def _seg_to_para(doc):
    """Map each flattened base-segment index to its paragraph (same order as
    transcript_io parses the docx) so replacements hit the right spot."""
    mapping = []
    for p in doc.paragraphs:
        t = p.text.strip()
        if not t:
            continue
        for _ in _parse_turn(t):
            mapping.append(p)
    return mapping


# ---------- header table on the final document ----------

# Rows we CREATE and fill. "Key quotes" was dropped on request (2026-07-16):
# we no longer add or fill it.
_HEADER_ROWS = ["Meeting title", "Date", "Duration", "Participants",
                "Summary", "Reflections"]

# Labels we RECOGNIZE when deciding "is this the meta table?" — a superset, so a
# transcript whose template still has a Key quotes row is reused (and that row
# left untouched) instead of getting a second table added above it.
_KNOWN_LABELS = _HEADER_ROWS + ["Key quotes"]


def _fmt_duration(sec):
    if not sec:
        return ""
    sec = int(sec)
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d} h" if h else f"{m}:{s:02d} min"


def _title_date_from_name(audio_path):
    """'250131_Team Meeting.m4a' -> ('Team Meeting', '31.01.2025')."""
    stem = Path(audio_path).stem
    m = re.match(r"^(\d{2})(\d{2})(\d{2})[ _-]+(.*)$", stem)
    if m:
        yy, mm, dd, rest = m.groups()
        try:
            from datetime import date
            date(2000 + int(yy), int(mm), int(dd))  # sanity: YYMMDD only
            return rest.strip() or stem, f"{dd}.{mm}.20{yy}"
        except ValueError:
            pass
    return stem, ""


def _set_cell_lines(cell, lines):
    """Fill a cell with one paragraph per line (only called on empty cells)."""
    cell.text = ""
    cell.paragraphs[0].text = lines[0] if lines else ""
    for ln in lines[1:]:
        cell.add_paragraph(ln)


def _ensure_header_table(doc, review):
    """Make sure the document starts with the meta table (Meeting title / Date /
    Duration / Participants / Summary / Reflections) and fill in
    what we know — ONLY into empty cells; existing entries are never touched."""
    labels_lc = [h.lower() for h in _KNOWN_LABELS]

    def label_key(text):
        t = (text or "").strip().lower().rstrip(":")
        for i, lab in enumerate(labels_lc):
            if t.startswith(lab) or lab.startswith(t) and t:
                return _KNOWN_LABELS[i]
        return None

    table = None
    if doc.tables:
        t0 = doc.tables[0]
        if len(t0.columns) >= 2 and sum(1 for r in t0.rows if label_key(r.cells[0].text)) >= 2:
            table = t0
    if table is None:
        table = doc.add_table(rows=0, cols=2)
        try:
            table.style = "Table Grid"
        except Exception:
            pass
        doc.element.body.insert(0, table._element)  # move to the very top

    rows = {}
    for r in table.rows:
        k = label_key(r.cells[0].text)
        if k and k not in rows:
            rows[k] = r
    for h in _HEADER_ROWS:  # add any missing rows (also builds the fresh table)
        if h not in rows:
            r = table.add_row()
            r.cells[0].text = h
            rows[h] = r

    title, date = _title_date_from_name(review.get("audio", ""))
    summ = review.get("summary") or {}
    values = {
        "Meeting title": [title] if title else [],
        "Date": [date] if date else [],
        "Duration": [_fmt_duration(review.get("duration_seconds"))],
        "Participants": [", ".join(review.get("participants") or [])],
        "Summary": ([summ.get("summary")] if summ.get("summary") else [])
                   + [f"• {t}" for t in (summ.get("topics") or [])],
    }
    for key, lines in values.items():
        lines = [ln for ln in lines if ln]
        cell = rows[key].cells[-1]
        if lines and not cell.text.strip():
            _set_cell_lines(cell, lines)


def _apply_to_doc(base_docx, review, decisions, out_path, mark=False):
    """One pass over the decisions. mark=False: really apply (final document).
    mark=True: change-tracked copy — removals struck grey, additions green."""
    doc = Document(str(base_docx))
    paras = doc.paragraphs
    s2p = _seg_to_para(doc)
    marker = _Marker() if mark else None
    counts = {"applied": 0, "skipped": 0, "skipped_rows": []}

    def rep_in(p, old, new):
        return marker.replace(p, old, new) if mark else _replace_in_para(p, old, new)

    def rep_anywhere(old, new, seg):
        if seg is not None and seg < len(s2p) and rep_in(s2p[seg], old, new):
            return True
        return any(rep_in(p, old, new) for p in paras)

    def note_skip(key, flag):
        # tell the reviewer exactly WHICH row to fix by hand, not just how many
        counts["skipped"] += 1
        counts["skipped_rows"].append({"key": key, "time": flag.get("start")})

    def do_replace(flag, dec, key):
        new = _final_text(flag, dec)
        if new and rep_anywhere(flag.get("base_text", ""), new, flag.get("seg")):
            counts["applied"] += 1
        else:
            note_skip(key, flag)

    for i, d in enumerate(review.get("disagreements", [])):
        dec = decisions.get(f"c{i}")
        if dec and _accepted(dec):
            do_replace(d, dec, f"c{i}")

    for i, d in enumerate(review.get("recovered", [])):
        dec = decisions.get(f"r{i}")
        if dec and _accepted(dec):
            do_replace(d, dec, f"r{i}")

    for i, o in enumerate(review.get("omissions", [])):
        dec = decisions.get(f"o{i}")
        if not dec or not _accepted(dec):
            continue
        text = o.get("audio_text", "")
        if dec.get("m") == "txt" and (dec.get("e") or "").strip():
            text = dec["e"].strip()
        seg = o.get("seg")
        if text and seg is not None and seg < len(s2p):
            if mark:
                marker.insert(s2p[seg], text, o.get("base_ctx"))
            else:
                _insert_in_para(s2p[seg], text, o.get("base_ctx"))
            counts["applied"] += 1
        else:
            note_skip(f"o{i}", o)

    # base_only: passage never heard in the audio — keep = remove it (or replace
    # with your typed override). Empty replacement is intentional here.
    for i, d in enumerate(review.get("base_only", [])):
        dec = decisions.get(f"b{i}")
        if not dec or not _accepted(dec):
            continue
        new = dec["e"].strip() if (dec.get("m") == "txt" and (dec.get("e") or "").strip()) else ""
        if rep_anywhere(d.get("base_text", ""), new, d.get("seg")):
            counts["applied"] += 1
        else:
            note_skip(f"b{i}", d)

    if mark:
        marker.render()
    else:
        try:
            _ensure_header_table(doc, review)
            counts["header"] = "ok"
        except Exception as e:  # noqa: BLE001 — an odd table must never break Apply
            counts["header"] = f"skipped ({e})"

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return {**counts, "out": str(out_path)}


def apply_decisions(base_docx, review, decisions, out_path, changes_path=None):
    """Write the corrected document; optionally also a change-tracked copy
    (struck-through removals, green additions) next to it."""
    res = _apply_to_doc(base_docx, review, decisions, out_path, mark=False)
    if changes_path:
        try:
            _apply_to_doc(base_docx, review, decisions, changes_path, mark=True)
            res["changes"] = str(changes_path)
        except Exception as e:  # noqa: BLE001 — the marked copy must never block Apply
            res["changes"] = f"failed ({e})"
    return res


if __name__ == "__main__":
    import sys
    review = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    decisions = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
    print(apply_decisions(sys.argv[1], review, decisions, sys.argv[4]))
