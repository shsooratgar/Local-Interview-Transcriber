#!/usr/bin/env python3
"""Align a base transcript (e.g. noScribe) with our Whisper re-transcription by
TEXT — no timestamps needed in the base. Surfaces:

  - disagreement flags : base says X, audio says Y  -> likely mis-hearing
  - omission flags     : audio has a chunk the base lacks -> likely dropped passage
  - base_only flags    : base has a chunk the audio lacks -> noScribe extra / our miss

Each flag carries a few words of context on both sides (base_ctx / audio_ctx) so
a reviewer can read the span inside its sentence. Per-word confidence from the
audio is carried onto the base words, and match_coverage reports how independent
our pass is from noScribe.

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
CONTEXT_WORDS = 6


def _tokens(text):
    return [(m.group(0).lower(), m.group(0)) for m in _WORD.finditer(text)]


def words_from_whisper(transcript):
    out = []
    for seg in transcript.get("segments", []):
        out += seg.get("words") or []
    return out


def _ctx(meta, lo, hi, n=CONTEXT_WORDS):
    """{before, span, after} of original-cased words around meta[lo:hi]."""
    return {
        "before": " ".join(m["orig"] for m in meta[max(0, lo - n):lo]),
        "span": " ".join(m["orig"] for m in meta[lo:hi]),
        "after": " ".join(m["orig"] for m in meta[hi:hi + n]),
    }


def align(base_segments, our_words, omission_min=5, base_only_min=5):
    base_norm, base_meta = [], []
    for si, seg in enumerate(base_segments):
        for norm, orig in _tokens(strip_pauses(seg["text"])):
            base_norm.append(norm)
            base_meta.append({"orig": orig, "seg": si})

    our_norm, our_meta = [], []
    for wi, w in enumerate(our_words):
        for norm, orig in _tokens(w.get("word", "")):
            our_norm.append(norm)
            our_meta.append({"orig": orig, "start": w.get("start"), "end": w.get("end"),
                             "prob": w.get("prob"), "wi": wi})

    def raw_span(j1, j2):
        """Whisper's original wording (casing + punctuation) for meta tokens [j1:j2)."""
        if j1 >= j2:
            return ""
        lo, hi = our_meta[j1]["wi"], our_meta[j2 - 1]["wi"]
        return "".join((our_words[k].get("word") or "") for k in range(lo, hi + 1)).strip()

    sm = SequenceMatcher(None, base_norm, our_norm, autojunk=False)
    flags = []
    base_conf = [None] * len(base_norm)

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                base_conf[i1 + k] = our_meta[j1 + k]["prob"]
        elif tag == "replace":
            probs = [our_meta[k]["prob"] for k in range(j1, j2) if our_meta[k]["prob"] is not None]
            blen, alen = i2 - i1, j2 - j1
            # a short transcript span aligned to a much longer audio span = noScribe
            # collapsed/dropped a chunk (often another speaker's turn), not a word-fix
            ftype = "recovered" if (blen <= 2 and alen - blen >= 3) else "disagreement"
            flags.append({
                "type": ftype,
                "seg": base_meta[i1]["seg"] if i1 < len(base_meta) else None,
                "base_text": " ".join(m["orig"] for m in base_meta[i1:i2]),
                "audio_text": raw_span(j1, j2),
                "start": our_meta[j1]["start"] if j1 < len(our_meta) else None,
                "end": our_meta[j2 - 1]["end"] if j1 < j2 <= len(our_meta) else None,
                "our_conf": round(sum(probs) / len(probs), 3) if probs else None,
                "base_ctx": _ctx(base_meta, i1, i2),
                "audio_ctx": _ctx(our_meta, j1, j2),
            })
        elif tag == "insert" and (j2 - j1) >= omission_min:
            probs = [our_meta[k]["prob"] for k in range(j1, j2) if our_meta[k]["prob"] is not None]
            flags.append({
                "type": "omission",
                "seg": base_meta[i1]["seg"] if i1 < len(base_meta) else (base_meta[-1]["seg"] if base_meta else None),
                "base_text": "",
                "audio_text": raw_span(j1, j2),
                "start": our_meta[j1]["start"] if j1 < len(our_meta) else None,
                "end": our_meta[j2 - 1]["end"] if j1 < j2 <= len(our_meta) else None,
                "our_conf": round(sum(probs) / len(probs), 3) if probs else None,
                "base_ctx": _ctx(base_meta, i1, i1),
                "audio_ctx": _ctx(our_meta, j1, j2),
            })
        elif tag == "delete" and (i2 - i1) >= base_only_min:
            # no audio words here; the nearest audio time locates the gap for re-listen
            if j1 > 0:
                gap_at = our_meta[j1 - 1].get("end") or our_meta[j1 - 1].get("start")
            else:
                gap_at = our_meta[j1]["start"] if j1 < len(our_meta) else None
            flags.append({
                "type": "base_only",
                "seg": base_meta[i1]["seg"],
                "base_text": " ".join(m["orig"] for m in base_meta[i1:i2]),
                "audio_text": "",
                "start": gap_at,
                "end": None,
                "base_ctx": _ctx(base_meta, i1, i2),
                "audio_ctx": _ctx(our_meta, j1, j1),
            })

    coverage = sum(1 for c in base_conf if c is not None) / max(1, len(base_norm))
    return {
        "flags": flags, "base_conf": base_conf,
        "n_base_tokens": len(base_norm), "n_our_tokens": len(our_norm),
        "match_coverage": round(coverage, 3),
    }


def main():
    ap = argparse.ArgumentParser(description="Align base transcript with our re-transcription.")
    ap.add_argument("base", help="noScribe .docx (or other base format)")
    ap.add_argument("whisper_json", help="our re-transcription (.whisper.json)")
    args = ap.parse_args()
    base = load_base(args.base)
    our = json.loads(Path(args.whisper_json).read_text(encoding="utf-8"))
    res = align(base["segments"], words_from_whisper(our))
    types = {}
    for f in res["flags"]:
        types[f["type"]] = types.get(f["type"], 0) + 1
    print(f"base_tokens={res['n_base_tokens']}  our_tokens={res['n_our_tokens']}  "
          f"match_coverage={res['match_coverage']}")
    print(f"{len(res['flags'])} flags: {types}")


if __name__ == "__main__":
    main()
