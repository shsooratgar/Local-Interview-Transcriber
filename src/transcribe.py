#!/usr/bin/env python3
"""Re-transcribe an audio file locally with Whisper into a normalized structure
with word-level timestamps and confidence. Results are cached as JSON in the
output directory so we never transcribe the same file twice.

Two pluggable backends (config: whisper_backend):
  * "mlx"    — mlx-whisper, GPU-accelerated on Apple Silicon (fast; Mac only).
  * "faster" — faster-whisper (CTranslate2), cross-platform CPU/NVIDIA — this is
               the Windows / Intel path. Produces the same word probs + times.

Imports for each backend are lazy, so this module loads even when only one of
them is installed (e.g. faster-whisper on Windows, where mlx is unavailable).

Usage:
    python src/transcribe.py data/audio/interview01.m4a
    python src/transcribe.py data/audio/interview01.m4a --backend faster --model large-v3
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path

from common import ensure_dirs, load_config, load_glossary, out_dirs


def _glossary_prompt(terms: list[str], max_chars: int = 600) -> str | None:
    """Whisper's initial_prompt nudges decoding toward these spellings.
    The prompt window is small, so we only include a slice of the glossary."""
    if not terms:
        return None
    return ("Technical terms: " + ", ".join(terms))[:max_chars]


def _assemble(audio_path, model, language, duration, text, segments) -> dict:
    return {
        "audio": str(audio_path),
        "model": model,
        "language": language,
        "duration": duration or 0.0,
        "text": (text or "").strip(),
        "segments": segments,
    }


# ---------- backend: mlx-whisper (Apple Silicon) ----------

def _transcribe_mlx(audio_path, model, language, prompt, verbose=True) -> dict:
    import mlx_whisper  # lazy: not available on Windows/Intel
    # condition_on_previous_text=False curbs runaway repetition/hallucination loops;
    # verbose=True streams segments so a long file shows live progress (None = silent).
    opts = {"path_or_hf_repo": model, "word_timestamps": True,
            "condition_on_previous_text": False, "verbose": True if verbose else None}
    if language and language != "auto":
        opts["language"] = language
    if prompt:
        opts["initial_prompt"] = prompt
    raw = mlx_whisper.transcribe(str(audio_path), **opts)
    segments = []
    for s in raw.get("segments", []):
        words = [
            {"word": w["word"], "start": w.get("start"), "end": w.get("end"),
             "prob": round(float(w["probability"]), 4) if w.get("probability") is not None else None}
            for w in (s.get("words") or [])
        ]
        segments.append({
            "id": s.get("id"), "start": s.get("start"), "end": s.get("end"),
            "text": (s.get("text") or "").strip(), "avg_logprob": s.get("avg_logprob"),
            "no_speech_prob": s.get("no_speech_prob"), "compression_ratio": s.get("compression_ratio"),
            "words": words,
        })
    duration = segments[-1]["end"] if segments and segments[-1]["end"] else 0.0
    return _assemble(audio_path, model, raw.get("language"), duration, raw.get("text"), segments)


# ---------- backend: faster-whisper (cross-platform / Windows) ----------

_FASTER_MODELS: dict = {}  # loaded WhisperModel instances, reused across clips


def _faster_model(model, device, compute_type):
    from faster_whisper import WhisperModel  # lazy: heavy import, CTranslate2 backend
    key = (model, device, compute_type)
    if key not in _FASTER_MODELS:
        _FASTER_MODELS[key] = WhisperModel(model, device=device, compute_type=compute_type)
    return _FASTER_MODELS[key]


def _transcribe_faster(audio_path, model, language, prompt, device, compute_type, verbose=True) -> dict:
    wm = _faster_model(model, device, compute_type)
    seg_iter, info = wm.transcribe(
        str(audio_path), word_timestamps=True,
        language=(language if language and language != "auto" else None),
        initial_prompt=prompt, condition_on_previous_text=False,
    )
    segments, texts = [], []
    for s in seg_iter:  # generator — transcription actually runs as we iterate
        words = [
            {"word": w.word, "start": w.start, "end": w.end,
             "prob": round(float(w.probability), 4) if w.probability is not None else None}
            for w in (s.words or [])
        ]
        segments.append({
            "id": s.id, "start": s.start, "end": s.end, "text": (s.text or "").strip(),
            "avg_logprob": s.avg_logprob, "no_speech_prob": s.no_speech_prob,
            "compression_ratio": s.compression_ratio, "words": words,
        })
        texts.append(s.text or "")
        if verbose:
            print(f"  [{s.start:6.1f}s] {s.text.strip()[:80]}", flush=True)  # live progress
    return _assemble(audio_path, model, info.language, info.duration, " ".join(texts), segments)


# ---------- careful re-listen (clip around a flagged span) ----------

def transcribe_clip(audio_path, start, end, cfg) -> str | None:
    """Cut [start, end] seconds out of the audio (ffmpeg) and decode it with the
    CAREFUL model — a slower, more accurate third listen used to veto flags.
    Returns the clip's text, or None when disabled (whisper_model_careful: "")."""
    model = (cfg.get("whisper_model_careful") or "").strip()
    if not model:
        return None
    backend = cfg.get("whisper_backend", "mlx")
    language = cfg.get("whisper_language", "auto")
    prompt = _glossary_prompt(load_glossary(cfg.get("glossary_file")) or [])
    with tempfile.TemporaryDirectory() as td:
        clip = Path(td) / "clip.wav"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error",
             "-ss", f"{max(0.0, float(start)):.2f}", "-to", f"{float(end):.2f}",
             "-i", str(audio_path), "-ar", "16000", "-ac", "1", "-y", str(clip)],
            check=True, capture_output=True)
        if backend == "faster":
            res = _transcribe_faster(clip, cfg.get("whisper_model_careful_faster", "large-v3"),
                                     language, prompt, cfg.get("whisper_device", "auto"),
                                     cfg.get("whisper_compute_type", "int8"), verbose=False)
        else:
            res = _transcribe_mlx(clip, model, language, prompt, verbose=False)
    return res["text"]


