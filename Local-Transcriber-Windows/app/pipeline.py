#!/usr/bin/env python3
"""End-to-end review of ONE audio file.

Two modes:
  * confidence-only (no base transcript):
        python src/pipeline.py audio.wav
  * Option A (annotate an existing noScribe transcript):
        python src/pipeline.py audio.m4a --base transcript.docx
    -> re-transcribe -> align by text -> adjudicate disagreements
    -> write output/<stem>.review.docx (original transcript untouched, additions only)
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

from tqdm import tqdm

from align import align, words_from_whisper
from common import load_config, load_glossary, out_dirs
from flag import find_suspects
from llm_review import ensure_llm_ready, review_disagreement, review_recovered, review_span
from transcribe import cached_transcribe, transcribe_clip
from transcript_io import load_base


# ---------- confidence-only mode ----------

def review_file(audio, cfg, max_flags=None):
    transcript, _ = cached_transcribe(audio, cfg)
    suspects = find_suspects(transcript, cfg["low_confidence_threshold"],
                             cfg["min_segment_gap_seconds"], cfg["context_window_seconds"])
    terms = load_glossary(cfg["glossary_file"])
    todo = suspects[:max_flags] if max_flags else suspects
    reviewed = [{**sp, "llm": review_span(sp["text"], sp.get("context", ""), terms,
                                          cfg["llm_model"], cfg["ollama_url"])} for sp in todo]
    result = {
        "audio": str(audio), "language": transcript.get("language"),
        "n_flags_raw": len(suspects), "n_flags_reviewed": len(reviewed),
        "n_real_errors": sum(1 for r in reviewed if r["llm"].get("is_error")),
        "flags": reviewed,
    }
    out = out_dirs(cfg)["reviews"] / (Path(audio).stem + ".review.json")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result, out


# ---------- Option A: annotate an existing transcript ----------

_FILLER = {"oh", "or", "ok", "okay", "um", "uh", "mm", "hmm", "yeah", "yes", "no",
           "well", "so", "and", "the", "a", "an", "but", "it", "is", "i", "you",
           "right", "now", "then", "ah", "eh", "mhm"}


# words whose swap flips the meaning of an answer — NEVER filtered as trivial,
# even though they are short or sit in the filler list (yes/no, negations, EN+DE)
_MEANING_FLIP = {"yes", "yeah", "no", "not", "never", "none", "cannot", "cant",
                 "wont", "dont", "isnt", "arent", "wasnt", "werent", "didnt",
                 "doesnt", "couldnt", "shouldnt", "wouldnt",
                 "ja", "nein", "nicht", "kein", "keine", "nie", "niemals", "nichts"}


def _trivial_disagreement(base_text, audio_text):
    """Skip noisy single short-word swaps (fillers/backchannels) — not real errors.
    Negation/affirmation flips are never trivial: not/now or yes/no changes meaning."""
    b, a = base_text.split(), audio_text.split()
    if len(b) <= 1 and len(a) <= 1:
        bw = re.sub(r"\W", "", (b[0] if b else "").lower())
        aw = re.sub(r"\W", "", (a[0] if a else "").lower())
        if bw != aw and (bw in _MEANING_FLIP or aw in _MEANING_FLIP):
            return False
        return max(len(bw), len(aw)) <= 4 or (bw in _FILLER and aw in _FILLER)
    return False


def _audio_region(f):
    """The audio span plus its surrounding context — so we can catch a
    hallucination sitting *around* a clean-looking span (e.g. Cyrillic nearby)."""
    c = f.get("audio_ctx") or {}
    return " ".join([c.get("before", ""), f.get("audio_text", ""), c.get("after", "")])


def _degenerate(text):
    """True if OUR transcription looks like a hallucination: any non-Latin script
    (interviews are English/German, so Cyrillic/Greek/CJK = made up) or a
    repetition loop. These are our failures, not real errors."""
    toks = text.lower().split()
    if not toks:
        return True
    if any(ch.isalpha() and ord(ch) > 0x250 for ch in text):
        return True
    c = Counter(toks)
    return len(toks) >= 4 and c.most_common(1)[0][1] / len(toks) > 0.5


def _context_for(segments, seg_idx, window=2):
    if seg_idx is None:
        return ""
    lo, hi = max(0, seg_idx - window), min(len(segments), seg_idx + window + 1)
    return " ".join(s["text"] for s in segments[lo:hi])


def _is_subseq(s, t):
    it = iter(t)
    return all(c in it for c in s)


def _acronym_downgrade(base, audio):
    """Drop a flag that would downgrade a correct uppercase acronym to a lowercase
    or garbled form of the same thing (e.g. CAGR -> cgr)."""
    b = base.strip()
    a = audio.strip().lower().replace(" ", "")
    if re.fullmatch(r"[A-Z][A-Z&]+", b) and not re.search(r"[A-Z]{2}", audio):
        return _is_subseq(a, b.lower()) or _is_subseq(b.lower(), a)
    return False


_FILLER_WORDS = {"um", "uh", "er", "erm", "ah", "eh", "mm", "hmm", "mhm", "uhm"}


def _norm_words(text):
    ws = [re.sub(r"\W", "", w).lower() for w in text.split()]
    ws = [w for w in ws if w and w not in _FILLER_WORDS]
    out = []
    for w in ws:
        if not out or out[-1] != w:  # collapse immediate repeats ("what what" -> "what")
            out.append(w)
    return out


def _disfluency_only(base_text, audio_text):
    """base and audio differ only by filler words / repeated words -> not a real fix."""
    return _norm_words(base_text) == _norm_words(audio_text)


def _noop(base_text, correction):
    """the suggested correction is the same as the transcript (no real change)."""
    return _norm_words(base_text) == _norm_words(correction)


# ---------- careful re-listen: third vote on every flag ----------

def _support(careful_tokens, span_tokens):
    """Fraction of the span's words that the careful decode reproduces in order."""
    if not span_tokens:
        return 0.0
    sm = SequenceMatcher(None, careful_tokens, span_tokens, autojunk=False)
    return sum(b.size for b in sm.get_matching_blocks()) / len(span_tokens)


