# Windows Bundle Test Report

**Date:** 2026-07-09 (evening run)
**Test type:** Automated field test, first run of the Windows distribution on real Windows hardware
**Machine:** Windows 10 Home 10.0.19045 · Intel i7-10750H (6C/12T, no NVIDIA GPU) · 32 GB RAM · 43 GB free on C:
**Baseline before test:** winget ✓, py launcher ✓, Python 3.13 ✓ — **no ffmpeg, no Ollama, no Python 3.11 on PATH** (representative of a collaborator PC)
**Test data:** synthetic only — `tools/make_sample_docx.py` transcript + Windows TTS (System.Speech, "Microsoft Hazel", 16 kHz mono, 46 s) speaking the `make_sample_audio.py` SCRIPT text. No real interview data ever touched this machine.

---

## Verdict (short)

**Not safe to hand out as-is — one critical, trivially fixable bug in SETUP.bat guarantees a broken install on every fresh PC.** The SETUP window dies silently right after the Python-packages step, so the two AI models are never downloaded, and re-running never gets past the same wall. Everything *behind* that wall is in genuinely good shape: the pipeline, the review page, apply/changes documents, UTF-8 handling, folder-move resilience, and the missing-LLM auto-recovery all passed every check. Fix the one `echo` line (and the `.gitignore` config.yaml trap for maintainers), rebuild the zip, and this is ready for a non-technical collaborator.

---

## Bugs found

### BUG 1 — CRITICAL: SETUP.bat aborts after pip; AI models never download (ships in the current zip)

`Local-Transcriber-Windows/1 - SETUP (run once).bat` line 60:

```bat
echo [X] Installing the Python packages failed (see above). Check your internet and re-run.
```

sits inside the `if errorlevel 1 ( … )` block after pip. cmd.exe closes the block at the unquoted `)` of "(see above)" **at parse time** — the branch never needs to be taken; pip succeeding doesn't help. Exact console output at the moment of death, reproduced on this machine directly after pip's `Successfully installed …` line:

```
. was unexpected at this time.
```

The batch then terminates entirely: **step [5/5] never runs** (no `large-v3` download, no `ollama pull qwen2.5:7b`), the final `pause` is skipped, and the window just vanishes — no `[X]` message, nothing to screenshot for the support flow. Re-running SETUP is the documented remedy for everything, but it hits the same parse error every time. A non-technical user is hard-stuck; the first PROCESS run then limps in via lazy downloads (faster-whisper fetches large-v3 itself, `ensure_llm_ready` pulls qwen), which is very plausibly the real story behind the "qwen2.5:7b pull silently never completing" field incident.

