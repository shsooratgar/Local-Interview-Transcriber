#!/usr/bin/env python3
"""Compare two transcripts of the same audio and flag time windows where they
DISAGREE. Disagreement between two independent transcriptions is a strong signal
of a likely transcription error.

  - In production: A = noScribe transcript, B = our Whisper re-transcription.
  - For testing:   two Whisper models (e.g., turbo vs tiny).

    python src/diff_flag.py output/A.whisper.json output/B.tiny.json
"""
from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher
from pathlib import Path


def _norm(s):
    return re.sub(r"[^\w\s]", "", s.lower()).split()


def _words_with_time(transcript):
    """(start, word) for every word; fall back to segment start if no word times."""
    out = []
    for seg in transcript.get("segments", []):
        words = seg.get("words") or []
        if words:
            out += [(w["start"], w["word"]) for w in words if w.get("start") is not None]
        elif seg.get("start") is not None:
            out += [(seg["start"], tok) for tok in seg.get("text", "").split()]
    return out


def _text_in_window(words, lo, hi):
    return " ".join(w for (t, w) in words if lo <= t < hi).strip()


def diff_windows(a, b, window=8.0, threshold=0.75):
    wa, wb = _words_with_time(a), _words_with_time(b)
    if not wa and not wb:
        return []
    end = max(t for t, _ in (wa + wb)) + window
    flags, lo = [], 0.0
    while lo < end:
        hi = lo + window
        ta, tb = _text_in_window(wa, lo, hi), _text_in_window(wb, lo, hi)
        if ta or tb:
            ratio = SequenceMatcher(None, _norm(ta), _norm(tb)).ratio()
            if ratio < threshold:
                flags.append({"start": round(lo, 1), "end": round(hi, 1),
                              "similarity": round(ratio, 2), "text_a": ta, "text_b": tb})
        lo = hi
    return flags


def main():
    ap = argparse.ArgumentParser(description="Flag windows where two transcripts disagree.")
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--window", type=float, default=8.0)
    ap.add_argument("--threshold", type=float, default=0.75)
    args = ap.parse_args()

    a = json.loads(Path(args.a).read_text(encoding="utf-8"))
    b = json.loads(Path(args.b).read_text(encoding="utf-8"))
    flags = diff_windows(a, b, args.window, args.threshold)
    print(f"{len(flags)} disagreement window(s) (similarity < {args.threshold})\n")
    for f in flags[:40]:
        print(f"[{f['start']:.0f}-{f['end']:.0f}s] sim={f['similarity']}")
        print(f"   A: {f['text_a']}")
        print(f"   B: {f['text_b']}")


if __name__ == "__main__":
    main()
