"""Shared helpers: config loading, glossary loading, path resolution.

All relative paths in the config are resolved against the project root, so the
scripts work no matter which directory you run them from.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    # models
    "llm_model": "qwen2.5:14b",
    "whisper_model": "mlx-community/whisper-large-v3-turbo",          # fast first pass
    "whisper_model_careful": "mlx-community/whisper-large-v3-mlx",    # re-listen to flags
    "whisper_language": "auto",      # "auto" | "en" | "de"
    "languages": ["en", "de"],       # for the LLM's context only
    # flagging
    "low_confidence_threshold": 0.55,
    "context_window_seconds": 20,
    "min_segment_gap_seconds": 0.5,
    # local LLM server
    "ollama_url": "http://localhost:11434",
    # paths
    "audio_dir": "data/audio",
    "transcript_dir": "data/transcripts",
    "output_dir": "output",
    "glossary_file": "glossary/glossary.txt",
}

_PATH_KEYS = ("audio_dir", "transcript_dir", "output_dir", "glossary_file")


def _resolve(p) -> Path:
    p = Path(p)
    return p if p.is_absolute() else ROOT / p


def load_config(path: str = "config.yaml") -> dict:
    """Load config.yaml if present, else config.example.yaml, else defaults."""
    cfg = dict(DEFAULTS)
    chosen = None
    for candidate in (_resolve(path), ROOT / "config.example.yaml"):
        if candidate.exists():
            chosen = candidate
            break
    if chosen:
        data = yaml.safe_load(chosen.read_text()) or {}
        cfg.update(data)
    for k in _PATH_KEYS:
        cfg[k] = str(_resolve(cfg[k]))
    return cfg


def load_glossary(path: str | None = None) -> list[str]:
    """Return domain terms (one per line; '#' comments and blanks ignored).
    Falls back from the given path -> glossary.txt -> glossary.example.txt."""
    candidates = []
    if path:
        candidates.append(_resolve(path))
    candidates += [ROOT / "glossary" / "glossary.txt",
                   ROOT / "glossary" / "glossary.example.txt"]
    for p in candidates:
        if p and Path(p).exists():
            terms = []
            for line in Path(p).read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    terms.append(line)
            return terms
    return []


def ensure_dirs(cfg: dict) -> None:
    for k in ("audio_dir", "transcript_dir", "output_dir"):
        Path(cfg[k]).mkdir(parents=True, exist_ok=True)
