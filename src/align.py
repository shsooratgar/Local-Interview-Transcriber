#!/usr/bin/env python3
"""Align a base transcript (e.g. noScribe) with our Whisper re-transcription by
TEXT — no timestamps needed in the base. Surfaces:

  - disagreement flags : base says X, audio says Y  -> likely mis-hearing
  - omission flags     : audio has a chunk the base lacks -> likely dropped passage
  - base_only flags    : base has a chunk the audio lacks -> noScribe extra / our miss

and carries per-word confidence from the audio onto the base words. The
match-coverage metric also tells us how independent our pass is from noScribe
(too-high coverage would mean the two passes are near-identical and the
disagreement signal is weak).

    python src/align.py data/testsets/sample_transcript.docx output/sample_audio.whisper.json
"""
from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

from transcript_io import load_base, strip_pauses

_WORD = re.compile(r"\w+", re.UNICODE)


def _tokens(text):
    return [(m.group(0).lower(), m.group(0)) for m in _WORD.finditer(text)]


def words_from_whisper(transcript):
    out = []
    for seg in transcript.get("segments", []):
        out += seg.get("words") or []
    return out


def align(base_segments, our_words, omission_min=5, base_only_min=5):
    base_norm, base_meta = [], []
    for si, seg in enumerate(base_segments):
        for norm, orig in _tokens(strip_pauses(seg["text"])):
            base_norm.append(norm)
            base_meta.append({"orig": orig, "seg": si})

    our_norm, our_meta = [], []
    for w in our_words:
        for norm, orig in _tokens(w.get("word", "")):
            our_norm.append(norm)
            our_meta.append({"orig": orig, "start": w.get("start"), "prob": w.get("prob")})

    sm = SequenceMatcher(None, base_norm, our_norm, autojunk=False)
    flags = []
    base_conf = [None] * len(base_norm)

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                base_conf[i1 + k] = our_meta[j1 + k]["prob"]
        elif tag == "replace":
            flags.append({
                "type": "disagreement",
                "seg": base_meta[i1]["seg"] if i1 < len(base_meta) else None,
                "base_text": " ".join(m["orig"] for m in base_meta[i1:i2]),
                "audio_text": " ".join(m["orig"] for m in our_meta[j1:j2]),
                "start": our_meta[j1]["start"] if j1 < len(our_meta) else None,
            })
        elif tag == "insert" and (j2 - j1) >= omission_min:
            flags.append({
                "type": "omission",
                "seg": base_meta[i1]["seg"] if i1 < len(base_meta)
                else (base_meta[-1]["seg"] if base_meta else None),
                "base_text": "",
                "audio_text": " ".join(m["orig"] for m in our_meta[j1:j2]),
                "start": our_meta[j1]["start"] if j1 < len(our_meta) else None,
            })
        elif tag == "delete" and (i2 - i1) >= base_only_min:
            flags.append({
                "type": "base_only",
                "seg": base_meta[i1]["seg"],
                "base_text": " ".join(m["orig"] for m in base_meta[i1:i2]),
                "audio_text": "",
                "start": None,
            })

    coverage = sum(1 for c in base_conf if c is not None) / max(1, len(base_norm))
    return {
        "flags": flags,
        "base_conf": base_conf,
        "n_base_tokens": len(base_norm),
        "n_our_tokens": len(our_norm),
        "match_coverage": round(coverage, 3),
    }


def main():
    ap = argparse.ArgumentParser(description="Align base transcript with our re-transcription.")
    ap.add_argument("base", help="noScribe .docx (or other base format)")
    ap.add_argument("whisper_json", help="our re-transcription (.whisper.json)")
    args = ap.parse_args()

    base = load_base(args.base)
    our = json.loads(Path(args.whisper_json).read_text())
    res = align(base["segments"], words_from_whisper(our))

    print(f"base_tokens={res['n_base_tokens']}  our_tokens={res['n_our_tokens']}  "
          f"match_coverage={res['match_coverage']}")
    print(f"{len(res['flags'])} flags:")
    for f in res["flags"]:
        loc = f"{f['start']:.0f}s" if f.get("start") is not None else "  -"
        print(f"  [{loc}] {f['type']:>12} | base={f['base_text']!r}  audio={f['audio_text']!r}")


if __name__ == "__main__":
    main()