Empirically verified mechanism (scratch test on this machine): unquoted-but-**balanced** parens inside an `if (...)` block abort the batch; **quoted** parens (PROCESS.bat's `"1 - SETUP (run once)"`) are safe. Note **WINDOWS.md §5 states the rule wrong** ("parentheses must be balanced") — balance is irrelevant; only quoting or `^)`-escaping protects. The doc's wrong rule likely caused the bug.

**Fix (1 line):** drop the parens, e.g. `…failed - see above. Check…` — applied locally to the test copy (see "Local modifications"), after which SETUP ran to `ALL DONE` with exit code 0.

### BUG 2 — HIGH (maintainer trap): `.gitignore` swallows the bundle's config.yaml

`.gitignore` line 10 has unanchored `config.yaml`, which also matches `Local-Transcriber-Windows/config.yaml`. A fresh clone's bundle **folder** therefore has no config.yaml (the committed zip does contain it). Consequences:

- Anyone who copies the folder out of a fresh clone (or rebuilds the zip from one — `build_windows_bundle.sh` can't add a file that isn't there) ships a bundle whose `load_config()` falls back to `config.example.yaml` (absent in the bundle) and then to code DEFAULTS: `whisper_backend: mlx`, `audio_dir: data/audio` → **instant crash on Windows** (mlx is not installed) with wrong folders.
- **Fix:** anchor the ignore (`/config.yaml`) or add `!Local-Transcriber-Windows/config.yaml`, and `git add -f` the bundle copy.

For this test the config was restored from the committed zip.

### Verified non-bugs worth recording

- `src/llm_review.py` `ensure_llm_ready` URL is correct (`/api/pull`); an early grep rendering suggested backslashes — raw bytes checked, false alarm.
- Committed zip's `app/*.py` are byte-identical (modulo CRLF) to the repo folder's — no drift.
- The placeholder files `PUT YOUR … HERE.txt` in `audio/`/`transcripts/` do not confuse PROCESS.bat's file pickers.

---

## Pass/fail table

| # | Check | Result |
|---|---|---|
| **Phase 1 — deploy** |
| 1.1 | Copy folder out of repo to C:\TranscriberTest | ✅ PASS (but see BUG 2: config.yaml had to come from the zip) |
| **Phase 2 — SETUP** |
| 2.1 | SETUP run 1 as a user would | ❌ **FAIL — BUG 1**: dies after pip, `". was unexpected at this time."`, no models, no pause, window vanishes |
| 2.2 | SETUP re-run after 1-line local fix | ✅ PASS — idempotent re-run through all 5 steps, `ALL DONE`, exit 0 |
| 2.3 | venv `python.exe` exists; imports faster_whisper, docx, requests, yaml, tqdm | ✅ PASS (Python 3.11.9) |
| 2.4 | ffmpeg works in a NEW terminal | ✅ PASS (8.1.2 via WinGet Links on registry PATH; note: not visible to shells that pre-date the install — normal Windows behavior) |
| 2.5 | `ollama list` shows qwen2.5:7b | ✅ PASS (4.7 GB; ollama on PATH via HKCU entry added by installer) |
| 2.6 | large-v3 under `%USERPROFILE%\.cache\huggingface` | ✅ PASS (`models--Systran--faster-whisper-large-v3`, 2.88 GB, 12 files) |
| **Phase 3 — synthetic data** |
| 3.1 | make_sample_docx.py with venv python → copy into transcripts\ | ✅ PASS |
| 3.2 | Windows TTS wav (16 kHz mono) as audio\sample_audio.wav | ✅ PASS (46 s, "Microsoft Hazel Desktop") |
| **Phase 4 — functional e2e (tiny models)** |
| 4.1 | PROCESS runs: transcribe → re-listen → LLM → server → browser opens | ✅ PASS (2 m 35 s cold; browser did open on the machine) |
| 4.2 | Outputs ONLY in `output/{cache,reviews}` (then `final/`,`changes/` after apply); nothing stray | ✅ PASS |
| 4.3 | Planted error "cattle is"→catalyst suggested | ✅ PASS (c0, LLM correction "catalyst") |
| 4.4 | Planted error "reinforced film"→reinforcement suggested | ✅ PASS (c1) |
| 4.5 | Omitted sentence found | ✅ PASS (o0 = "We also compared it against a strong baseline before deployment.", verbatim) |
| 4.6 | Planted strings visible in served review page (HTTP 200) | ✅ PASS |
| 4.7 | POST /save `{"decisions":{"c0":…}}` | ✅ PASS → `{"ok":true,"saved":1}` |
| 4.8 | POST /apply same body | ✅ PASS → `{"applied":1,"skipped":0,"header":"ok"}` |
| 4.9 | final\ corrected.docx: header table incl. Duration/Summary/Key quotes; correction applied | ✅ PASS (Duration "0:46 min" + 3 Key quotes added; pre-filled Summary cell NOT overwritten; "catalyst" in body, "cattle is" gone; unaccepted c1 untouched) |
| 4.10 | changes\ changes.docx: strikethrough + green runs | ✅ PASS (strike `cattle is`, green-bold `catalyst`, color 137A3E) |
| 4.11 | review.json valid strict UTF-8, no mojibake | ✅ PASS |
| **Phase 5 — resilience** |
| 5a | MOVE to C:\TranscriberTest2, PROCESS works | ✅ PASS (41 s, identical results, no ModuleNotFoundError) |
| 5b | `ollama rm qwen2.5:7b` → PROCESS detects + auto-pulls BEFORE transcription | ✅ PASS (detected in seconds; "fetching it now" printed before "Re-transcribing"; 4.7 GB re-pulled with 10 %-step progress; run completed) |
| 5c | PROCESS again, well under a minute via caches | ✅ PASS (41 s) |
| **Phase 6 — realism (large-v3, cold cache)** |
| 6.1 | Full run with production models (large-v3 both passes, cold `output/cache`) | ✅ PASS — **1 m 09 s** on this hardware; found exactly the 2 planted errors + the omission with **zero** noise flags (the tiny-model bonus flag disappeared); match_coverage 0.955; all 3 re-listen clips decoded (~3.2 s/clip), no fail-open passthroughs |

## Timings

| Step | Wall time | Notes |
|---|---|---|
| SETUP run 1 (steps 1–4 then crash) | ~10 min | Python 3.11.9 + ffmpeg 8.1.2 + Ollama 0.31.2 via winget, venv, pip |
| SETUP run 2 (idempotent re-run + step 5) | 7 m 15 s | includes large-v3 (2.88 GB) + qwen2.5:7b (4.7 GB) at ~20 MB/s |
| PROCESS, tiny, cold caches | 2 m 35 s | first qwen call 109 s (model load into RAM); later calls ~4 s |
| PROCESS after folder move (5a) | 41 s | whisper + careful caches reused; LLM re-reviews |
| PROCESS with deleted LLM (5b) | 5 m 08 s | ~4.5 min of it is the 4.7 GB re-pull |
| PROCESS warm repeat (5c) | 41 s | |
| PROCESS, large-v3, cold cache (Phase 6) | **1 m 09 s** | launch 22:30:39 → review page serving 22:31:48; qwen still warm in Ollama from the previous run |

**Phase 6 realism run (large-v3, cold cache):** 46 s of clean TTS audio processed in 1 m 09 s — transcription streamed with live timestamps and got every planted phrase right ("catalyst", "reinforcement learning", "held out runs", plus the sentence the docx omits). Review output was *exactly* the 2 planted disagreements + 1 omission, no noise. Note this is a best-case CPU number (clean synthetic speech, short file, warm LLM); the "few hours for a one-hour interview" guidance in INSTRUCTIONS.txt remains the right expectation to set — extrapolating this run (~1.5× realtime for transcription alone, plus ~1 min re-listen per flagged spot on real audio with more flags, plus LLM time per flag) supports it.

## Usability rough edges (non-technical-user lens)

1. **The BUG 1 failure mode is the worst possible for the support playbook**: no `[X]`, no pause, the window closes itself. INSTRUCTIONS.txt tells users to screenshot `[X]` messages — there is nothing to screenshot.
2. **Scary tracebacks in the black window during review.** Every time the browser aborts an audio request (seek, tab close, refresh), the console prints a 20-line `Traceback … ConnectionResetError: [WinError 10054]` / `ConnectionAbortedError: [WinError 10053]`. Harmless (ThreadingHTTPServer keeps serving) but INSTRUCTIONS.txt only says *yellow warnings* are normal — a red-flag "Traceback/Error" wall will generate support emails or, worse, make users close the window mid-review. Consider a `handle_error` override in `serve_review.py` to swallow disconnect errors.
3. **Console mojibake:** `…` and `—` print as `�` under the default cp1252 console (e.g. `Re-transcribing (or loading cache)�`). Cosmetic — all files are clean UTF-8 — but it looks broken. `chcp 65001` in the .bat or ASCII-only console strings would fix it.
4. **First LLM call = ~2 min of frozen progress bar** (`LLM review: 0%` while qwen loads into RAM). A one-liner "loading the AI model (first time takes a couple of minutes)…" would prevent "it hung" reports.
5. **The review URL is not in INSTRUCTIONS.txt.** If the browser fails to open (or the user closes the tab), nothing tells them to go to `http://127.0.0.1:8765/…`. The console prints it, buried between tqdm bars.
6. **SETUP asks for a keypress before doing anything** (`pause` at the top). Harmless, but "press any key" + a wall of winget license text is the first thing a non-technical user sees; a friendlier "starting in 5 seconds…" would be smoother.
7. Ollama's pull progress renders ANSI spinner escape codes into logs when output is redirected; in a real console it looks fine. Only relevant for anyone collecting logs for support.

## Test-harness notes (transparency; not product findings)

- The test shell sets `NoDefaultCurrentDirectoryInExePath=1`, which blocks `call name.bat` resolution against the CWD. All launcher runs were done through thin wrapper .cmd files that clear this variable and refresh PATH from the registry — i.e. the environment a real double-click gets. Wrappers also piped Enter keypresses into `pause` and captured all console output to log files.
- The `/apply` and `/save` POSTs were sent with PowerShell `Invoke-RestMethod` exactly as specified in the plan.
- The machine's real default browser did open the review page during runs (visible as autosave pings in the server log).

## Local modifications made to keep testing (none committed; repo untouched except this report)

1. `C:\TranscriberTest\1 - SETUP (run once).bat` line 60: `(see above).` → `- see above.` — the BUG 1 workaround, applied **after** run 1 failed, so the failure is fully documented above.
2. `C:\TranscriberTest\config.yaml`: restored from the committed `Local-Transcriber-Windows.zip` (BUG 2), then edited per test plan (tiny models for Phases 4–5; large-v3 restored and `whisper_model_careful_faster` removed for Phase 6).
3. `data/testsets/sample_transcript.docx` regenerated in the repo by `make_sample_docx.py` (gitignored artifact, as designed).
4. Folder moved `C:\TranscriberTest` → `C:\TranscriberTest2` in Phase 5a (per plan); all later phases ran from the moved folder.

## What must be fixed before handing to a collaborator

1. **BUG 1** — the SETUP.bat echo line (1-line change) + rebuild zip (`tools/build_windows_bundle.sh`).
2. **BUG 2** — anchor `.gitignore`'s `config.yaml` and force-add the bundle copy, so future zips can't ship configless.
3. Correct WINDOWS.md §5's parenthesis rule (balance does NOT protect; quoting/escaping does) so the bug doesn't come back.
4. Strongly recommended: swallow client-disconnect tracebacks in `serve_review.py` (rough edge 2) — it's the only remaining thing likely to frighten a non-technical user into aborting a healthy review session.
