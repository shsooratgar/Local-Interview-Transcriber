# Local Interview Transcriber & Checker

Find & fix likely mis-transcriptions, omissions, and speaker/overlap issues in interview transcripts — **fully local, free, and offline**, so confidential audio never leaves your machine. Built to QA ~50 English/German interviews originally transcribed with [noScribe](https://github.com/kaixxx/noScribe).

## ⚠️ Confidential data
Audio + transcripts live in `data/`, results in `output/` — both git-ignored. Keep this repository **private**.

## How it works (Option A)
1. **Re-transcribe** the audio locally (Whisper via MLX) → word-level confidence.
2. **Text-align** it against the noScribe `.docx` (no timestamps needed).
3. **Flag**: *disagreements* (mis-hearings), *recovered* passages (dropped chunks, often another speaker), *omissions*, *overlaps* (`//…//`).
4. A **local LLM** (Ollama, `qwen2.5:14b`) adjudicates — grounded, never invents — with pure-code gates removing noise (confidence, hallucinations, acronym downgrades, filler/no-op).
5. **Summarize** into ≤8 agenda-style topics.
6. **Review** in the HTML cockpit (click-to-play audio, keep/drop, your-own-correction) → **Apply** writes a corrected `.docx` (original untouched).

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
# process one file  ->  output/<stem>.review.{docx,html,json}
python src/pipeline.py "data/audio/file.m4a" --base "data/transcripts/file.docx"
# review + apply (audio player + working Apply button):
#   double-click review.command     (or:  python src/serve_review.py "file")
```
Add domain terms / abbreviations to `glossary/glossary.txt` to bias the transcription and the reviewer (re-run with `--force` to re-transcribe).

## Layout
`src/`: transcribe · transcript_io · align · llm_review · summarize · pipeline · report_docx · report_html · apply_docx · serve_review · flag · common.
`review.command` — double-click launcher. `config.example.yaml` — tuning (confidence gate, per-file cap, models).

## Status
🚧 Working end-to-end on Mac. TBD: Windows setup for collaborators; optional standalone mode (drop noScribe via a second internal Whisper pass + pyannote diarization); Excel summary export.
