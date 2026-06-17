# Local Interview Transcriber & Checker

Find and fix likely mis-transcriptions in interview transcripts — **fully local, free, and offline**, so confidential audio never leaves your machine.

Built for ~50 English/German interviews originally transcribed with [noScribe](https://github.com/kaixxx/noScribe).

## ⚠️ Confidential data
Interview audio and transcripts are **never** committed to git. They live in `data/`, which is git-ignored. Keep this repository **private**. See [`data/README.md`](data/README.md).

## How it works
1. **Re-transcribe** the audio locally with Whisper (MLX, GPU-accelerated on Apple Silicon) to get word-level timestamps + confidence.
2. **Flag suspect spans** = low Whisper confidence (+ optional disagreement with the original noScribe transcript).
3. **LLM review** (local, via Ollama) reads each flagged span in context and suggests a correction + reason.
4. **Targeted re-listen** (optional) re-transcribes only the flagged audio slices more carefully.
5. **Report** an annotated file with timestamps, original text, suggestion, and confidence — you accept/reject each change.

A **glossary** of domain terms (`glossary/glossary.txt`) biases the transcriber and informs the LLM, fixing many technical-word errors up front.

## Requirements
- macOS on Apple Silicon (developed on M5 / 32 GB)
- [Homebrew](https://brew.sh): `ffmpeg`, `ollama`
- [Miniconda](https://docs.conda.io)
- A local LLM: `ollama pull qwen2.5:14b`

## Setup
```bash
# system tools
brew install ffmpeg ollama
brew services start ollama
ollama pull qwen2.5:14b

# python environment
conda create -y -n transcriber python=3.11
conda activate transcriber
pip install -r requirements.txt

# verify everything is ready
python src/check_setup.py
```

## Status
🚧 Work in progress — environment + scaffold in place; pipeline being built.

A Windows setup guide for collaborators will be added later.
