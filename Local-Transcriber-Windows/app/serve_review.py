#!/usr/bin/env python3
"""Serve the review cockpit locally so the Apply button works — it POSTs your
keep/drop/edit decisions and writes a corrected .docx (original untouched).

    python src/serve_review.py "interview01"
    python src/serve_review.py "output/reviews/interview01.review.json"
    python src/serve_review.py "interview01" --port 54987   # recover choices left on an old port

Opens your browser to the viewer; click "Apply" -> output/<stem>.corrected.docx.

Your keep/drop/edit choices are autosaved server-side to output/<stem>.choices.json
(POST /save) and reloaded on open, so they survive across launches, port changes,
and even a different browser. The server also binds a FIXED port (config:
review_port, default 8765) so the browser origin — and its localStorage — stays
stable too. Pass --port <oldport> to re-open under a previous random port and pull
back choices that were stranded in that origin's localStorage.

Audio plays over http here (no local-file quirks). Ctrl-C to stop.
"""
from __future__ import annotations

import argparse
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote
import webbrowser

from apply_docx import apply_decisions
from common import load_config, out_dirs
from report_html import write_html_report

CFG = load_config()
DIRS = out_dirs(CFG)
OUT = DIRS["root"]      # server root — pages live under reviews/
REV = DIRS["reviews"]


def _resolve_review(arg):
    p = Path(arg)
    if p.suffix == ".json" and p.exists():
        return p
    name = Path(arg).stem.replace(".review", "") + ".review.json"
    for cand in (REV / name, OUT / name):  # new layout, then legacy flat
        if cand.exists():
            return cand
    raise SystemExit(f"Could not find a .review.json for: {arg}")


def _choices_path(review):
    return REV / (Path(review["audio"]).stem + ".choices.json")


class Handler(SimpleHTTPRequestHandler):
    review_path = None

    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def _body_decisions(self):
        n = int(self.headers.get("Content-Length", 0))
        return (json.loads(self.rfile.read(n) or "{}")).get("decisions", {})

    def do_POST(self):
        route = self.path.rstrip("/")
        try:
            review = json.loads(Path(self.review_path).read_text(encoding="utf-8"))
            if route == "/save":
                # autosave the current keep/drop/edit map next to the review (origin-independent)
                decisions = self._body_decisions()
                cp = _choices_path(review)
                cp.write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"  saved {len(decisions)} choice(s) -> {cp.name}", flush=True)
                self._json(200, {"ok": True, "saved": len(decisions)})
            elif route == "/apply":
                decisions = self._body_decisions()
                stem = Path(review["audio"]).stem
                out = DIRS["final"] / (stem + ".corrected.docx")
                changes = DIRS["changes"] / (stem + ".changes.docx")
                self._json(200, apply_decisions(review["base"], review, decisions, out,
                                                changes_path=changes))
            else:
                self.send_error(404)
        except Exception as e:  # noqa: BLE001
            self._json(500, {"error": str(e)})

    def log_message(self, *a):
        pass


def _serve(handler, port):
    """Bind the requested port; fall back to a random one if it is busy."""
    try:
        return ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError:
        srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        print(f"port {port} is busy — using random port {srv.server_address[1]} instead. "
              f"(Your choices still autosave to output/*.choices.json regardless.)")
        return srv


def main():
    ap = argparse.ArgumentParser(description="Serve the local review cockpit.")
    ap.add_argument("name", nargs="?", help="review name or .review.json (default: newest)")
    ap.add_argument("--port", type=int, default=None,
                    help=f"port to serve on (default: config review_port = {CFG.get('review_port', 8765)}). "
                         "Use a previous run's port to recover choices stranded in that origin's localStorage.")
    args = ap.parse_args()

    if args.name:
        review_path = _resolve_review(args.name)
    else:
        reviews = sorted(list(REV.glob("*.review.json")) + list(OUT.glob("*.review.json")),
                         key=lambda p: p.stat().st_mtime, reverse=True)
        if not reviews:
            raise SystemExit("No reviews in output/. Run the pipeline on a file first.")
        review_path = reviews[0]

    review = json.loads(review_path.read_text(encoding="utf-8"))
    html = write_html_report(review["audio"], review,
                             REV / (Path(review["audio"]).stem + ".review.html"))
    Handler.review_path = str(review_path)

    port = args.port if args.port is not None else CFG.get("review_port", 8765)
    srv = _serve(partial(Handler, directory=str(OUT)), port)
    url = f"http://127.0.0.1:{srv.server_address[1]}/{quote(html.relative_to(OUT).as_posix())}"
    print(f"Serving review at {url}\n(Ctrl-C to stop.)")
    webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