# ---------- dispatch + cache ----------

def transcribe_audio(audio_path, cfg) -> dict:
    backend = cfg.get("whisper_backend", "mlx")
    language = cfg.get("whisper_language", "auto")
    prompt = _glossary_prompt(load_glossary(cfg.get("glossary_file")) or [])
    if backend == "faster":
        return _transcribe_faster(audio_path, cfg.get("whisper_model_faster", "large-v3"),
                                   language, prompt, cfg.get("whisper_device", "auto"),
                                   cfg.get("whisper_compute_type", "int8"))
    return _transcribe_mlx(audio_path, cfg.get("whisper_model"), language, prompt)


def cached_transcribe(audio_path, cfg, force=False, out_path=None):
    ensure_dirs(cfg)
    dirs = out_dirs(cfg)
    name = Path(audio_path).stem + ".whisper.json"
    out = Path(out_path) if out_path else dirs["cache"] / name
    if not out_path and not out.exists() and (dirs["root"] / name).exists():
        out = dirs["root"] / name  # legacy flat layout: reuse, don't re-transcribe
    if out.exists() and not force:
        return json.loads(out.read_text(encoding="utf-8")), out
    t0 = time.time()
    result = transcribe_audio(audio_path, cfg)
    result["transcribe_seconds"] = round(time.time() - t0, 1)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result, out


def main():
    ap = argparse.ArgumentParser(description="Re-transcribe audio with Whisper.")
    ap.add_argument("audio")
    ap.add_argument("--backend", choices=["mlx", "faster"], default=None)
    ap.add_argument("--model", default=None, help="override the backend's model")
    ap.add_argument("--language", default=None)
    ap.add_argument("--out", default=None, help="output JSON path (default: output/<stem>.whisper.json)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    if args.backend:
        cfg["whisper_backend"] = args.backend
    if args.model:
        cfg["whisper_model"] = args.model
        cfg["whisper_model_faster"] = args.model
    if args.language:
        cfg["whisper_language"] = args.language

    result, out = cached_transcribe(args.audio, cfg, force=args.force, out_path=args.out)
    n_words = sum(len(s["words"]) for s in result["segments"])
    print(f"backend={cfg['whisper_backend']}  language={result['language']}  "
          f"duration={result['duration']:.1f}s  segments={len(result['segments'])}  "
          f"words={n_words}  time={result.get('transcribe_seconds', '?')}s")
    print(f"saved -> {out}")


if __name__ == "__main__":
    main()
