#!/usr/bin/env python3
"""Standalone, offline HTML review cockpit.

- Audio player on top; every suggested correction / omission has a clickable
  time that seeks the audio to that exact moment.
- keep / drop triage on each item, a running tally, and "Copy accepted" to
  export the ones you kept.
Self-contained: inline CSS + JS, audio referenced by relative path, no internet.
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
 header{position:sticky;top:0;background:#fff;border-bottom:1px solid #ddd;padding:12px 20px;box-shadow:0 1px 4px rgba(0,0,0,.06);z-index:5}
 header b{font-size:16px}
 audio{width:100%;margin-top:10px}
 main{max-width:980px;margin:0 auto;padding:20px}
 h2{margin-top:30px;border-bottom:2px solid #eee;padding-bottom:5px;font-size:17px}
 h2 small{color:#888;font-weight:400;font-size:13px}
 table{border-collapse:collapse;width:100%}
 th,td{text-align:left;padding:7px 9px;border-bottom:1px solid #eee;vertical-align:top}
 th{color:#555;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
 .t{white-space:nowrap;color:#0066cc;cursor:pointer;font-variant-numeric:tabular-nums;width:56px;font-weight:600}
 .t:hover{text-decoration:underline}
 .sug{color:#137a3e}
 .dec{white-space:nowrap;width:112px}
 .dec button{font-size:12px;padding:3px 9px;margin-right:4px;border:1px solid #ccc;background:#fff;border-radius:6px;cursor:pointer}
 .dec button.on{border-color:#0066cc;background:#eaf3ff;font-weight:600}
 tr[data-state=keep]{background:#eafaf0}
 tr[data-state=drop]{opacity:.45;text-decoration:line-through}
 .pill{display:inline-block;background:#eef2ff;color:#334;border-radius:11px;padding:2px 10px;margin-left:6px;font-size:12px}
 .note{color:#555;font-size:13px;background:#fff;border:1px solid #eee;border-radius:8px;padding:10px 12px}
 .bar{background:#fff;border:1px solid #e3e3e3;border-radius:8px;padding:8px 12px;margin:10px 0;display:flex;align-items:center;gap:12px}
 .bar button{font-size:13px;padding:4px 12px;border:1px solid #0066cc;background:#0066cc;color:#fff;border-radius:6px;cursor:pointer}
</style></head><body>
<header>
 <b>__TITLE__</b> __PILLS__
 <audio id="p" controls preload="metadata" src="__AUDIO__"></audio>
</header>
<main>
 <p class="note">Click any blue time to hear that moment, then mark each suggestion <b>keep</b> or <b>drop</b>. Use "Copy accepted" to export the ones you kept. Nothing here changes your transcript.</p>
 <h2>Summary</h2>
 <p>__SUMMARY__</p>
 <ul>__TOPICS__</ul>
 <h2>Suggested corrections</h2>
 <div class="bar"><span id="tally">…</span><button onclick="copyAccepted()">Copy accepted</button></div>
 <table><tr><th class="t">time</th><th>speaker</th><th>in transcript</th><th>suggested (from audio)</th><th>conf</th><th></th></tr>__CORR__</table>
 <h2>Possible omissions <small>(heard in audio, missing from transcript)</small></h2>
 <table><tr><th class="t">time</th><th>heard in audio</th><th></th></tr>__OM__</table>
 <h2>Overlapping speech to verify</h2>
 <ul>__OV__</ul>
</main>
<script>
 var p=document.getElementById('p');
 function seek(s){ if(s===null||s===undefined) return; p.currentTime=s; p.play(); }
 function mark(btn,val){ var tr=btn.closest('tr'); var nv=tr.getAttribute('data-state')===val?'':val; tr.setAttribute('data-state',nv); tr.querySelectorAll('.dec button').forEach(function(b){ b.classList.toggle('on', b===btn && nv!==''); }); updateTally(); }
 function updateTally(){ var rows=document.querySelectorAll('tr[data-flag]'); var k=0,d=0; rows.forEach(function(r){var s=r.getAttribute('data-state'); if(s==='keep')k++; else if(s==='drop')d++;}); document.getElementById('tally').textContent='kept '+k+' · dropped '+d+' · '+(rows.length-k-d)+' to review'; }
 function copyAccepted(){ var out=[]; document.querySelectorAll('tr[data-flag]').forEach(function(r){ if(r.getAttribute('data-state')==='keep') out.push((r.getAttribute('data-base')||'')+'  ->  '+(r.getAttribute('data-sug')||'')); }); if(!out.length){ alert('Nothing marked keep yet.'); return; } navigator.clipboard.writeText(out.join(String.fromCharCode(10))).then(function(){ alert('Copied '+out.length+' accepted item(s) to clipboard.'); }); }
 updateTally();
</script>
</body></html>"""


def _mmss(s):
    if s is None:
        return "—"
    s = int(s)
    return f"{s // 60:02d}:{s % 60:02d}"


def _esc(x):
    return html.escape("" if x is None else str(x))


def _click(start):
    return f' onclick="seek({start})"' if start is not None else ""


def _dec():
    return ('<td class="dec"><button onclick="mark(this,\'keep\')">keep</button>'
            '<button onclick="mark(this,\'drop\')">drop</button></td>')


def write_html_report(audio_path, review, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    audio_rel = quote(os.path.relpath(Path(audio_path).resolve(), out_path.parent))
    summ = review.get("summary", {}) or {}

    corr = ""
    for d in review.get("disagreements", []):
        base = _esc(d.get("base_text"))
        sug = _esc((d.get("llm") or {}).get("correction") or d.get("audio_text"))
        corr += (f'<tr data-flag data-base="{base}" data-sug="{sug}">'
                 f'<td class="t"{_click(d.get("start"))}>{_mmss(d.get("start"))}</td>'
                 f'<td>{_esc(d.get("speaker"))}</td><td>{base}</td>'
                 f'<td class="sug">{sug}</td>'
                 f'<td>{_esc((d.get("llm") or {}).get("confidence"))}</td>{_dec()}</tr>')
    corr = corr or '<tr><td colspan="6">None found.</td></tr>'

    om = ""
    for o in review.get("omissions", []):
        txt = _esc(o.get("audio_text"))
        om += (f'<tr data-flag data-base="[omission]" data-sug="{txt}">'
               f'<td class="t"{_click(o.get("start"))}>{_mmss(o.get("start"))}</td>'
               f'<td>{txt}</td>{_dec()}</tr>')
    om = om or '<tr><td colspan="3">None found.</td></tr>'

    ov = "".join(f'<li><b>{_esc(o.get("speaker"))}:</b> {_esc(o.get("text"))}</li>'
                 for o in review.get("overlaps", [])) or "<li>None marked.</li>"
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
