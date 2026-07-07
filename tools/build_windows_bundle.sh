#!/bin/bash
# Build/refresh the Windows bundle from src/ — the ONLY sanctioned way to update it.
# Usage:  ./tools/build_windows_bundle.sh          sync + verify + rebuild zip
#         ./tools/build_windows_bundle.sh --check  verify only (CI-style drift check)
#
# See WINDOWS.md for the full developer guide.
set -euo pipefail
cd "$(dirname "$0")/.."

BUNDLE="Local-Transcriber-Windows"
APP="$BUNDLE/app"
# dev-only modules that intentionally do NOT ship in the bundle
EXCLUDE_MODULES="check_setup.py diff_flag.py fetch_testdata.py"

PYBIN="$HOME/miniconda3/envs/transcriber/bin/python"
[ -x "$PYBIN" ] || PYBIN="python3"

skip() { for e in $EXCLUDE_MODULES; do [ "$1" = "$e" ] && return 0; done; return 1; }

if [ "${1:-}" = "--check" ]; then
  fail=0
  for f in src/*.py; do
    b=$(basename "$f"); skip "$b" && continue
    if [ ! -f "$APP/$b" ]; then echo "MISSING in bundle: $b"; fail=1
    elif ! diff -q "$f" "$APP/$b" >/dev/null; then echo "DRIFTED: $b"; fail=1; fi
  done
  for f in "$APP"/*.py; do
    b=$(basename "$f")
    [ -f "src/$b" ] || { echo "ORPHAN in bundle (no src/ counterpart): $b"; fail=1; }
  done
  [ $fail -eq 0 ] && echo "OK: bundle is in sync with src/"
  exit $fail
fi

echo "[1/4] sync src/ -> $APP/"
for f in src/*.py; do
  b=$(basename "$f"); skip "$b" && continue
  cp "$f" "$APP/$b"
done
for f in "$APP"/*.py; do
  b=$(basename "$f")
  [ -f "src/$b" ] || { echo "  removing orphan $b (deleted from src/)"; rm "$f"; }
done

echo "[2/4] compile check"
"$PYBIN" -m py_compile "$APP"/*.py
rm -rf "$APP/__pycache__"

echo "[3/4] verify no data/junk will ship"
for d in audio transcripts output; do
  extra=$(find "$BUNDLE/$d" -type f ! -name "*.txt" 2>/dev/null || true)
  [ -z "$extra" ] || { echo "REFUSING to zip — real data in $BUNDLE/$d:"; echo "$extra"; exit 1; }
done

echo "[4/4] rebuild $BUNDLE.zip"
rm -f "$BUNDLE.zip"
zip -rq "$BUNDLE.zip" "$BUNDLE" -x "*.DS_Store" "*__pycache__*" "*/.venv/*" "*/output/*"
echo "done: $(du -h "$BUNDLE.zip" | cut -f1) $(unzip -l "$BUNDLE.zip" | awk 'END{print $2}') files"