def _careful_check(audio, flags, cfg, cache, kind, cache_path=None):
    """Re-decode a short clip around each flag with the careful Whisper model and
    vote. Returns the surviving flags; the clip decode is cached in *cache* and
    persisted to *cache_path* after EVERY clip — this pass costs real time
    (~1 min/clip on a CPU laptop) and must survive a later crash.
      disagreement/recovered : drop when the re-listen sides with the transcript
      omission               : drop when the re-listen does not reproduce the words
      base_only              : drop when the re-listen DOES hear the transcript's words
    Fails open: if the careful model is disabled or a clip errors, flags pass through."""
    if not (cfg.get("whisper_model_careful") or "").strip() or not flags:
        return flags
    pad = float(cfg.get("careful_pad_seconds", 8.0))
    model = cfg["whisper_model_careful"]
    kept = []
    for f in tqdm(flags, desc=f"re-listen ({kind})", unit="clip"):
        start = f.get("start")
        if start is None:
            kept.append(f)
            continue
        end = f.get("end")
        if end is None:  # estimate from the span's word count
            n_words = len((f.get("audio_text") or f.get("base_text") or "").split())
            end = start + 0.4 * n_words + 1.0
        lo, hi = max(0.0, start - pad), end + pad
        key = f"{model}|{lo:.2f}|{hi:.2f}"
        text = cache.get(key)
        if text is None:
            try:
                text = transcribe_clip(audio, lo, hi, cfg)
            except Exception as e:  # noqa: BLE001 — ffmpeg/model hiccup: keep unverified
                print(f"  re-listen failed at {lo:.0f}s ({e}); keeping flag unverified", flush=True)
                text = None
            if text is None:
                kept.append(f)
                continue
            cache[key] = text
            if cache_path:
                cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
        ct = _norm_words(text)
        sb = _support(ct, _norm_words(f.get("base_text") or ""))
        sa = _support(ct, _norm_words(f.get("audio_text") or ""))
        f["careful"] = {"support_base": round(sb, 2), "support_audio": round(sa, 2)}
        if kind in ("disagreement", "recovered"):
            if sb >= 0.8 and sa < 0.5:
                continue  # re-listen sides with the transcript -> not an error
            f["careful"]["vote"] = "audio" if (sa >= 0.8 and sb < 0.5) else "unclear"
        elif kind == "omission":
            if sa < 0.5:
                continue  # extra words not reproduced -> likely our hallucination
            f["careful"]["vote"] = "audio"
        elif kind == "base_only":
            if sb >= 0.6:
                continue  # heard after all -> our first pass missed it, base is fine
            f["careful"]["vote"] = "absent"
        kept.append(f)
    return kept


