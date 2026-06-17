#!/usr/bin/env python3
"""Ask the local LLM (Ollama) whether a flagged span is a transcription error
and, if so, what the correction should be. Output is strict JSON.

Self-test with crafted English + German examples:
    python src/llm_review.py --demo
"""
from __future__ import annotations

import argparse
import json

import requests

from common import load_config, load_glossary

PROMPT = """You are proofreading an automatically generated interview transcript.
Domain: artificial intelligence and process engineering.
Languages: English and German. Do NOT translate — keep the original language.
Speech recognition often mishears technical terms, names, acronyms and numbers.

Known-correct domain terms (prefer these spellings when they fit):
{glossary}

Below is a passage from the transcript. The suspicious part is wrapped in >>> <<<:

{context_marked}

Decide whether the marked part is likely a transcription error. If it is, give the
most plausible correction that fits the context and sounds similar to the marked
words. If it is probably correct, set is_error to false.

Respond with ONLY this JSON object and nothing else:
{{"is_error": true or false, "correction": "corrected text for the marked part (empty if fine)", "reason": "short explanation", "confidence": 0.0 to 1.0}}"""


def review_span(span_text, context_text, glossary_terms, model, ollama_url):
    if span_text and span_text in context_text:
        marked = context_text.replace(span_text, f">>> {span_text} <<<", 1)
    else:
        marked = f"{context_text}\n\n[Marked part]: >>> {span_text} <<<"
    glossary = ", ".join(glossary_terms[:80]) if glossary_terms else "(none provided)"
    prompt = PROMPT.format(glossary=glossary, context_marked=marked)

    r = requests.post(
        f"{ollama_url}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False,
              "format": "json", "options": {"temperature": 0.1}},
        timeout=180,
    )
    r.raise_for_status()
    resp = r.json().get("response", "{}")
    try:
        return json.loads(resp)
    except json.JSONDecodeError:
        return {"is_error": None, "correction": "",
                "reason": f"unparseable LLM output: {resp[:200]}", "confidence": 0.0}


def main():
    ap = argparse.ArgumentParser(description="LLM review of a flagged span.")
    ap.add_argument("--demo", action="store_true", help="run built-in test examples")
    args = ap.parse_args()

    cfg = load_config()
    terms = load_glossary(cfg["glossary_file"])

    if args.demo:
        examples = [
            ("cattle is",
             "So in the second reactor we rely on cattle is to speed up the reaction without being consumed."),
            ("reinforced film learning",
             "The agent was trained with reinforced film learning to optimize its policy over many episodes."),
            ("Stickstoff Dioxid",
             "Wir haben die Konzentration von Stickstoff Dioxid im Abgasstrom gemessen."),
        ]
        for span, ctx in examples:
            out = review_span(span, ctx, terms, cfg["llm_model"], cfg["ollama_url"])
            print(f"\nMARKED  : {span!r}")
            print(f"CONTEXT : {ctx}")
            print(f"LLM     : {json.dumps(out, ensure_ascii=False)}")
    else:
        ap.error("nothing to do — pass --demo (pipeline wiring comes next)")


if __name__ == "__main__":
    main()
