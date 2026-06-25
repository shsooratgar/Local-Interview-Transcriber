#!/usr/bin/env python3
"""Load a "base" transcript (the document we annotate) from various formats into
one common structure:

    {"source": str, "format": str,
     "segments": [{"speaker": str|None, "start": float|None, "end": float|None,
                   "text": str, "interjection": bool}, ...]}

Supported: noScribe .docx / .ref.json (our test format) / .vtt / .srt / .txt.

noScribe .docx specifics (confirmed from real samples):
  - Each turn is a paragraph starting with "Speaker:" (names OR S01-style labels).
  - A short turn by another speaker can be inlined mid-turn as //Name: text//.
  - Pauses are marked (.) / (..) / (...) — preserved in text, never flagged.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# leading "Speaker:" at the start of a turn (name or S01-style, <=40 chars, no colon)
SPEAKER_RE = re.compile(r"^\s*([^:]{1,40}?):\s*(.*)$", re.S)
# inline interjection //Speaker: text //
INTERJECTION_RE = re.compile(r"//\s*([^:/]{1,40}?):\s*(.*?)\s*//", re.S)
# pause markers: (.) (..) (...) or timed (2.0)
_PAUSE_RE = re.compile(
    r"\(\s*\.+\s*\)"                                                    # (.) (..) (...)
    r"|\(\s*\d+(?:[.,]\d+)?\s*\)"                                       # (2.0) timed
    r"|\([^)]*[Pp]ause[^)]*\)"                                          # (14 Sekunden Pause) etc.
    r"|\b\d+\s+(?:seconds?|minutes?|Sekunden?|Minuten?)\s+[Pp]ause\b"  # bare written-out
)


def strip_pauses(text: str) -> str:
    """Remove pause markers for matching / LLM input (keeps wording intact)."""
    return re.sub(r"\s{2,}", " ", _PAUSE_RE.sub(" ", text)).strip()


def load_base(path) -> dict:
    p = Path(path)
    suffix, name = p.suffix.lower(), p.name.lower()
    if suffix == ".docx":
        segs, fmt = _from_docx(p), "noscribe_docx"
    elif name.endswith(".ref.json") or suffix == ".json":
        segs, fmt = _from_ref_json(p), "ref_json"
    elif suffix == ".vtt":
        segs, fmt = _from_vtt(p), "vtt"
    elif suffix == ".srt":
        segs, fmt = _from_srt(p), "srt"
    elif suffix in (".txt", ".text"):
        segs, fmt = _from_txt(p), "txt"
    else:
        raise ValueError(f"Unsupported transcript format: {suffix}")
    return {"source": str(p), "format": fmt, "segments": segs}


# ---------- noScribe .docx ----------

def _parse_turn(text: str) -> list[dict]:
    """Split one paragraph into ordered segments, handling //inline interjections//."""
    m = SPEAKER_RE.match(text)
    if not m:
        return [{"speaker": None, "text": text.strip(), "interjection": False}]
    main, rest = m.group(1).strip(), m.group(2)
    segs, pos = [], 0
    for it in INTERJECTION_RE.finditer(rest):
        before = rest[pos:it.start()].strip()
        if before:
            segs.append({"speaker": main, "text": before, "interjection": False})
        segs.append({"speaker": it.group(1).strip(), "text": it.group(2).strip(), "interjection": True})
        pos = it.end()
    tail = rest[pos:].strip()
    if tail:
        segs.append({"speaker": main, "text": tail, "interjection": False})
    return segs or [{"speaker": main, "text": "", "interjection": False}]


def _from_docx(path) -> list[dict]:
    from docx import Document  # python-docx
    doc = Document(str(path))
    segments = []
    for para in doc.paragraphs:           # body paragraphs only (table cells excluded)
        t = para.text.strip()
        if not t:
            continue
        for s in _parse_turn(t):
            segments.append({"speaker": s["speaker"], "start": None, "end": None,
                             "text": s["text"], "interjection": s["interjection"]})
    return segments


# ---------- other formats ----------

def _from_ref_json(p):
    data = json.loads(p.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else data.get("segments", [])
    return [{"speaker": r.get("speaker"), "start": r.get("start"), "end": r.get("end"),
             "text": (r.get("text") or "").strip(), "interjection": False} for r in rows]


def _ts_to_sec(ts):
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    h, m, s = (["0"] * (3 - len(parts)) + parts)[:3]
    return int(h) * 3600 + int(m) * 60 + float(s)


def _from_vtt(p):
    try:
        import webvtt
        out = []
        for c in webvtt.read(str(p)):
            text, spk = c.text.strip(), None
            mt = re.match(r"<v\s+([^>]+)>", text)
            if mt:
                spk = mt.group(1).strip()
                text = re.sub(r"<[^>]+>", "", text).strip()
            out.append({"speaker": spk, "start": _ts_to_sec(c.start),
                        "end": _ts_to_sec(c.end), "text": text, "interjection": False})
        return out
    except Exception:
        return _from_srt(p)


def _from_srt(p):
    out = []
    for b in re.split(r"\n\s*\n", p.read_text(encoding="utf-8").strip()):
        lines = [ln for ln in b.splitlines() if ln.strip()]
        if not lines:
            continue
        ts_line = next((ln for ln in lines if "-->" in ln), None)
        start = end = None
        if ts_line:
            a, _, c = ts_line.partition("-->")
            start, end = _ts_to_sec(a.strip().split()[0]), _ts_to_sec(c.strip().split()[0])
        text = " ".join(ln for ln in lines if "-->" not in ln and not ln.strip().isdigit()).strip()
        spk = None
        mm = re.match(r"\s*([A-Za-z0-9 _.\-]{1,40}?):\s*(.*)", text)
        if mm:
            spk, text = mm.group(1).strip(), mm.group(2).strip()
        if text:
            out.append({"speaker": spk, "start": start, "end": end, "text": text, "interjection": False})
    return out


def _from_txt(p):
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        spk = None
        mm = re.match(r"\[([^\]]+)\]\s*(.*)", ln) or re.match(r"([A-Za-z0-9 _.\-]{1,40}?):\s+(.*)", ln)
        if mm:
            spk, ln = mm.group(1).strip(), mm.group(2).strip()
        out.append({"speaker": spk, "start": None, "end": None, "text": ln, "interjection": False})
    return out


if __name__ == "__main__":
    import sys
    base = load_base(sys.argv[1])
    print(f"format={base['format']}  segments={len(base['segments'])}")
    for s in base["segments"][:12]:
        tag = " (interj)" if s.get("interjection") else ""
        print(f"  {s['speaker']!s:>10}{tag}: {s['text'][:70]}")
