#!/usr/bin/env python3
"""Batch-process a whole study: find every audio+transcript pair under a folder
(sub-folders included), run the full review pipeline on each, and keep an Excel
status sheet you can paste into the shared Data Log.

Pairing: an audio file is matched to a .docx transcript in the SAME folder first
(exact stem, then closest stem), then to transcript_dir. Runs resume for free:
files whose .review.json already exists are skipped (re-run with --force).

    python src/batch.py                      # scan data/ (audio_dir + transcript_dir)
    python src/batch.py "data/my_study"        # scan one study folder
    python src/batch.py --dry-run            # only show the pairing, process nothing
    (or double-click  batch.command)

Output per file -> output/<stem>.review.{json,docx,html}; status -> output/data_log.xlsx.
A low match coverage (<0.7) usually means a WRONG PAIRING or very poor audio — check
those before trusting their review.
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from common import load_config, out_dirs

AUDIO_EXTS = {".m4a", ".wav", ".mp3", ".mp4", ".aac", ".flac", ".ogg", ".wma", ".webm"}
LOW_COVERAGE = 0.7


def _stem_sim(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _find_pairs(roots):
    """[(audio, transcript|None), ...] — transcript from the same folder if
    possible, else the closest stem anywhere under the scanned roots."""
    audios, docs = [], []
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        for p in sorted(root.rglob("*")):
            if p.name.startswith((".", "~$")) or not p.is_file():
                continue
            if p.suffix.lower() in AUDIO_EXTS:
                audios.append(p)
            elif p.suffix.lower() == ".docx" and ".review" not in p.name and ".corrected" not in p.name:
                docs.append(p)
    pairs = []
    for a in audios:
        local = [d for d in docs if d.parent == a.parent]
        pool = local or docs
        best, score = None, 0.0
        for d in pool:
            s = 1.0 if d.stem == a.stem else _stem_sim(d.stem, a.stem)
            if s > score:
                best, score = d, s
        pairs.append((a, best if score >= 0.5 else None))
    return pairs


def _fmt_dur(sec):
    if not sec:
        return ""
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _log_row(audio, review, dirs):
    import json
    stem = Path(audio).stem
    choices = dirs["reviews"] / f"{stem}.choices.json"
    reviewed = False
    if choices.exists():
        try:
            reviewed = bool(json.loads(choices.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            pass
    cov = review.get("match_coverage")
    return {
        "File": stem,
        "Duration": _fmt_dur(review.get("duration_seconds")),
        "Match coverage": cov,
        "Corrections": len(review.get("disagreements", [])),
        "Recovered": len(review.get("recovered", [])),
        "Omissions": len(review.get("omissions", [])),
        "Not heard": len(review.get("base_only", [])),
        "Overlaps": len(review.get("overlaps", [])),
        "Reviewed (choices saved)": "yes" if reviewed else "",
        "Final (.corrected.docx)": "yes" if (dirs["final"] / f"{stem}.corrected.docx").exists() else "",
        "Check pairing?": "CHECK" if (cov is not None and cov < LOW_COVERAGE) else "",
        "Processed at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def _write_log(rows, path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Data log"
    if rows:
        headers = list(rows[0].keys())
        ws.append(headers)
        for r in rows:
            ws.append([r.get(h) for h in headers])
        for col in ws.columns:
            width = max(len(str(c.value or "")) for c in col) + 2
            ws.column_dimensions[col[0].column_letter].width = min(width, 60)
    wb.save(path)


def main():
    ap = argparse.ArgumentParser(description="Batch-review every audio+transcript pair.")
    ap.add_argument("folder", nargs="?", default=None,
                    help="folder to scan recursively (default: audio_dir + transcript_dir)")
    ap.add_argument("--force", action="store_true", help="re-process even if a review exists")
    ap.add_argument("--dry-run", action="store_true", help="only show the pairing")
    args = ap.parse_args()

    cfg = load_config()
    dirs = out_dirs(cfg)
    roots = [args.folder] if args.folder else [cfg["audio_dir"], cfg["transcript_dir"]]
    pairs = _find_pairs(roots)

    print(f"found {len(pairs)} audio file(s):")
    for a, d in pairs:
        print(f"  {a.name}  <->  {d.name if d else '!! NO TRANSCRIPT FOUND'}")
    if args.dry_run:
        return

    import json
    from llm_review import ensure_llm_ready
    from pipeline import process_one

    ensure_llm_ready(cfg["llm_model"], cfg["ollama_url"])  # fail in seconds, not hours

    rows, failed = [], []
    todo = [(a, d) for a, d in pairs if d is not None]
    for n, (audio, base) in enumerate(todo, 1):
        review_json = dirs["reviews"] / f"{audio.stem}.review.json"
        print(f"\n[{n}/{len(todo)}] {audio.name}", flush=True)
        if review_json.exists() and not args.force:
            print("  already processed — skipping (use --force to redo)")
            review = json.loads(review_json.read_text(encoding="utf-8"))
        else:
            t0 = time.time()
            try:
                review = process_one(str(audio), str(base), cfg)
            except Exception as e:  # noqa: BLE001 — one bad file must not kill the night run
                print(f"  FAILED: {e}")
                failed.append(audio.name)
                continue
            print(f"  done in {time.time() - t0:.0f}s")
        rows.append(_log_row(audio, review, dirs))

    log = dirs["root"] / "data_log.xlsx"
    _write_log(rows, log)
    print(f"\n{len(rows)} file(s) in the log -> {log}")
    low = [r["File"] for r in rows if r["Check pairing?"]]
    if low:
        print(f"⚠️  low match coverage (<{LOW_COVERAGE}) — check audio/transcript pairing for: {', '.join(low)}")
    if failed:
        print(f"⚠️  failed: {', '.join(failed)}")
    unmatched = [a.name for a, d in pairs if d is None]
    if unmatched:
        print(f"⚠️  no transcript found for: {', '.join(unmatched)}")


if __name__ == "__main__":
    main()
