#!/usr/bin/env python3
"""Load a "base" transcript (the document we annotate) from various formats into
one common structure:

    {"source": str, "format": str,
     "segments": [{"speaker": str|None, "start": float|None, "end": float|None, "text": str}, ...]}

Supported now: .ref.json (our test format) / .vtt / .srt / .txt.
noScribe .html is added once we confirm its exact layout from a real sample.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def load_base(path) -> dict:
    p = Path(path)
    suffix, name = p.suffix.lower(), p.name.lower()
    if name.endswith(".ref.json") or suffix == ".json":
        segs, fmt = _from_ref_json(p), "ref_json"
    elif suffix == ".vtt":
        segs, fmt = _from_vtt(p), "vtt"
    elif suffix == ".srt":
        segs, fmt = _from_srt(p), "srt"
    elif suffix in (".txt", ".text"):
        segs, fmt = _from_txt(p), "txt"
    elif suffix in (".html", ".htm"):
        raise NotImplementedError(
            "noScribe .html parsing is added once we confirm its layout from a real sample.")
    else:
        raise ValueError(f"Unsupported transcript format: {suffix}")
    return {"source": str(p), "format": fmt, "segments": segs}


def _from_ref_json(p):
    data = json.loads(p.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else data.get("segments", [])
    return [{"speaker": r.get("speaker"), "start": r.get("start"),
             "end": r.get("end"), "text": (r.get("text") or "").strip()} for r in rows]


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
                        "end": _ts_to_sec(c.end), "text": text})
        return out
    except Exception:
        return _from_srt(p)  # generic block fallback


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
        m = re.match(r"\s*([A-Za-z0-9 _.\-]{1,40}?):\s*(.*)", text)
        if m:
            spk, text = m.group(1).strip(), m.group(2).strip()
        if text:
            out.append({"speaker": spk, "start": start, "end": end, "text": text})
    return out


def _from_txt(p):
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        spk = None
        m = re.match(r"\[([^\]]+)\]\s*(.*)", ln) or re.match(r"([A-Za-z0-9 _.\-]{1,40}?):\s+(.*)", ln)
        if m:
            spk, ln = m.group(1).strip(), m.group(2).strip()
        out.append({"speaker": spk, "start": None, "end": None, "text": ln})
    return out


if __name__ == "__main__":
    import sys
    base = load_base(sys.argv[1])
    print(f"format={base['format']}  segments={len(base['segments'])}")
    for s in base["segments"][:5]:
        print(s)
