#!/usr/bin/env python3
"""Re-transcribe an audio file locally with Whisper (MLX) into a normalized
structure with word-level timestamps and confidence. Results are cached as
JSON in the output directory so we never transcribe the same file twice.

Usage:
    python src/transcribe.py data/audio/interview01.m4a
    python src/transcribe.py data/audio/interview01.m4a --model mlx-community/whisper-tiny-mlx --out output/interview01.tiny.json
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import mlx_whisper

from common import ensure_dirs, load_config, load_glossary


def _glossary_prompt(terms: list[str], max_chars: int = 600) -> str | None:
    """Whisper's initial_prompt nudges decoding toward these spellings.
    The prompt window is small, so we only include a slice of the glossary."""
    if not terms:
        return None
    return ("Technical terms: " + ", ".join(terms))[:max_chars]


def transcribe_audio(audio_path, model, language="auto", glossary_terms=None) -> dict:
    opts = {"path_or_hf_repo": model, "word_timestamps": True}
    if language and language != "auto":
        opts["language"] = language
    prompt = _glossary_prompt(glossary_terms or [])
    if prompt:
        opts["initial_prompt"] = prompt
    raw = mlx_whisper.transcribe(str(audio_path), **opts)
    return _normalize(raw, audio_path, model)


def _normalize(raw: dict, audio_path, model: str) -> dict:
    segments = []
    for s in raw.get("segments", []):
        words = [
            {
                "word": w["word"],
                "start": w.get("start"),
                "end": w.get("end"),
                "prob": round(float(w["probability"]), 4) if w.get("probability") is not None else None,
            }
            for w in (s.get("words") or [])
        ]
        segments.append({
            "id": s.get("id"),
            "start": s.get("start"),
            "end": s.get("end"),
            "text": (s.get("text") or "").strip(),
            "avg_logprob": s.get("avg_logprob"),
            "no_speech_prob": s.get("no_speech_prob"),
            "compression_ratio": s.get("compression_ratio"),
            "words": words,
        })
    duration = segments[-1]["end"] if segments and segments[-1]["end"] else 0.0
    return {
        "audio": str(audio_path),
        "model": model,
        "language": raw.get("language"),
        "duration": duration,
        "text": (raw.get("text") or "").strip(),
        "segments": segments,
    }


def cached_transcribe(audio_path, cfg, force=False, out_path=None):
    ensure_dirs(cfg)
    out = Path(out_path) if out_path else Path(cfg["output_dir"]) / (Path(audio_path).stem + ".whisper.json")
    if out.exists() and not force:
        return json.loads(out.read_text()), out
    terms = load_glossary(cfg.get("glossary_file"))
    t0 = time.time()
    result = transcribe_audio(audio_path, cfg["whisper_model"],
                              cfg.get("whisper_language", "auto"), terms)
    result["transcribe_seconds"] = round(time.time() - t0, 1)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result, out


def main():
    ap = argparse.ArgumentParser(description="Re-transcribe audio with Whisper (MLX).")
    ap.add_argument("audio")
    ap.add_argument("--model", default=None)
    ap.add_argument("--language", default=None)
    ap.add_argument("--out", default=None, help="output JSON path (default: output/<stem>.whisper.json)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    if args.model:
        cfg["whisper_model"] = args.model
    if args.language:
        cfg["whisper_language"] = args.language

    result, out = cached_transcribe(args.audio, cfg, force=args.force, out_path=args.out)
    n_words = sum(len(s["words"]) for s in result["segments"])
    print(f"language={result['language']}  duration={result['duration']:.1f}s  "
          f"segments={len(result['segments'])}  words={n_words}  "
          f"time={result.get('transcribe_seconds', '?')}s")
    print(f"saved -> {out}")


if __name__ == "__main__":
    main()
