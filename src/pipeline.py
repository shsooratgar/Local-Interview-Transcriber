#!/usr/bin/env python3
"""End-to-end review of ONE audio file:

    transcribe -> flag (confidence) -> LLM adjudicate each flag -> summarize
    -> write a structured review file (output/<stem>.review.json)

The LLM adjudicator is what turns noisy confidence flags into a short list of
*real* suspected errors with suggested fixes.

    python src/pipeline.py data/testsets/ami/ami5min.wav
    python src/pipeline.py data/testsets/ami/ami5min.wav --max-flags 20
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from common import load_config, load_glossary
from flag import find_suspects
from llm_review import review_span
from summarize import summarize_text
from transcribe import cached_transcribe


def review_file(audio, cfg, max_flags=None, do_summary=True):
    transcript, _ = cached_transcribe(audio, cfg)
    suspects = find_suspects(transcript, cfg["low_confidence_threshold"],
                             cfg["min_segment_gap_seconds"], cfg["context_window_seconds"])
    terms = load_glossary(cfg["glossary_file"])

    todo = suspects[:max_flags] if max_flags else suspects
    reviewed = []
    for sp in todo:
        verdict = review_span(sp["text"], sp.get("context", ""), terms,
                              cfg["llm_model"], cfg["ollama_url"])
        reviewed.append({**sp, "llm": verdict})

    summary = summarize_text(transcript["text"], cfg["llm_model"], cfg["ollama_url"]) \
        if do_summary else {"summary": "", "topics": []}

    result = {
        "audio": str(audio),
        "language": transcript.get("language"),
        "duration": transcript.get("duration"),
        "n_flags_raw": len(suspects),
        "n_flags_reviewed": len(reviewed),
        "n_real_errors": sum(1 for r in reviewed if r["llm"].get("is_error")),
        "summary": summary,
        "flags": reviewed,
    }
    out = Path(cfg["output_dir"]) / (Path(audio).stem + ".review.json")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result, out


def main():
    ap = argparse.ArgumentParser(description="Review one audio file end-to-end.")
    ap.add_argument("audio")
    ap.add_argument("--max-flags", type=int, default=None, help="cap LLM calls (for quick demos)")
    ap.add_argument("--no-summary", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    t0 = time.time()
    result, out = review_file(args.audio, cfg, args.max_flags, do_summary=not args.no_summary)
    print(f"flags: {result['n_flags_raw']} raw -> reviewed {result['n_flags_reviewed']} "
          f"-> LLM kept {result['n_real_errors']} as real errors")
    print(f"summary: {len(result['summary'].get('topics', []))} topics")
    print(f"saved -> {out}   ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