def review_with_base(audio, base_path, cfg):
    print("Re-transcribing (or loading cache)…", flush=True)
    transcript, _ = cached_transcribe(audio, cfg)
    base = load_base(base_path)
    print("Aligning transcript with audio…", flush=True)
    al = align(base["segments"], words_from_whisper(transcript))
    terms = load_glossary(cfg["glossary_file"])

    min_conf = cfg.get("disagreement_min_confidence", 0.6)
    cap = cfg.get("max_corrections_per_file", 40)
    candidates = [f for f in al["flags"]
                  if f["type"] == "disagreement"
                  and not _trivial_disagreement(f["base_text"], f["audio_text"])
                  and not _degenerate(_audio_region(f))
                  and not _acronym_downgrade(f["base_text"], f["audio_text"])
                  and not _disfluency_only(f["base_text"], f["audio_text"])
                  and (f.get("our_conf") or 0) >= min_conf]
    candidates.sort(key=lambda f: f.get("our_conf") or 0, reverse=True)
    n_disagree = sum(1 for f in al["flags"] if f["type"] == "disagreement")
    candidates = candidates[:cap]
    print(f"{n_disagree} raw disagreements -> {len(candidates)} pass the quality gate "
          f"(our confidence >= {min_conf}); reviewing…", flush=True)

    # careful re-listen: clip-decode every flag with the slower model; cached on disk
    dirs = out_dirs(cfg)
    care_name = Path(audio).stem + ".careful.json"
    care_path = dirs["cache"] / care_name
    if not care_path.exists() and (dirs["root"] / care_name).exists():
        care_path = dirs["root"] / care_name  # legacy flat layout
    care_cache = json.loads(care_path.read_text(encoding="utf-8")) if care_path.exists() else {}

    n_before = len(candidates)
    candidates = _careful_check(audio, candidates, cfg, care_cache, "disagreement", care_path)
    if len(candidates) != n_before:
        print(f"re-listen vetoed {n_before - len(candidates)} of {n_before} "
              f"(sided with the transcript)", flush=True)

    disagreements = []
    if candidates:
        print("Waking the language model - the FIRST answer can take a few minutes "
              "on a laptop; after that it speeds up.", flush=True)
    for f in tqdm(candidates, desc="LLM review", unit="flag"):
        ctx = _context_for(base["segments"], f.get("seg"))
        v = review_disagreement(f["base_text"], f["audio_text"], ctx,
                                cfg["llm_model"], cfg["ollama_url"], terms)
        if v.get("is_error") and not _noop(f["base_text"], v.get("correction") or ""):
            spk = base["segments"][f["seg"]]["speaker"] if f.get("seg") is not None else None
            disagreements.append({**f, "speaker": spk, "llm": v})

    # omissions: hallucination gates (degenerate text, confidence, re-listen).
    # The confidence bar is deliberately LOWER than for disagreements: quiet or
    # overlapped speech that noScribe dropped often decodes with low confidence
    # yet is real (verified against human review of a full interview — real
    # omissions scored 0.36+, junk 0.12).
    om_min_conf = cfg.get("omission_min_confidence", 0.3)
    omissions = [f for f in al["flags"] if f["type"] == "omission"
                 and not _degenerate(_audio_region(f))
                 and (f.get("our_conf") or 0) >= om_min_conf]
    omissions = _careful_check(audio, omissions, cfg, care_cache, "omission", care_path)
    # present everything in time order
    disagreements.sort(key=lambda x: x.get("start") if x.get("start") is not None else 0.0)
    omissions.sort(key=lambda x: x.get("start") if x.get("start") is not None else 0.0)
    overlaps = [{"seg": i, "speaker": s["speaker"], "text": s["text"]}
                for i, s in enumerate(base["segments"]) if s.get("interjection")]

    # base-only passages: in the transcript but never heard by our pass — possible
    # noScribe fabrication. The re-listen drops the ones it can actually hear.
    base_only = [f for f in al["flags"] if f["type"] == "base_only"]
    base_only = _careful_check(audio, base_only, cfg, care_cache, "base_only", care_path)
    for f in base_only:
        f["speaker"] = base["segments"][f["seg"]]["speaker"] if f.get("seg") is not None else None
    base_only.sort(key=lambda x: x.get("seg") or 0)

    rec_flags = [f for f in al["flags"] if f["type"] == "recovered"
                 and not _degenerate(_audio_region(f))
                 and not _acronym_downgrade(f["base_text"], f["audio_text"])
                 and (f.get("our_conf") or 0) >= min_conf]
    rec_flags.sort(key=lambda f: f.get("our_conf") or 0, reverse=True)
    rec_flags = _careful_check(audio, rec_flags[:cap], cfg, care_cache, "recovered", care_path)
    if rec_flags:
        print(f"{len(rec_flags)} recovered (dropped) passages; checking…", flush=True)
    recovered = []
    for f in tqdm(rec_flags, desc="recovered", unit="flag"):
        ctx = _context_for(base["segments"], f.get("seg"))
        v = review_recovered(f["base_text"], f["audio_text"], ctx, cfg["llm_model"], cfg["ollama_url"])
        spk = base["segments"][f["seg"]]["speaker"] if f.get("seg") is not None else None
        recovered.append({**f, "speaker": spk, "other_speaker": v.get("other_speaker"),
                          "llm": {"correction": v.get("text") or f["audio_text"],
                                  "reason": v.get("reason"), "confidence": v.get("confidence")}})
    recovered.sort(key=lambda x: x.get("start") if x.get("start") is not None else 0.0)

    if care_cache:
        care_path.write_text(json.dumps(care_cache, ensure_ascii=False, indent=2), encoding="utf-8")

    participants = []
    for s in base["segments"]:
        spk = s.get("speaker")
        if spk and spk not in participants:
            participants.append(spk)

    return {
        "audio": str(audio), "base": str(base_path),
        "match_coverage": al["match_coverage"],
        "duration_seconds": transcript.get("duration"),
        "participants": participants,
        "disagreements": disagreements,
        "omissions": omissions, "overlaps": overlaps, "recovered": recovered,
        "base_only": base_only,
    }


