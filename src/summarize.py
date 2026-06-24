#!/usr/bin/env python3
"""Summarize a transcript into specific, agenda-style bullet topics using the
local LLM (Ollama). Long transcripts are summarized in chunks (map) and then
merged (reduce), so there is no context-length limit.

The prompts are GROUNDED: the model must summarize ONLY what is actually said and
must not invent topics. (An earlier domain-primed prompt fabricated content.)

    python src/summarize.py --demo
    python src/summarize.py output/interview01.whisper.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import requests

from common import load_config

MAP_PROMPT = """Below is PART of a transcript (an interview, meeting, or talk). It may be English or German.

List ONLY the topics that are actually discussed in this text, as short, specific bullet points.
Rules:
- Use only what is in the text. Do NOT add, infer, generalize, or invent topics.
- If this part is greetings, small talk, or has no substantive topic, return an empty list.
- Keep each bullet in the transcript's original language.

Transcript part:
{chunk}

Respond with ONLY this JSON: {{"topics": ["..."]}}"""

REDUCE_PROMPT = """Below are granular topic bullets extracted from consecutive parts of ONE transcript (an interview, meeting, or talk). Many of them are narrow sub-points of the same broader theme.

Consolidate them into a SHORT, high-level agenda — the handful of main topics someone would put on a meeting agenda or table of contents.
Rules:
- Group related sub-points under one broader heading; merge duplicates and near-duplicates. Prefer a few broad topics over many narrow ones.
- Return AT MOST 8 topics. Aim for about 5-8; use fewer if the transcript is short. Never exceed 8.
- Stay faithful: only consolidate what is in the bullets below. Do NOT invent, infer, or add topics that are not present.
- Order the agenda logically (roughly the order discussed). Keep the original language.

Topic bullets:
{bullets}

Respond with ONLY this JSON: {{"summary": "one factual sentence on what was actually discussed", "topics": ["..."]}}"""


def _ollama(prompt, model, url, num_ctx=8192):
    r = requests.post(
        f"{url}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False, "format": "json",
              "options": {"temperature": 0.0, "num_ctx": num_ctx, "num_predict": 1024}},
        timeout=300,
    )
    r.raise_for_status()
    try:
        return json.loads(r.json().get("response", "{}"))
    except json.JSONDecodeError:
        return {}


def _chunks(text, max_chars=6000):
    words, out, cur, n = text.split(), [], [], 0
    for w in words:
        cur.append(w)
        n += len(w) + 1
        if n >= max_chars:
            out.append(" ".join(cur))
            cur, n = [], 0
    if cur:
        out.append(" ".join(cur))
    return out or [""]


def summarize_text(text, model, url):
    parts = _chunks(text)
    topics = []
    for ch in parts:
        topics += _ollama(MAP_PROMPT.format(chunk=ch), model, url).get("topics", [])
    if not topics:
        return {"summary": "", "topics": []}
    bullets = "\n".join(f"- {t}" for t in topics)
    final = _ollama(REDUCE_PROMPT.format(bullets=bullets), model, url)
    return {"summary": final.get("summary", ""),
            "topics": final.get("topics") or topics}


def _text_from(path):
    data = json.loads(Path(path).read_text())
    return data.get("text") or " ".join(s.get("text", "") for s in data.get("segments", []))


def main():
    ap = argparse.ArgumentParser(description="Summarize a transcript into topic bullets.")
    ap.add_argument("transcript", nargs="?", help="path to a .whisper.json (or .json with text)")
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    if args.demo:
        text = (
            "Interviewer: Let's talk about your work on catalysis for ammonia synthesis. "
            "Guest: Sure. We used an iron-based catalyst and studied the reaction kinetics at high pressure. "
            "We also applied a machine learning model, specifically a transformer, to predict optimal "
            "temperature profiles. Then we discussed scaling up the distillation column and the challenges "
            "of mass transfer. Finally we touched on reinforcement learning for controlling the reactor in real time."
        )
    elif args.transcript:
        text = _text_from(args.transcript)
    else:
        ap.error("pass --demo or a transcript json path")

    print(json.dumps(summarize_text(text, cfg["llm_model"], cfg["ollama_url"]),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
