#!/usr/bin/env python3
"""Ask the local LLM (Ollama) whether a flagged span is a transcription error
and, if so, what the correction should be. Output is strict JSON.

The prompt is deliberately CONSERVATIVE and GROUNDED: the model must not invent
content, and should only correct clear mishearings that sound similar to the
original and fit the surrounding context. A programmatic guard also rejects
"corrections" that are not similar to the original span.

Self-test with crafted English + German examples:
    python src/llm_review.py --demo
"""
from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher

import requests

from common import load_config, load_glossary

def ensure_llm_ready(model, ollama_url):
    """Fail fast BEFORE hours of transcription: verify the Ollama server is up
    and the model is downloaded; pull it if missing. (A missing model used to
    surface as a 404 only at review time — after a collaborator's multi-hour
    CPU run.) Raises SystemExit with a plain-language message on failure."""
    try:
        r = requests.get(f"{ollama_url}/api/tags", timeout=10)
        r.raise_for_status()
        names = {m.get("name") for m in r.json().get("models", [])}
    except requests.RequestException as e:
        raise SystemExit(
            f"[X] Cannot reach the local AI engine (Ollama) at {ollama_url}\n"
            f"    ({e})\n"
            "    Start Ollama (or re-run the setup) and try again.")
    if model in names or f"{model}:latest" in names:
        unload_llm(ollama_url)  # free RAM for the transcription phase ahead
        return
    print(f"AI model '{model}' is not downloaded yet — fetching it now (one time)…", flush=True)
    try:
        with requests.post(f"{ollama_url}/api/pull", json={"model": model},
                           stream=True, timeout=3600) as r:
            r.raise_for_status()
            last_status, last_bucket = "", -1
            for line in r.iter_lines():
                if not line:
                    continue
                info = json.loads(line)
                if info.get("error"):
                    raise RuntimeError(info["error"])
                status = info.get("status", "")
                total, done = info.get("total") or 0, info.get("completed") or 0
                if total:  # big layer: print every ~10%
                    bucket = int(done * 10 / total)
                    if bucket != last_bucket:
                        print(f"  downloading… {done * 100 // total}%", flush=True)
                        last_bucket = bucket
                elif status != last_status:
                    print(f"  {status}", flush=True)
                    last_status = status
        print(f"  model '{model}' ready.", flush=True)
    except Exception as e:  # noqa: BLE001 — turn into a clear, actionable exit
        raise SystemExit(
            f"[X] Could not download the AI model '{model}'\n"
            f"    ({e})\n"
            f"    Check the internet connection, then run the setup again\n"
            f"    (or in a terminal:  ollama pull {model})")


def unload_llm(ollama_url):
    """Ask Ollama to release any loaded model's RAM. On 8-16GB laptops the
    resident 7B model (pinned by keep_alive) plus Whisper large-v3 do not fit
    together — a field run died at model load with 'mkl_malloc: failed to
    allocate memory'. Called before the memory-heavy transcription phase and
    after a file completes; the next review call reloads the model, which
    _post_generate's patient timeout absorbs. Best-effort: never raises."""
    try:
        r = requests.get(f"{ollama_url}/api/ps", timeout=5)
        for m in r.json().get("models", []):
            name = m.get("name") or m.get("model")
            if name:
                requests.post(f"{ollama_url}/api/generate",
                              json={"model": name, "prompt": "", "keep_alive": 0},
                              timeout=30)
    except Exception:  # noqa: BLE001 — old Ollama without /api/ps etc.
        pass


def _post_generate(body, ollama_url, timeout=600):
    """One LLM call, tolerant of slow CPU laptops. Ollama unloads an idle model
    after ~5 min — and our re-listen phases take longer than that — so the next
    call pays a multi-minute model reload; a tight timeout then kills a healthy
    run (field incident: ReadTimeout at 180s ended a full-morning run at the
    recovered-passages step). keep_alive pins the model between calls, the
    timeout allows a reload, and one retry covers a residual stall."""
    body = {**body, "keep_alive": "2h"}
    for attempt in (1, 2):
        try:
            r = requests.post(f"{ollama_url}/api/generate", json=body, timeout=timeout)
            r.raise_for_status()
            return r
        except requests.Timeout:
            if attempt == 2:
                raise
            print("  (the language model is answering very slowly - retrying once...)", flush=True)


