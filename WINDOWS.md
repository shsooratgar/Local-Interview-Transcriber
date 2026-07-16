# Windows Version — Developer Guide

Audience: future maintainers of this repo. Read this **before**
touching anything under `Local-Transcriber-Windows/`. It explains how the
Windows version relates to the Mac version, why it looks the way it does, and
the hard-won rules whose violation has already broken it once in the field.

---

## 1. Big picture: one codebase, two deployments

There is **no Windows fork**. All Python logic lives in `src/` — the single
source of truth. The Windows "version" is a distribution kit:

```
Local-Transcriber-Windows/
├── 1 - SETUP (run once).bat      installer (winget: Python 3.11, ffmpeg, Ollama; venv; models)
├── 2 - PROCESS (double-click).bat   run pipeline on ONE audio+transcript, then open review
├── INSTRUCTIONS.txt              for the non-technical end user
├── config.yaml                   the ONLY intended divergence point (see §4)
├── audio/  transcripts/          the user drops ONE file in each
├── output/                       created at runtime (cache/ reviews/ final/ changes/)
└── app/                          byte-for-byte COPY of src/*.py  (see §2)
    ├── requirements-windows.txt  pip deps (no mlx-whisper; faster-whisper instead)
    ├── glossary/                 domain terms
    └── .venv/                    created by SETUP on the user's machine (never ship it)
```

The kit is zipped as `Local-Transcriber-Windows.zip` (repo root, committed)
and shared with collaborators via Drive. Its design constraints: the end user
is **non-technical** (double-click only, no terminal), on a **CPU-only laptop**
(no CUDA), possibly behind OneDrive, possibly moving folders around.

## 2. The sync contract (the #1 divergence risk)

`app/*.py` must be **byte-identical** to `src/*.py`, except three dev-only
modules that intentionally don't ship: `check_setup.py`, `diff_flag.py`,
`fetch_testdata.py`.

Never edit `app/*.py` directly. The workflow for every code change:

```bash
# edit src/, test, then:
./tools/build_windows_bundle.sh          # sync + compile check + junk guard + rebuild zip
./tools/build_windows_bundle.sh --check  # drift check only (run in reviews/CI)
```

The script also refuses to zip if real data (non-`.txt` files) sits in the
bundle's `audio/`, `transcripts/` or `output/` — confidential-data guard.

If you add a new module to `src/`, decide whether the bundle needs it; if yes,
copy it once by hand (the script syncs only files already present in `app/`)
and it is tracked from then on. If a module is deleted from `src/`, the script
removes the orphan from `app/`.

## 3. How the SAME code runs on both platforms

Three mechanisms — understand all three before refactoring:

**a) `common.ROOT` is relative to the code's location.**
`ROOT = Path(__file__).resolve().parent.parent` — the parent of the folder
containing `common.py`. On Mac that's the repo root; in the bundle it's the
bundle root (parent of `app/`). All relative config paths (`audio_dir`,
`output_dir`, `glossary_file`, `config.yaml` itself) resolve against ROOT.
This is why the identical file works in both trees. **Do not "simplify" ROOT.**

**b) The Whisper backend is a config switch, not a code branch.**
`src/transcribe.py` is the only file with platform-specific paths:
`_transcribe_mlx()` (mlx-whisper, Apple-Silicon GPU) vs `_transcribe_faster()`
(faster-whisper / CTranslate2, CPU or NVIDIA). Selection: `whisper_backend:
mlx|faster` in config. Both backends emit the identical normalized dict
(segments → words with `word/start/end/prob`), so everything downstream is
platform-agnostic. **Imports are lazy** — `import mlx_whisper` sits inside
`_transcribe_mlx`, `from faster_whisper import ...` inside `_faster_model` —
because each platform has only one of them installed. Keep it that way.

**c) The careful re-listen has TWO model keys.**
`whisper_model_careful` (an mlx repo id on Mac) is the master ON/OFF switch —
empty string disables the re-listen pass everywhere. When the backend is
`faster`, the actual model name comes from `whisper_model_careful_faster`
(default `large-v3`). The Windows config sets `whisper_model_careful:
large-v3` — the value only needs to be non-empty there; the `_faster` key is
what is loaded. `transcribe_clip()` shells out to **ffmpeg** (installed by
SETUP via winget on Windows, brew on Mac) and fails OPEN: if ffmpeg or the
model errors, flags pass through unverified instead of crashing.

## 4. Intended differences (config + launchers ONLY)

