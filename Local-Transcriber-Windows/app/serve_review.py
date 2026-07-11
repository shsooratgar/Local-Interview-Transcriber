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
import re
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote
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


def _all_reviews():
    """Every processed interview's review.json, newest first, deduped."""
    seen, out = set(), []
    for p in sorted(list(REV.glob("*.review.json")) + list(OUT.glob("*.review.json")),
                    key=lambda p: p.stat().st_mtime, reverse=True):
        if p.name not in seen:
            seen.add(p.name)
            out.append(p)
    return out


def _find_review_json(stem):
    stem = Path(stem).name  # no path tricks
    for cand in (REV / f"{stem}.review.json", OUT / f"{stem}.review.json"):
        if cand.exists():
            return cand
    return None


def _interview_status(rj):
    """Review progress for the sidebar dot. A suggestion counts as decided when
    it has keep, drop, or a typed override — the same rule the page's tally and
    apply_docx use. none = untouched · wip = some decided · done = all decided."""
    try:
        r = json.loads(rj.read_text(encoding="utf-8"))
        total = sum(len(r.get(k) or [])
                    for k in ("disagreements", "recovered", "omissions", "base_only"))
    except Exception:  # noqa: BLE001
        return "none"
    if total == 0:
        return "done"  # nothing to decide
    stem = rj.name[: -len(".review.json")]
    decided = 0
    for cand in (REV / f"{stem}.choices.json", OUT / f"{stem}.choices.json"):
        if cand.exists():
            try:
                choices = json.loads(cand.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                break
            for v in choices.values():
                if isinstance(v, dict) and (
                        v.get("s") in ("keep", "drop")
                        or (v.get("m") == "txt" and (v.get("e") or "").strip())):
                    decided += 1
            break
    if decided <= 0:
        return "none"
    return "done" if decided >= total else "wip"


class Handler(SimpleHTTPRequestHandler):
    review_path = None

    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def _payload(self):
        n = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(n) or "{}")
        return data.get("stem"), data.get("decisions", {})

    def _review_for(self, stem):
        """The review a POST belongs to: the page sends its stem (sidebar lets the
        user switch interviews); fall back to the launch-time review."""
        rj = _find_review_json(stem) if stem else None
        return Path(rj) if rj else Path(self.review_path)

    def do_GET(self):
        path = unquote(self.path.split("?", 1)[0])
        if path in ("", "/"):  # bare 127.0.0.1:8765 -> newest interview
            reviews = _all_reviews()
            if reviews:
                stem = reviews[0].name[: -len(".review.json")]
                self.send_response(302)
                self.send_header("Location", "/reviews/" + quote(f"{stem}.review.html"))
                self.end_headers()
                return
        m = re.match(r"^/reviews/(.+)\.review\.html$", path)
        if m:  # regenerate the page fresh, with the current interview list in the sidebar
            rj = _find_review_json(m.group(1))
            if rj:
                stem = rj.name[: -len(".review.json")]
                try:
                    review = json.loads(rj.read_text(encoding="utf-8"))
                    interviews = [(p.name[: -len(".review.json")], _interview_status(p))
                                  for p in _all_reviews()]
                    write_html_report(review["audio"], review, REV / f"{stem}.review.html",
                                      interviews=interviews)
                except Exception as e:  # noqa: BLE001 — serve the existing file instead
                    print(f"  (could not refresh page: {e})", flush=True)
        super().do_GET()

    def do_POST(self):
        route = self.path.rstrip("/")
        try:
            stem, decisions = self._payload()
            review = json.loads(self._review_for(stem).read_text(encoding="utf-8"))
            if route == "/save":
                # autosave the current keep/drop/edit map next to the review (origin-independent)
                cp = _choices_path(review)
                cp.write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"  saved {len(decisions)} choice(s) -> {cp.name}", flush=True)
                self._json(200, {"ok": True, "saved": len(decisions)})
            elif route == "/apply":
                out_stem = Path(review["audio"]).stem
                out = DIRS["final"] / (out_stem + ".corrected.docx")
                changes = DIRS["changes"] / (out_stem + ".changes.docx")
                self._json(200, apply_decisions(review["base"], review, decisions, out,
                                                changes_path=changes))
            else:
                self.send_error(404)
        except Exception as e:  # noqa: BLE001
            self._json(500, {"error": str(e)})

    def log_message(self, *a):
        pass


class _QuietServer(ThreadingHTTPServer):
    """Swallow routine client-disconnect errors (browser seeking in the audio,
    tab closed, page refreshed) — the default handler prints a 20-line red
    traceback that makes non-technical users think the tool crashed."""

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def _serve(handler, port):
    """Bind the requested port; fall back to a random one if it is busy."""
    try:
        return _QuietServer(("127.0.0.1", port), handler)
    except OSError:
        srv = _QuietServer(("127.0.0.1", 0), handler)
        print(f"port {port} is busy — using random port {srv.server_address[1]} instead. "
              f"(Your choices still autosave to output/*.choices.json regardless.)")
        return srv


def main():
    ap = argparse.ArgumentParser(description="Serve the local review cockpit.")
    ap.add_argument("name", nargs="?", help="review name or .review.json (default: newest)")
    ap.add_argument("--port", type=int, default=None,
                    help=f"port to serve on (default: config review_port = {CFG.get('review_port', 8765)}). "
                         "Use a previous run's port to recover choices stranded in that origin's localStorage.")
    ap.add_argument("--pick", action="store_true",
                    help="when several interviews are processed, ask which one to open "
                         "(Enter = most recent). review.command uses this.")
    args = ap.parse_args()

    if args.name:
        review_path = _resolve_review(args.name)
    else:
        seen, reviews = set(), []
        for p in sorted(list(REV.glob("*.review.json")) + list(OUT.glob("*.review.json")),
                        key=lambda p: p.stat().st_mtime, reverse=True):
            if p.name not in seen:
                seen.add(p.name)
                reviews.append(p)
        if not reviews:
            raise SystemExit("No reviews in output/. Run the pipeline on a file first.")
        review_path = reviews[0]
        if args.pick and len(reviews) > 1:
            print("Which interview do you want to review?")
            for i, p in enumerate(reviews, 1):
                marker = "  (most recent)" if i == 1 else ""
                print(f"  [{i}] {p.name.replace('.review.json', '')}{marker}")
            choice = input("Number (just press Enter for the most recent): ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(reviews):
                review_path = reviews[int(choice) - 1]

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
