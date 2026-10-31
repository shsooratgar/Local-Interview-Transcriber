<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/ethz_logo_white.svg">
  <img src="assets/ethz_logo_black.svg" alt="ETH Zurich" height="32">
</picture>

# Local Interview Transcriber

A fully local, AI-powered tool for checking interview transcripts against their recordings. It listens to the audio again with Whisper, compares what it heard with a draft transcript, and shows every likely mistake next to a play button. You accept or reject each suggestion, and it writes a corrected Word document.

Nothing leaves your computer. There are no API keys and no cloud services, and every component is free, so it works for recordings you are not allowed to upload anywhere.

It was originally built as an internal tool for the Chair of Strategic Management and Innovation at ETH Zurich, for confidential research interviews in English and German. This repository contains only the code and invented test data. It is not an official ETH Zurich service, and the ETH Zurich logo remains a registered trademark of ETH Zurich.

## What it does

Input: a recording and its draft transcript as a `.docx`, for example from [noScribe](https://github.com/kaixxx/noScribe). The draft does not need timestamps.

1. **Transcribe.** Runs Whisper on the audio with word-level timestamps and confidence (`mlx-whisper` on Apple Silicon, `faster-whisper` on Windows). An optional glossary nudges it towards your domain terms.
2. **Align.** Matches the two texts word by word and collects four kinds of difference:
   - *Corrections:* the draft and the audio disagree on the wording.
   - *Recovered passages:* the draft has a word or two where the audio has a whole passage.
   - *Possible omissions:* the audio has speech the draft skipped.
   - *Not heard:* the draft has text the audio pass never heard, which may be invented.
3. **Listen again.** Cuts a short clip around each flag and decodes it with a slower Whisper model. Flags this second listen contradicts are dropped.
4. **Decide.** A local LLM (Ollama, `qwen2.5`) chooses between the two readings of each correction and cleans recovered passages. Plain code filters remove low-confidence flags, filler swaps and likely Whisper hallucinations, and reject corrections that stray from both readings.
5. **Review.** A browser page plays the audio at each flag. You choose keep, drop, or type your own wording. Choices save automatically, and a sidebar tracks which interviews are untouched, in progress or finished.
6. **Apply.** Writes a corrected `.docx` and a marked-up copy with removals struck through and additions in green. The original file is never changed. A table at the top is filled with title, date, duration measured from the audio and participants, and existing entries are left alone.

A whole folder of interviews can run as a batch, which skips finished files and writes a status sheet.

## What it does not do

- **It is not a standalone transcriber.** The full workflow needs a draft transcript. Audio alone only gives you Whisper's raw output and low-confidence flags as JSON, not a finished document.
- **It does not identify speakers.** Labels are carried over from the draft unchanged, so a wrong speaker stays wrong. The labels are also per file: `S01` in one interview is not `S01` in another.
- **It does not replace a person.** In three reviewed interviews, about a third of the suggestions were rejected (49 of 147), because the suggestion is only a candidate. Names and technical terms are the weak spot, since both transcripts can mishear the same word. A glossary helps with this. If you need an error-free transcript, you still have to listen to all of it.
- **It has not been benchmarked.** There is no labelled accuracy evaluation, only checks by hand on real interviews.
- **Teams-style exports and `.vtt` files are not supported** as drafts.
- **A file reviews at most 40 corrections by default.** Raise `max_corrections_per_file` to see more, at the cost of a longer run.

## Setup on a Mac (Apple Silicon)

```bash
brew install ffmpeg ollama && brew services start ollama && ollama pull qwen2.5:14b
conda create -y -n transcriber python=3.11 && conda activate transcriber
pip install -r requirements.txt
python src/check_setup.py
```

## Use

```bash
# one interview
python src/pipeline.py "data/audio/interview01.m4a" --base "data/transcripts/interview01.docx"

# a whole folder (or double-click batch.command)
python src/batch.py "data/my_study"

# review and apply (or double-click review.command)
python src/serve_review.py "interview01"
```

Results go to `output/`: `final/` holds the corrected documents, `changes/` the marked-up copies, `reviews/` the review pages and your choices, and `cache/` the saved transcriptions. `data/` and `output/` are ignored by git so real interviews cannot be committed by accident.

To try it without real data, `tools/make_sample_docx.py` and `tools/make_sample_audio.py` (macOS) create a short invented interview with planted errors.

Settings such as models, thresholds and the port are in `config.example.yaml`. Copy it to `config.yaml` to change them. Domain terms go in `glossary/glossary.txt`, which is ignored by git. It only affects new transcriptions, so run `python src/transcribe.py <audio> --force` after editing it.

## Windows

`Local-Transcriber-Windows/` is a double-click kit for people who don't use a terminal: `1 - SETUP` installs everything once, `2 - PROCESS` handles one interview, and `3 - PROCESS ALL` runs a batch. It uses the same code on CPU with smaller models, and a one-hour interview takes a few hours on a normal laptop.

The kit was run on real Windows machines, and the failures found there were fixed. [TEST-REPORT.md](TEST-REPORT.md) is the first field test and [WINDOWS.md](WINDOWS.md) is the developer guide. Never edit `app/` directly: change `src/` and run `tools/build_windows_bundle.sh`.

## Speed

On a MacBook Pro with an M5 chip and 32 GB of memory, the first pass transcribed a 56-minute interview in about 5 minutes. A full run takes roughly 10 to 20 minutes per interview, and reviewing the suggestions takes a person about 10 to 15 minutes per hour of audio.

## Status

This is the final state of the project and it is not under active development. There is no automated test suite. It was checked with scripted end-to-end runs on invented data and by use on real interviews.