| | Mac (repo) | Windows (bundle) |
|---|---|---|
| Whisper engine | mlx-whisper (GPU via Metal) | faster-whisper / CTranslate2 (CPU, int8) |
| First-pass model | `mlx-community/whisper-large-v3-turbo` | `large-v3` |
| Careful model | `mlx-community/whisper-large-v3-mlx` | `large-v3` (via `_careful_faster`) |
| LLM | `qwen2.5:14b` | **`qwen2.5:7b`** (CPU-viable; SETUP pulls exactly this) |
| Python env | conda env `transcriber` (user-managed) | `app/.venv` (SETUP-managed) |
| Launchers | `review.command`, `batch.command` | `1 - SETUP.bat`, `2 - PROCESS.bat` |
| Config file | repo-root `config.yaml` (falls back to `config.example.yaml`) | bundle-root `config.yaml` (ships in zip) |
| Data location | `data/audio/`, `data/transcripts/` (many files, batch) | `audio/`, `transcripts/` (ONE file at a time) |
| Speed (1 h interview) | ~10–20 min | **a few hours** (CPU) |

Anything else that differs between the trees is a bug — run the drift check.

Two consequences worth remembering:
- **LLM prompts must stay 7b-compatible.** Every prompt is used by both
  qwen2.5:14b and qwen2.5:7b (all calls use Ollama `format: "json"` and the
  parsers reject non-dict output). If you enrich a prompt, smoke-test it on
  7b (`ollama pull qwen2.5:7b`, then run the pipeline on
  `data/testsets/sample_audio.wav`).
- **If you change the LLM model in `config.yaml`, change the `ollama pull`
  line in SETUP.bat to match** — a mismatch means a crash at review time on a
  fresh install.

## 5. The .bat launchers — why they look the way they do

`cmd.exe` is a minefield; these rules are encoded in the current files:

- **Never `call activate.bat`.** venv activation scripts hard-code the
  absolute path at creation time; the user MOVED the folder (OneDrive → C:\)
  and every `python` call silently fell back to the bare system Python
  (`ModuleNotFoundError: tqdm`, July 2026). Both launchers instead call
  `set "PY=%~dp0app\.venv\Scripts\python.exe"` and use `"%PY%"` everywhere —
  a venv invoked by its own python.exe survives folder moves.
- **Self-healing venv check**: SETUP tests for
  `app\.venv\Scripts\python.exe` (not the folder) so a half-created venv is
  repaired by re-running SETUP, not skipped forever.
- **Ollama preflight**: the silent winget install doesn't always start the
  Ollama service; both launchers run `ollama list || start "" /MIN ollama serve`
  before anything that needs it.
- `PROCESS` uses `setlocal enabledelayedexpansion` + `!AUDIO!` because the
  file variables are set inside `for` loops. If you add `echo` lines there,
  remember `!` is special under delayed expansion.
- Inside parenthesized `if (...)` blocks, `echo` text must contain **NO
  unquoted parentheses at all** — balance does NOT protect you (a previous
  version of this document claimed it did; the resulting bug killed SETUP
  silently after pip on every fresh PC — TEST-REPORT.md BUG 1, July 2026).
  cmd aborts the whole batch at parse time with `. was unexpected at this
  time.`. Safe forms: parens inside double quotes (`"1 - SETUP (run once)"`),
  escaped `^)`, or no parens. Empirically verified on real Windows.
- Corollary: **.bat edits cannot be validated on macOS.** Lint by these rules
  conservatively, but any non-trivial launcher change needs a run on a real
  Windows machine (see TEST-REPORT.md for the field-test recipe).
- Error paths end with `pause` so the non-technical user sees the `[X]`
  message instead of a vanishing window. Keep that pattern.
- SETUP is **re-runnable by design** ("if it stops, run it again") — winget
  installs are idempotent, the venv self-heals, model pulls resume.

## 6. Hard-won portability rules (violating these broke production)

1. **Every file read/write must pass `encoding="utf-8"`** —
   `read_text(encoding="utf-8")`, `write_text(..., encoding="utf-8")`, same
   for `open()`. Windows Python 3.11 defaults to cp1252; the first Cyrillic
   Whisper hallucination crashes the save AFTER a multi-hour transcription.
   Fixed repo-wide in July 2026; any new IO call is a regression risk.
   Check: `grep -n "read_text()\|write_text(json" src/*.py` → must be empty.
2. **Never rewrite fonts in generated documents.** A normalization pass
   (Play/Aptos → Calibri) was added and then REMOVED: it changed how the
   documents render for the collaborator who owns the originals. The
   Word-on-Mac "replace fonts" dialog is solved by installing Aptos/Play
   locally on the Mac, never by touching shared files.
3. **Model caches live outside the bundle** — Hugging Face:
   `%USERPROFILE%\.cache\huggingface`, Ollama: `%USERPROFILE%\.ollama`.
   Replacing/deleting the bundle folder does NOT re-download models; say so
   in support emails, it changes the user's willingness to reinstall.
