#!/usr/bin/env python3
"""Serve the review cockpit locally so the Apply button works — it POSTs your
keep/drop/edit decisions and writes a corrected .docx (original untouched).

    python src/serve_review.py "interview01"
    python src/serve_review.py "output/reviews/interview01.review.json"

Opens your browser to the viewer; click "Apply" -> output/<stem>.corrected.docx.
Audio also plays over http here (no local-file quirks). Ctrl-C to stop.
"""
from __future__ import annotations

import json
import sys
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

from apply_docx import apply_decisions
from common import load_config
from report_html import write_html_report

CFG = load_config()
OUT = Path(CFG["output_dir"])


def _resolve_review(arg):
    p = Path(arg)
    if p.suffix == ".json" and p.exists():
        return p
    cand = OUT / (Path(arg).stem.replace(".review", "") + ".review.json")
    if cand.exists():
        return cand
    raise SystemExit(f"Could not find a .review.json for: {arg}")


class Handler(SimpleHTTPRequestHandler):
    review_path = None

    def do_POST(self):
        if self.path.rstrip("/") != "/apply":
            self.send_error(404)
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            decisions = (json.loads(self.rfile.read(n) or "{}")).get("decisions", {})
            review = json.loads(Path(self.review_path).read_text())
            out = OUT / (Path(review["audio"]).stem + ".corrected.docx")
            res = apply_decisions(review["base"], review, decisions, out)
            payload = json.dumps(res).encode()
            self.send_response(200)
        except Exception as e:  # noqa: BLE001
            payload = json.dumps({"error": str(e)}).encode()
            self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


def main():
    if len(sys.argv) < 2:
        reviews = sorted(OUT.glob("*.review.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not reviews:
            raise SystemExit("No reviews in output/. Run the pipeline on a file first.")
        review_path = reviews[0]
    else:
        review_path = _resolve_review(sys.argv[1])
    review = json.loads(review_path.read_text())
    html = write_html_report(review["audio"], review,
                             OUT / (Path(review["audio"]).stem + ".review.html"))
    Handler.review_path = str(review_path)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(OUT)))
    url = f"http://127.0.0.1:{srv.server_address[1]}/{quote(html.name)}"
    print(f"Serving review at {url}\n(Ctrl-C to stop.)")
    webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
