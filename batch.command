#!/bin/bash
# Double-click to batch-process ALL audio+transcript pairs under data/
# (or drop a folder path onto this file / pass one as argument).
# Already-processed files are skipped, so you can re-run it anytime.
# Status sheet: output/data_log.xlsx
cd "$(cd "$(dirname "$0")" && pwd)" || exit 1
PYBIN="$HOME/miniconda3/envs/transcriber/bin/python"
[ -x "$PYBIN" ] || PYBIN="python"
"$PYBIN" src/batch.py "$@"
echo
read -r -p "Done. Press Enter to close…"