4. **Legacy-layout fallbacks exist on purpose**: `cached_transcribe()` and
   the careful-cache lookup check the flat pre-July-2026 `output/` root
   before assuming `output/cache/`. Don't remove them until every install
   (incl. collaborators') has re-processed everything.
5. **Advise against running from OneDrive/Dropbox folders** (sync locks,
   placeholder hydration, venv churn) — and remember the folder may be moved
   anyway; nothing may depend on its absolute path.
6. **Long runs die from sleep, not bugs.** A run that vanished without an
   `[X]` message = Windows went to sleep. It's in INSTRUCTIONS.txt; keep it.

## 7. Testing the Windows version on a Mac (dress-rehearsal recipe)

Everything except `cmd.exe`, winget, and true Windows perf can be validated
on macOS, because faster-whisper is cross-platform:

```bash
SIM=/tmp/sim && rm -rf $SIM && cp -R Local-Transcriber-Windows $SIM && rm -rf $SIM/output
cp data/testsets/sample_audio.wav        $SIM/audio/
cp data/testsets/sample_transcript.docx  $SIM/transcripts/
~/miniconda3/envs/transcriber/bin/python -m venv $SIM/app/.venv
$SIM/app/.venv/bin/pip install -q -r $SIM/app/requirements-windows.txt
# shrink models for the test (code path is identical):
#   config.yaml: whisper_model_faster: tiny / whisper_model_careful: tiny
#   + add: whisper_model_careful_faster: tiny        llm stays qwen2.5:7b
cd $SIM && ./app/.venv/bin/python app/pipeline.py "audio/sample_audio.wav" \
        --base "transcripts/sample_transcript.docx"          # ← what PROCESS.bat runs
BROWSER=true ./app/.venv/bin/python app/serve_review.py --port 8971 &
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8971/reviews/sample_audio.review.html
curl -s -X POST http://127.0.0.1:8971/apply -H "Content-Type: application/json" \
     -d '{"decisions":{"c0":{"s":"keep","e":"","m":"btn"}}}'  # → final/ + changes/ docs
```

Checklist: outputs land in `output/{cache,reviews,final,changes}`, nothing at
the output root; `/apply` returns `"header": "ok"`; the final docx's font set
is identical to the base docx's; a second pipeline run completes in seconds
(cache reuse). The `.bat` files can only be linted (§5 rules) — if you change
them, walk every parenthesis and variable expansion by hand.

## 8. Support playbook (what the field has already shown)

| Symptom on the user's PC | Cause | Fix |
|---|---|---|
| SETUP window vanishes right after the pip step, no `[X]`, models missing → later 404 at review | BUG 1 (zips before 2026-07-09): unquoted parens in an echo inside a block killed the batch at parse time | update to a fixed zip / fixed SETUP.bat; root cause of BOTH July 404 incidents |
| `ModuleNotFoundError` at line 1 of anything | moved folder with pre-July bats (activate.bat) | replace bats / re-run SETUP; new bats immune |
| Audio ▶ buttons dead; a "Download File Info" dialog pops up instead | a download manager (IDM etc.) intercepts the playback .mp3 | cancel the dialog; add 127.0.0.1 to the manager's exceptions or use a browser without the extension |
| Yellow `huggingface_hub` symlink warnings | normal on Windows | ignore |
| "You are sending unauthenticated requests to the HF Hub" | normal | ignore |
| Window looks frozen on first run | 3 GB model download | wait; happens once |
| Run vanished overnight, no `[X]` | Windows sleep | power settings → sleep Never; re-run |
| `404 Not Found … /api/generate` | LLM model missing from the Ollama store (July 2026: cost a full CPU run) | pipeline now verifies + auto-pulls the model at START (`ensure_llm_ready`); manual: `ollama pull <llm_model>` |
| Crash at "reviewing" stage (other) | Ollama service died mid-run / model name mismatch with SETUP pull | launcher preflight starts the service; keep `llm_model` == SETUP's pull; transcription + re-listen caches survive (saved incrementally), so a re-run resumes in minutes |
| Everything extremely slow | 8 GB RAM: large-v3 (~3 GB) + qwen 7b (~4.5 GB) contend | `whisper_model_faster: medium` in config.yaml |

## 9. Known gaps / future work

- ~~`batch.py` ships in the bundle but has no .bat launcher~~ — added 2026-07-16
  as `3 - PROCESS ALL (batch).bat`: shows the pairing via `--dry-run`, asks for
  confirmation (multi-hour CPU runs!), processes everything with resume-skip,
  writes `output\data_log.xlsx`, then starts the review server. Accepts a
  dragged-on folder as argument. Mind the runtime on CPU: a handful of
  one-hour interviews is an overnight-to-days job.
- `check_setup.py` (Mac toolchain checker) has no Windows counterpart; SETUP's
  own error branches are the current equivalent.
- The zip is a committed binary artifact; if the repo ever goes properly
  multi-developer, move it to GitHub Releases and keep only the folder in git.
- Speaker verification by voice (pyannote) is a promised future feature
  (README status) — if added, remember the bundle user has no GPU and no
  HF account; it likely stays Mac-only, which is fine: the Mac side produces,
  Windows side reviews.