PROMPT = """An automatic speech recognizer produced this transcript passage. The part wrapped in
>>> <<< had low confidence and may be misheard. The text may be English or German — do not translate.

Decide whether the marked part is CLEARLY a transcription error.
Rules:
- Set is_error=true ONLY if the marked text is garbled/nonsensical or an obvious mishearing, AND you
  can give a correction that (a) sounds similar to the marked words and (b) is supported by the
  surrounding context.
- Do NOT invent information, names, numbers, or topics. Do NOT add words the context does not support.
- Short filler/backchannel words (uh, oh, yeah, well, right, mm) that read fine in context are NOT errors.
- If you are unsure, set is_error=false.

These domain terms are known-correct spellings; use one ONLY if it clearly fits a mishearing: {glossary}

Passage (suspected part marked):
{context_marked}

Respond with ONLY this JSON:
{{"is_error": true or false, "correction": "corrected text for the marked part (empty if not an error)", "reason": "short justification grounded in the context", "confidence": 0.0 to 1.0}}"""


def _similar(a, b):
    return SequenceMatcher(None, re.sub(r"\W+", " ", a.lower()).strip(),
                           re.sub(r"\W+", " ", b.lower()).strip()).ratio()


def review_span(span_text, context_text, glossary_terms, model, ollama_url):
    if span_text and span_text in context_text:
        marked = context_text.replace(span_text, f">>> {span_text} <<<", 1)
    else:
        marked = f"{context_text}\n\n[Marked part]: >>> {span_text} <<<"
    glossary = ", ".join(glossary_terms[:60]) if glossary_terms else "(none provided)"
    prompt = PROMPT.format(glossary=glossary, context_marked=marked)

    r = _post_generate({"model": model, "prompt": prompt, "stream": False,
                        "format": "json", "options": {"temperature": 0.0}}, ollama_url)
    resp = r.json().get("response", "{}")
    try:
        verdict = json.loads(resp)
    except json.JSONDecodeError:
        verdict = None
    if not isinstance(verdict, dict):
        return {"is_error": None, "correction": "",
                "reason": f"unparseable LLM output: {resp[:200]}", "confidence": 0.0}

    # Guard against fabrication: a real ASR fix should sound similar to the original.
    if verdict.get("is_error") and verdict.get("correction"):
        sim = _similar(span_text, verdict["correction"])
        words_added = len(verdict["correction"].split()) - len(span_text.split())
        if sim < 0.34 or words_added >= 3:
            verdict["is_error"] = False
            verdict["reason"] = (f"rejected (correction not similar to original: "
                                 f"sim={sim:.2f}, +{words_added} words) — was: {verdict.get('correction')!r}")
            verdict["correction"] = ""
            verdict["confidence"] = 0.0
    return verdict


DISAGREE_PROMPT = """An automatic transcript may contain a mis-hearing. For the marked part:
- the transcript reads:  "{base_text}"
- an independent re-transcription of the same audio heard:  "{audio_text}"

Context (the suspected part is marked with >>> <<<):
{context_marked}

Decide whether to correct the transcript here:
- If the audio version is clearly the correct wording (a genuine fix), set is_error=true and return it (lightly cleaned for punctuation/casing).
- If the ONLY difference is a spelling/orthography variant of the SAME word (British vs American English — e.g. favour/favor, colour/color, sulphate/sulfate, organise/organize, centre/center), set is_error=false. We do NOT care about spelling variants.
- If it is a DIFFERENT word or changes the meaning (e.g. collar vs color, wipe vs white), set is_error=true.
- If the transcript is fine, set is_error=false.
- Known-correct domain terms/abbreviations (keep their spelling and UPPERCASE; never replace one of these with a lowercase or garbled form): {glossary}
Do NOT invent anything beyond these two candidates. Keep the original language.

Respond with ONLY this JSON:
{{"is_error": true or false, "correction": "the corrected text (empty if fine)", "reason": "short reason", "confidence": 0.0 to 1.0}}"""


