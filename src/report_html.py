#!/usr/bin/env python3
"""Write a standalone, offline HTML review — the fast-review 'cockpit'.

Click any flagged row to jump the audio player to that moment. Self-contained:
inline CSS + JS, audio referenced by relative path, no internet, no tracking.
"""
from __future__ import annotations

import html
import os
from pathlib import Path
from urllib.parse import quote

TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8">
<title>Review — __TITLE__</title>
<style>
 body{font:15px/1.6 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;margin:0;color:#1a1a1a;background:#fafafa}
 header{position:sticky;top:0;background:#fff;border-bottom:1px solid #ddd;padding:12px 20px;box-shadow:0 1px 4px rgba(0,0,0,.06)}
 header b{font-size:16px}
 audio{width:100%;margin-top:10px}
 main{max-width:920px;margin:0 auto;padding:20px}
 h2{margin-top:30px;border-bottom:2px solid #eee;padding-bottom:5px;font-size:17px}
 h2 small{color:#888;font-weight:400;font-size:13px}
 table{border-collapse:collapse;width:100%}
 th,td{text-align:left;padding:7px 9px;border-bottom:1px solid #eee;vertical-align:top}
 th{color:#555;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
 .t{white-space:nowrap;color:#0066cc;font-variant-numeric:tabular-nums;width:56px;font-weight:600}
 tr.clk{cursor:pointer} tr.clk:hover{background:#eaf3ff}
 .note{color:#555;font-size:13px;background:#fff;border:1px solid #eee;border-radius:8px;padding:10px 12px}
 .pill{display:inline-block;background:#eef2ff;color:#334;border-radius:11px;padding:2px 10px;margin-left:6px;font-size:12px}
 ul{margin:6px 0}
</style></head><body>
<header>
 <b>__TITLE__</b> __PILLS__
 <audio id="p" controls preload="metadata" src="__AUDIO__"></audio>
</header>
<main>
 <p class="note">Automatic suggestions — click any row with a time to hear that exact moment, then accept or reject. Nothing here changes your transcript.</p>
 <h2>Summary</h2>
 <p>__SUMMARY__</p>
 <ul>__TOPICS__</ul>
 <h2>Suggested corrections</h2>
 <table><tr><th class="t">time</th><th>in transcript</th><th>suggested (from audio)</th><th>why</th><th>conf</th></tr>__CORR__</table>
 <h2>Possible omissions <small>(heard in audio, missing from transcript)</small></h2>
 <table><tr><th class="t">time</th><th>heard in audio</th></tr>__OM__</table>
 <h2>Overlapping speech to verify</h2>
 <ul>__OV__</ul>
</main>
<script>
 var p=document.getElementById('p');
 function seek(s){ if(s===null||s===undefined) return; p.currentTime=s; p.play(); }
</script>
</body></html>"""


def _mmss(s):
    if s is None:
        return "—"
    s = int(s)
    return f"{s // 60:02d}:{s % 60:02d}"


def _esc(x):
    return html.escape("" if x is None else str(x))


def _row(start, cells):
    onclick = f' onclick="seek({start})"' if start is not None else ""
    tds = "".join(f"<td>{c}</td>" for c in cells)
    return f'<tr class="clk"{onclick}><td class="t">{_mmss(start)}</td>{tds}</tr>'


def write_html_report(audio_path, review, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    audio_rel = quote(os.path.relpath(Path(audio_path).resolve(), out_path.parent))
    summ = review.get("summary", {}) or {}

    corr = "".join(
        _row(d.get("start"), [
            _esc(d.get("base_text")),
            _esc((d.get("llm") or {}).get("correction") or d.get("audio_text")),
            _esc((d.get("llm") or {}).get("reason")),
            _esc((d.get("llm") or {}).get("confidence")),
        ]) for d in review.get("disagreements", [])
    ) or '<tr><td colspan="5">None found.</td></tr>'

    om = "".join(
        _row(o.get("start"), [_esc(o.get("audio_text"))]) for o in review.get("omissions", [])
    ) or '<tr><td colspan="2">None found.</td></tr>'

    ov = "".join(
        f'<li><b>{_esc(o.get("speaker"))}:</b> {_esc(o.get("text"))}</li>'
        for o in review.get("overlaps", [])
    ) or "<li>None marked.</li>"

    topics = "".join(f"<li>{_esc(t)}</li>" for t in summ.get("topics", []))
    pills = (f'<span class="pill">match {_esc(review.get("match_coverage"))}</span>'
             f'<span class="pill">{len(review.get("disagreements", []))} corrections</span>'
             f'<span class="pill">{len(review.get("omissions", []))} omissions</span>'
             f'<span class="pill">{len(review.get("overlaps", []))} overlaps</span>')

    doc = (TEMPLATE
           .replace("__TITLE__", _esc(Path(audio_path).name))
           .replace("__PILLS__", pills)
           .replace("__AUDIO__", audio_rel)
           .replace("__SUMMARY__", _esc(summ.get("summary")))
           .replace("__TOPICS__", topics)
           .replace("__CORR__", corr)
           .replace("__OM__", om)
           .replace("__OV__", ov))
    out_path.write_text(doc, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    import json
    import sys
    review = json.loads(Path(sys.argv[2]).read_text())
    print("saved ->", write_html_report(sys.argv[1], review, sys.argv[3]))
