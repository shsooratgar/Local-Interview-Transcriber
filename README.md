# Local Interview Transcriber & Checker

Find & fix likely mis-transcriptions, omissions, and speaker/overlap issues in interview transcripts — **fully local, free, and offline**, so confidential audio never leaves your machine. Built to QA ~50 English/German interviews originally transcribed with [noScribe](https://github.com/kaixxx/noScribe).

## ⚠️ Confidential data
Audio + transcripts live in `data/`, results in `output/` — both git-ignored. Keep this repository **private**.

## How it works (Option A)
1. **Re-transcribe** the audio locally (Whisper via MLX) → word-level confidence.
2. **Text-align** it against the noScribe `.docx` (no timestamps needed).
3. **Flag**: *disagreements* (mis-hearings), *recovered* passages (dropped chunks, often another speaker), *omissions*, *not-heard* passages (in the transcript but never in the audio — possible fabrication), *overlaps* (`//…//`).
4. A careful **re-listen** (slower Whisper on a short clip around every flag) votes as a third ear — flags it contradicts are dropped.
5. A **local LLM** (Ollama, `qwen2.5:14b`) adjudicates — grounded, never invents — with pure-code gates removing noise (confidence, hallucinations, acronym downgrades, filler/no-op, ungrounded corrections).
6. **Summarize** into ≤8 agenda-style topics + suggest **verbatim key quotes** (code-verified word-for-word against the transcript).
7. **Review** in the HTML cockpit (click-to-play audio, keep/drop, your-own-correction) → **Apply** writes `output/final/<stem>.corrected.docx` (original untouched, corrections placed in-position) with the **meta header table** (title · date · duration · participants · summary · key quotes) filled where known — existing entries never overwritten — plus a **change-tracked copy** in `output/changes/` (removals struck through, additions green). Generated documents keep the original's fonts and formatting untouched — if Word on Mac asks about missing fonts (noScribe's Play, Office's Aptos), install those fonts locally rather than altering shared documents.

## Setup (macOS, Apple Silicon)
```bash
brew install ffmpeg ollama && brew services start ollama && ollama pull qwen2.5:14b
conda create -y -n transcriber python=3.11 && conda activate transcriber
pip install -r requirements.txt          # to fetch public test data: pip install -r requirements-dev.txt
python src/check_setup.py                # verify the toolchain
```

## Use
```bash
conda activate transcriber
# process one file  ->  output/reviews/<stem>.review.{docx,html,json}
python src/pipeline.py "data/audio/file.m4a" --base "data/transcripts/file.docx"
# process a WHOLE STUDY (all audio+transcript pairs, sub-folders included; resume-safe;
# writes the status sheet output/data_log.xlsx):
#   double-click batch.command      (or:  python src/batch.py "data/my_study")
# review + apply (audio player + working Apply button):
#   double-click review.command     (or:  python src/serve_review.py "file")
```
Add domain terms / abbreviations to `glossary/glossary.txt` to bias the transcription and the reviewer (re-run with `--force` to re-transcribe).

## Layout
`src/`: transcribe · transcript_io · align · llm_review · summarize · pipeline · report_docx · report_html · apply_docx · serve_review · batch · flag · common.
`Local-Transcriber-Windows/` — self-contained kit for Windows collaborators; **see [WINDOWS.md](WINDOWS.md) before touching it** (sync contract, platform rules, release script `tools/build_windows_bundle.sh`).
`review.command` — double-click launcher. `config.example.yaml` — tuning (confidence gate, per-file cap, models, `review_port`). Your keep/drop/edit choices autosave to `output/<stem>.choices.json` and reload on open.

## Status
🚧 Working end-to-end on Mac. TBD: Windows setup for collaborators; optional standalone mode (drop noScribe via a second internal Whisper pass + pyannote diarization); speaker verification by voice.
