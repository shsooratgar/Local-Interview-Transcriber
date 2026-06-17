#!/usr/bin/env python3
"""Flag suspect spans in a normalized Whisper transcript (from transcribe.py).

Signals used:
  - low per-word probability  -> likely mis-heard word(s)
  - high no_speech_prob + low avg_logprob on a segment -> possible hallucination

Usage:
    python src/flag.py output/interview01.whisper.json
    python src/flag.py output/interview01.whisper.json --threshold 0.5
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import load_config


def find_suspects(transcript, threshold=0.55, gap=0.5, context_seconds=20):
    segments = transcript["segments"]
    suspects = []

    # 1) low-confidence words, merged into spans when they are close together
    spans = []
    for seg in segments:
        for w in seg["words"]:
            p = w.get("prob")
            if p is None or p >= threshold or not w["word"].strip():
                continue
            if (spans and w["start"] is not None and spans[-1]["end"] is not None
                    and w["start"] - spans[-1]["end"] <= gap):
                spans[-1]["end"] = w["end"]
                spans[-1]["words"].append(w["word"])
                spans[-1]["min_prob"] = min(spans[-1]["min_prob"], p)
            else:
                spans.append({"start": w["start"], "end": w["end"],
                              "words": [w["word"]], "min_prob": p,
                              "reason": "low_confidence"})
    for sp in spans:
        suspects.append({
            "start": sp["start"], "end": sp["end"],
            "text": "".join(sp["words"]).strip(),
            "min_prob": round(sp["min_prob"], 3),
            "reason": "low_confidence",
            "context": _context(segments, sp["start"], sp["end"], context_seconds),
        })

    # 2) hallucination-ish segments
    for seg in segments:
        nsp = seg.get("no_speech_prob") or 0.0
        alp = seg.get("avg_logprob")
        if nsp > 0.6 and alp is not None and alp < -1.0 and seg["text"]:
            suspects.append({
                "start": seg["start"], "end": seg["end"],
                "text": seg["text"], "min_prob": None,
                "reason": "possible_hallucination",
                "context": _context(segments, seg["start"], seg["end"], context_seconds),
            })

    suspects.sort(key=lambda s: s["start"] if s["start"] is not None else 0.0)
    return suspects


def _context(segments, start, end, window):
    if start is None or end is None:
        return ""
    lo, hi = start - window, end + window
    parts = [s["text"] for s in segments
             if s["start"] is not None and s["end"] is not None
             and s["end"] >= lo and s["start"] <= hi]
    return " ".join(parts).strip()


def fmt_ts(t):
    if t is None:
        return "??:??"
    m, s = divmod(int(t), 60)
    return f"{m:02d}:{s:02d}"


def main():
    ap = argparse.ArgumentParser(description="Flag suspect spans in a transcript.")
    ap.add_argument("whisper_json")
    ap.add_argument("--threshold", type=float, default=None)
    args = ap.parse_args()

    cfg = load_config()
    thr = args.threshold if args.threshold is not None else cfg["low_confidence_threshold"]
    transcript = json.loads(Path(args.whisper_json).read_text())
    suspects = find_suspects(transcript, thr,
                             cfg["min_segment_gap_seconds"], cfg["context_window_seconds"])

    print(f"{len(suspects)} suspect span(s) at threshold {thr}\n")
    for sp in suspects:
        mp = f"{sp['min_prob']:.2f}" if sp.get("min_prob") is not None else "  --"
        print(f"[{fmt_ts(sp['start'])}-{fmt_ts(sp['end'])}] p={mp} "
              f"{sp['reason']:>20} | {sp['text']!r}")


if __name__ == "__main__":
    main()
