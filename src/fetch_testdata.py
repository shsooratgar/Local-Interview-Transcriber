#!/usr/bin/env python3
"""Fetch small SAMPLES of public, labeled speech datasets for development.

Saves audio (.wav) + a reference transcript (.ref.json / .ref.txt) under
data/testsets/<name>/. These are PUBLIC, non-confidential datasets used only to
build and validate the tool — your real interview data is never used here.

    python src/fetch_testdata.py                  # the minimal mixed set
    python src/fetch_testdata.py --only ami       # just one source
    python src/fetch_testdata.py --only ami --max-segments 30
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from common import ROOT

OUT = ROOT / "data" / "testsets"


def _save(name, sr, audio, segments):
    d = OUT / name
    d.mkdir(parents=True, exist_ok=True)
    wav = d / f"{name}.wav"
    sf.write(wav, audio, sr)
    (d / f"{name}.ref.json").write_text(json.dumps(segments, ensure_ascii=False, indent=2))
    txt = "\n".join(
        (f"[{s['speaker']}] {s['text']}" if s.get("speaker") else s["text"]) for s in segments
    )
    (d / f"{name}.ref.txt").write_text(txt, encoding="utf-8")
    print(f"  saved {wav.relative_to(ROOT)}  ({len(audio) / sr:.1f}s, {len(segments)} segments)")


def _load(repo, config, split):
    from datasets import load_dataset
    try:
        return load_dataset(repo, config, split=split, streaming=True)
    except Exception:
        # older datasets that ship a loading script
        return load_dataset(repo, config, split=split, streaming=True, trust_remote_code=True)


def _grab_hf(name, repo, config, split, text_key, speaker_key=None,
             group_key=None, max_segments=40, target_sr=16000):
    from datasets import Audio
    print(f"[{name}] streaming {repo} ({config}/{split}) ...")
    ds = _load(repo, config, split).cast_column("audio", Audio(sampling_rate=target_sr))

    chunks, segments, group, t, n = [], [], None, 0.0, 0
    for row in ds:
        if group_key:
            if group is None:
                group = row[group_key]
            elif row[group_key] != group:
                continue  # stay within a single meeting / talk
        text = (row.get(text_key) or "").strip()
        if not text:
            continue
        arr = np.asarray(row["audio"]["array"], dtype=np.float32)
        sr = row["audio"]["sampling_rate"]
        dur = len(arr) / sr
        seg = {"start": round(t, 2), "end": round(t + dur, 2), "text": text}
        if speaker_key and row.get(speaker_key) is not None:
            seg["speaker"] = str(row[speaker_key])
        chunks.append(arr)
        segments.append(seg)
        t += dur
        n += 1
        if n >= max_segments:
            break

    if not chunks:
        print(f"  [skip] no segments collected for {name}")
        return
    _save(name, target_sr, np.concatenate(chunks), segments)


def fetch_ami(max_segments=40):
    # English meetings, multi-speaker, with gold speaker labels
    _grab_hf("ami", "edinburghcstr/ami", "ihm", "train",
             text_key="text", speaker_key="speaker_id",
             group_key="meeting_id", max_segments=max_segments)


def fetch_voxpopuli(max_segments=40):
    # German parliamentary speech (best free German option)
    _grab_hf("voxpopuli_de", "facebook/voxpopuli", "de", "train",
             text_key="normalized_text", speaker_key="speaker_id",
             max_segments=max_segments)


def fetch_tedlium(max_segments=40):
    # English talks -> "presentation" type, single speaker
    _grab_hf("tedlium", "LIUM/tedlium", "release3", "train",
             text_key="text", speaker_key="speaker_id",
             group_key="speaker_id", max_segments=max_segments)


def fetch_earnings21(max_files=1):
    """Best-effort: one earnings call (mp3 + .nlp transcript) from GitHub —
    jargon- and named-entity-heavy English, the closest match to technical terms."""
    import urllib.request
    api = "https://api.github.com/repos/revdotcom/speech-datasets/contents/earnings21/media"
    try:
        with urllib.request.urlopen(api, timeout=30) as r:
            listing = json.load(r)
    except Exception as e:
        print(f"  [skip] earnings21 listing failed: {e}")
        return
    d = OUT / "earnings21"
    d.mkdir(parents=True, exist_ok=True)
    for f in [x for x in listing if x["name"].endswith(".mp3")][:max_files]:
        fid = f["name"][:-4]
        try:
            urllib.request.urlretrieve(f["download_url"], d / f["name"])
            nlp = ("https://raw.githubusercontent.com/revdotcom/speech-datasets/"
                   f"main/earnings21/transcripts/nlp_references/{fid}.nlp")
            urllib.request.urlretrieve(nlp, d / f"{fid}.nlp")
            print(f"  saved earnings21/{f['name']} (+ transcript)")
        except Exception as e:
            print(f"  [warn] {fid}: {e}")


ALL = {"ami": fetch_ami, "voxpopuli": fetch_voxpopuli,
       "tedlium": fetch_tedlium, "earnings21": fetch_earnings21}


def main():
    ap = argparse.ArgumentParser(description="Fetch public test datasets.")
    ap.add_argument("--only", choices=list(ALL), default=None)
    ap.add_argument("--max-segments", type=int, default=40)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ([args.only] if args.only else list(ALL)):
        try:
            ALL[name]() if name == "earnings21" else ALL[name](max_segments=args.max_segments)
        except Exception as e:
            print(f"[{name}] FAILED: {e}")


if __name__ == "__main__":
    main()
