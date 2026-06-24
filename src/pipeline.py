#!/usr/bin/env python3
"""End-to-end review of ONE audio file.

Two modes:
  * confidence-only (no base transcript):
        python src/pipeline.py audio.wav
  * Option A (annotate an existing noScribe transcript):
        python src/pipeline.py audio.m4a --base transcript.docx
    -> re-transcribe -> align by text -> adjudicate disagreements -> summarize
    -> write output/<stem>.review.docx (original transcript untouched, additions only)
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from tqdm import tqdm

from align import align, words_from_whisper
from common import load_config, load_glossary
from flag import find_suspects
from llm_review import review_disagreement, review_recovered, review_span
from summarize import summarize_text
from transcribe import cached_transcribe
from transcript_io import load_base


# ---------- confidence-only mode ----------

def review_file(audio, cfg, max_flags=None, do_summary=True):
    transcript, _ = cached_transcribe(audio, cfg)
    suspects = find_suspects(transcript, cfg["low_confidence_threshold"],
                             cfg["min_segment_gap_seconds"], cfg["context_window_seconds"])
    terms = load_glossary(cfg["glossary_file"])
    todo = suspects[:max_flags] if max_flags else suspects
    reviewed = [{**sp, "llm": review_span(sp["text"], sp.get("context", ""), terms,
                                          cfg["llm_model"], cfg["ollama_url"])} for sp in todo]
    summary = summarize_text(transcript["text"], cfg["llm_model"], cfg["ollama_url"]) \
        if do_summary else {"summary": "", "topics": []}
    result = {
        "audio": str(audio), "language": transcript.get("language"),
        "n_flags_raw": len(suspects), "n_flags_reviewed": len(reviewed),
        "n_real_errors": sum(1 for r in reviewed if r["llm"].get("is_error")),
        "summary": summary, "flags": reviewed,
    }
    out = Path(cfg["output_dir"]) / (Path(audio).stem + ".review.json")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result, out


# ---------- Option A: annotate an existing transcript ----------

_FILLER = {"oh", "or", "ok", "okay", "um", "uh", "mm", "hmm", "yeah", "yes", "no",
           "well", "so", "and", "the", "a", "an", "but", "it", "is", "i", "you",
           "right", "now", "then", "ah", "eh", "mhm"}


def _trivial_disagreement(base_text, audio_text):
    """Skip noisy single short-word swaps (fillers/backchannels) — not real errors."""
    b, a = base_text.split(), audio_text.split()
    if len(b) <= 1 and len(a) <= 1:
        bw = (b[0] if b else "").lower().strip(".,!?")
        aw = (a[0] if a else "").lower().strip(".,!?")
        return max(len(bw), len(aw)) <= 4 or (bw in _FILLER and aw in _FILLER)
    return False


def _degenerate(text):
    """True if OUR transcription text looks like a hallucination (non-Latin
    gibberish or a repetition loop) — those are our failures, not real errors."""
    toks = text.lower().split()
    if not toks:
        return True
    if sum(1 for ch in text if ch.isalpha() and ord(ch) > 0x250) >= 3:
        return True
    c = Counter(toks)
    return len(toks) >= 4 and c.most_common(1)[0][1] / len(toks) > 0.5


def _context_for(segments, seg_idx, window=2):
    if seg_idx is None:
        return ""
    lo, hi = max(0, seg_idx - window), min(len(segments), seg_idx + window + 1)
    return " ".join(s["text"] for s in segments[lo:hi])


def review_with_base(audio, base_path, cfg, do_summary=True):
    print("Re-transcribing (or loading cache)…", flush=True)
    transcript, _ = cached_transcribe(audio, cfg)
    base = load_base(base_path)
    print("Aligning transcript with audio…", flush=True)
    al = align(base["segments"], words_from_whisper(transcript))

    min_conf = cfg.get("disagreement_min_confidence", 0.6)
    cap = cfg.get("max_corrections_per_file", 40)
    candidates = [f for f in al["flags"]
                  if f["type"] == "disagreement"
                  and not _trivial_disagreement(f["base_text"], f["audio_text"])
                  and not _degenerate(f["audio_text"])
                  and (f.get("our_conf") or 0) >= min_conf]
    candidates.sort(key=lambda f: f.get("our_conf") or 0, reverse=True)
    n_disagree = sum(1 for f in al["flags"] if f["type"] == "disagreement")
    candidates = candidates[:cap]
    print(f"{n_disagree} raw disagreements -> {len(candidates)} pass the quality gate "
          f"(our confidence >= {min_conf}); reviewing…", flush=True)

    disagreements = []
    for f in tqdm(candidates, desc="LLM review", unit="flag"):
        ctx = _context_for(base["segments"], f.get("seg"))
        v = review_disagreement(f["base_text"], f["audio_text"], ctx,
                                cfg["llm_model"], cfg["ollama_url"])
        if v.get("is_error"):
            spk = base["segments"][f["seg"]]["speaker"] if f.get("seg") is not None else None
            disagreements.append({**f, "speaker": spk, "llm": v})

    omissions = [f for f in al["flags"] if f["type"] == "omission"]
    # present everything in time order
    disagreements.sort(key=lambda x: x.get("start") if x.get("start") is not None else 0.0)
    omissions.sort(key=lambda x: x.get("start") if x.get("start") is not None else 0.0)
    overlaps = [{"seg": i, "speaker": s["speaker"], "text": s["text"]}
                for i, s in enumerate(base["segments"]) if s.get("interjection")]

    rec_flags = [f for f in al["flags"] if f["type"] == "recovered"
                 and not _degenerate(f["audio_text"]) and (f.get("our_conf") or 0) >= min_conf]
    rec_flags.sort(key=lambda f: f.get("our_conf") or 0, reverse=True)
    if rec_flags:
        print(f"{len(rec_flags)} recovered (dropped) passages; checking…", flush=True)
    recovered = []
    for f in tqdm(rec_flags[:cap], desc="recovered", unit="flag"):
        ctx = _context_for(base["segments"], f.get("seg"))
        v = review_recovered(f["base_text"], f["audio_text"], ctx, cfg["llm_model"], cfg["ollama_url"])
        spk = base["segments"][f["seg"]]["speaker"] if f.get("seg") is not None else None
        recovered.append({**f, "speaker": spk, "other_speaker": v.get("other_speaker"),
                          "llm": {"correction": v.get("text") or f["audio_text"],
                                  "reason": v.get("reason"), "confidence": v.get("confidence")}})
    recovered.sort(key=lambda x: x.get("start") if x.get("start") is not None else 0.0)

    print("Summarizing…", flush=True)
    base_text = " ".join(s["text"] for s in base["segments"])
    summary = summarize_text(base_text, cfg["llm_model"], cfg["ollama_url"]) \
        if do_summary else {"summary": "", "topics": []}

    return {
        "audio": str(audio), "base": str(base_path),
        "match_coverage": al["match_coverage"],
        "summary": summary, "disagreements": disagreements,
        "omissions": omissions, "overlaps": overlaps, "recovered": recovered,
    }


def main():
    ap = argparse.ArgumentParser(description="Review one audio file end-to-end.")
    ap.add_argument("audio")
    ap.add_argument("--base", default=None, help="existing noScribe .docx transcript (Option A)")
    ap.add_argument("--max-flags", type=int, default=None, help="cap LLM calls (confidence mode)")
    ap.add_argument("--no-summary", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    t0 = time.time()

    if args.base:
        from report_docx import write_docx_report
        review = review_with_base(args.audio, args.base, cfg, do_summary=not args.no_summary)
        out = Path(cfg["output_dir"]) / (Path(args.audio).stem + ".review.docx")
        write_docx_report(args.base, review, out)
        from report_html import write_html_report
        html_out = write_html_report(args.audio, review, out.with_suffix(".html"))
        (out.with_suffix(".json")).write_text(json.dumps(review, ensure_ascii=False, indent=2))
        print(f"corrections: {len(review['disagreements'])}  omissions: {len(review['omissions'])}  "
              f"overlaps: {len(review['overlaps'])}  match_coverage: {review['match_coverage']}")
        print(f"summary topics: {len(review['summary']['topics'])}")
        print(f"saved -> {out}")
        print(f"        {html_out}   ({time.time() - t0:.0f}s)")
        return

    result, out = review_file(args.audio, cfg, args.max_flags, do_summary=not args.no_summary)
    print(f"flags: {result['n_flags_raw']} raw -> reviewed {result['n_flags_reviewed']} "
          f"-> LLM kept {result['n_real_errors']} as real errors")
    print(f"summary: {len(result['summary'].get('topics', []))} topics")
    print(f"saved -> {out}   ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