def process_one(audio, base_path, cfg):
    """Full Option-A run for one file: review + all three report files.
    Returns the review dict (also used by the batch runner)."""
    from report_docx import write_docx_report
    from report_html import write_html_report
    review = review_with_base(audio, base_path, cfg)
    out = out_dirs(cfg)["reviews"] / (Path(audio).stem + ".review.docx")
    write_docx_report(base_path, review, out)
    write_html_report(audio, review, out.with_suffix(".html"))
    out.with_suffix(".json").write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    return review


def main():
    ap = argparse.ArgumentParser(description="Review one audio file end-to-end.")
    ap.add_argument("audio")
    ap.add_argument("--base", default=None, help="existing noScribe .docx transcript (Option A)")
    ap.add_argument("--max-flags", type=int, default=None, help="cap LLM calls (confidence mode)")
    args = ap.parse_args()

    cfg = load_config()
    ensure_llm_ready(cfg["llm_model"], cfg["ollama_url"])  # fail in seconds, not hours
    t0 = time.time()

    if args.base:
        review = process_one(args.audio, args.base, cfg)
        out = out_dirs(cfg)["reviews"] / (Path(args.audio).stem + ".review.docx")
        print(f"corrections: {len(review['disagreements'])}  omissions: {len(review['omissions'])}  "
              f"overlaps: {len(review['overlaps'])}  not-heard: {len(review['base_only'])}  "
              f"match_coverage: {review['match_coverage']}")
        print(f"saved -> {out}")
        print(f"        {out.with_suffix('.html')}   ({time.time() - t0:.0f}s)")
        return

    result, out = review_file(args.audio, cfg, args.max_flags)
    print(f"flags: {result['n_flags_raw']} raw -> reviewed {result['n_flags_reviewed']} "
          f"-> LLM kept {result['n_real_errors']} as real errors")
    print(f"saved -> {out}   ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