def review_disagreement(base_text, audio_text, context_text, model, ollama_url, glossary_terms=None):
    """Adjudicate a base-vs-audio disagreement. Grounded: the LLM chooses between
    the two real candidates instead of generating freely."""
    if base_text and base_text in context_text:
        marked = context_text.replace(base_text, f">>> {base_text} <<<", 1)
    else:
        marked = f"{context_text}\n\n[Marked]: >>> {base_text} <<<"
    glossary = ", ".join((glossary_terms or [])[:60]) or "(none provided)"
    prompt = DISAGREE_PROMPT.format(base_text=base_text, audio_text=audio_text,
                                    context_marked=marked, glossary=glossary)
    r = _post_generate({"model": model, "prompt": prompt, "stream": False,
                        "format": "json", "options": {"temperature": 0.0}}, ollama_url)
    try:
        verdict = json.loads(r.json().get("response", "{}"))
    except json.JSONDecodeError:
        verdict = None
    if not isinstance(verdict, dict):
        return {"is_error": None, "correction": "", "reason": "unparseable", "confidence": 0.0}

    # Grounding guard (same idea as review_span): the correction must stay close to
    # one of the two REAL candidates — reject anything the LLM rewrote freely.
    if verdict.get("is_error") and verdict.get("correction"):
        corr = str(verdict["correction"])
        sim = max(_similar(corr, audio_text), _similar(corr, base_text))
        words_added = len(corr.split()) - max(len(audio_text.split()), len(base_text.split()))
        if sim < 0.5 or words_added >= 3:
            verdict["is_error"] = False
            verdict["reason"] = (f"rejected (correction strays from both candidates: "
                                 f"sim={sim:.2f}, +{words_added} words) — was: {corr!r}")
            verdict["correction"] = ""
            verdict["confidence"] = 0.0
    return verdict


RECOVERED_PROMPT = """In an interview transcript, this spot was reduced to "{base_text}", but a second
transcription of the same audio actually contains: "{audio_text}".

Context (the spot is marked with >>> <<<):
{context_marked}

The transcript dropped this passage. Do two things:
1) Give the cleaned recovered text (fix obvious slips, keep the wording, do NOT invent).
2) Decide whether it reads like a DIFFERENT speaker's turn or interjection, rather than a
   continuation of the current speaker.

Respond with ONLY this JSON:
{{"text": "cleaned recovered text", "other_speaker": true or false, "reason": "short note", "confidence": 0.0 to 1.0}}"""


def review_recovered(base_text, audio_text, context_text, model, ollama_url):
    """Clean a dropped/recovered passage and judge whether it's another speaker."""
    if base_text and base_text in context_text:
        marked = context_text.replace(base_text, f">>> {base_text} <<<", 1)
    else:
        marked = f"{context_text}\n\n[Spot]: >>> {base_text} <<<"
    prompt = RECOVERED_PROMPT.format(base_text=base_text, audio_text=audio_text, context_marked=marked)
    r = _post_generate({"model": model, "prompt": prompt, "stream": False,
                        "format": "json", "options": {"temperature": 0.0}}, ollama_url)
    try:
        verdict = json.loads(r.json().get("response", "{}"))
    except json.JSONDecodeError:
        verdict = None
    if not isinstance(verdict, dict):
        return {"text": audio_text, "other_speaker": None, "reason": "unparseable", "confidence": 0.0}
    return verdict


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
            ("Great.",
             "Okay, so we're designing a new remote control. Great. And you all arrived on time."),
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
