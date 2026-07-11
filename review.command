#!/bin/bash
# Double-click to open the transcript review (with working "Apply") in your browser.
# Serves the most recently processed file, or pass a name:  review.command "interview01"
# Close the Terminal window when you're done to stop the server.
cd "$(cd "$(dirname "$0")" && pwd)" || exit 1
PYBIN="$HOME/miniconda3/envs/transcriber/bin/python"
[ -x "$PYBIN" ] || PYBIN="python"
# (interviews are switched inside the page via the left sidebar)
exec "$PYBIN" src/serve_review.py "$@"
