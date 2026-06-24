#!/usr/bin/env python3
"""Standalone, offline HTML review cockpit.

- Audio player on top; every suggested correction / omission has a small ▶ play
  button and a clickable time that seek the audio to ~5s before that moment.
- keep / drop triage, plus a "your correction" box per row for when both the
  transcript and the audio suggestion are wrong (typing auto-keeps the row).
- A running tally, and "Copy accepted" exports your edit (or the suggestion).

For reliable local playback the audio is transcoded to a small mono .mp3 placed
NEXT TO the html (same folder, bare filename) — browsers refuse cross-folder
file:// media and many won't decode .m4a/AAC. Falls back to a relative path if
ffmpeg isn't available.
"""
from __future__ import annotations

import html
import os
import shutil
import subprocess
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
 main{max-width:1100px;margin:0 auto;padding:20px}
 h2{margin-top:30px;border-bottom:2px solid #eee;padding-bottom:5px;font-size:17px}
 h2 small{color:#888;font-weight:400;font-size:13px}
 table{border-collapse:collapse;width:100%}
 th,td{text-align:left;padding:7px 9px;border-bottom:1px solid #eee;vertical-align:top}
 th{color:#555;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
 .t{white-space:nowrap;width:96px}
 .play{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;margin-right:7px;padding:0;border:1px solid #cdd6e4;background:#fff;color:#0066cc;border-radius:50%;cursor:pointer;font-size:9px;line-height:1;vertical-align:middle}
 .play:hover{background:#0066cc;color:#fff;border-color:#0066cc}
 .ts{color:#0066cc;cursor:pointer;font-variant-numeric:tabular-nums;font-weight:600;vertical-align:middle}
 .ts:hover{text-decoration:underline}
 .sug{color:#137a3e}
 .edit{width:170px;font-size:13px;padding:4px 6px;border:1px solid #cdd6e4;border-radius:6px}
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
 <p class="note">Hit ▶ (or click the blue time) to hear that moment — playback starts ~5s earlier for context. Mark each row <b>keep</b> or <b>drop</b>; if both the transcript and the suggestion are wrong, type your own in <b>your correction</b> (that auto-keeps the row). "Copy accepted" exports everything you kept. Nothing here changes your transcript.</p>
 <h2>Summary</h2>
 <p>__SUMMARY__</p>
 <ul>__TOPICS__</ul>
 <h2>Suggested corrections</h2>
 <div class="bar"><span id="tally">…</span><button onclick="copyAccepted()">Copy accepted</button></div>
 <table><tr><th class="t">time</th><th>speaker</th><th>in transcript</th><th>suggested (from audio)</th><th>conf</th><th>your correction</th><th></th></tr>__CORR__</table>
 <h2>Possible omissions <small>(heard in audio, missing from transcript)</small></h2>
 <table><tr><th class="t">time</th><th>heard in audio</th><th>your correction</th><th></th></tr>__OM__</table>
 <h2>Overlapping speech to verify</h2>
 <ul>__OV__</ul>
</main>
<script>
 var p=document.getElementById('p');
 var LEAD=5;
 function seek(s){ if(s===null||s===undefined) return; p.currentTime=Math.max(0,s-LEAD); p.play(); }
 function mark(btn,val){ var tr=btn.closest('tr'); var nv=tr.getAttribute('data-state')===val?'':val; tr.setAttribute('data-state',nv); tr.querySelectorAll('.dec button').forEach(function(b){ b.classList.toggle('on', b===btn && nv!==''); }); updateTally(); }
 function onedit(inp){ var tr=inp.closest('tr'); if(inp.value.trim()){ tr.setAttribute('data-state','keep'); tr.querySelectorAll('.dec button').forEach(function(b){ b.classList.toggle('on', b.textContent==='keep'); }); updateTally(); } }
 function updateTally(){ var rows=document.querySelectorAll('tr[data-flag]'); var k=0,d=0; rows.forEach(function(r){var s=r.getAttribute('data-state'); if(s==='keep')k++; else if(s==='drop')d++;}); document.getElementById('tally').textContent='kept '+k+' · dropped '+d+' · '+(rows.length-k-d)+' to review'; }
 function copyAccepted(){ var out=[]; document.querySelectorAll('tr[data-flag]').forEach(function(r){ if(r.getAttribute('data-state')!=='keep') return; var inp=r.querySelector('input.edit'); var custom=inp&&inp.value.trim()?inp.value.trim():(r.getAttribute('data-sug')||''); out.push((r.getAttribute('data-base')||'')+'  ->  '+custom); }); if(!out.length){ alert('Nothing marked keep yet.'); return; } navigator.clipboard.writeText(out.join(String.fromCharCode(10))).then(function(){ alert('Copied '+out.length+' accepted item(s) to clipboard.'); }); }
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


def _ctx_html(ctx, span_text, cls=""):
    """Render '<context before> <b>span</b> <context after>'. Falls back to just
    the bold span if no context is available (older reviews without *_ctx)."""
    if not ctx:
        return f'<b class="{cls}">{_esc(span_text)}</b>' if span_text else ""
    before, after = _esc(ctx.get("before")), _esc(ctx.get("after"))
    span = _esc(span_text if span_text is not None else ctx.get("span"))
    inner = f'<b class="{cls}">{span}</b>' if span else '<b>[missing]</b>'
    return f"{before} {inner} {after}".strip()


def _time_cell(start):
    if start is None:
        return '<td class="t">—</td>'
    return (f'<td class="t"><button class="play" onclick="seek({start})" aria-label="play here">▶</button>'
            f'<span class="ts" onclick="seek({start})">{_mmss(start)}</span></td>')


def _edit_cell():
    return '<td><input class="edit" type="text" oninput="onedit(this)" placeholder="optional override"></td>'


def _dec():
    return ('<td class="dec"><button onclick="mark(this,\'keep\')">keep</button>'
            '<button onclick="mark(this,\'drop\')">drop</button></td>')


def _web_audio_src(audio_path, out_dir):
    """Return an <audio> src browsers reliably play from a local file: a mono
    .mp3 placed next to the report (bare filename). Cached. Falls back to a
    relative path to the original if ffmpeg is unavailable."""
    audio_path = Path(audio_path)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        mp3 = Path(out_dir) / (audio_path.stem + ".audio.mp3")
        if not mp3.exists():
            try:
                subprocess.run([ffmpeg, "-y", "-i", str(audio_path), "-ac", "1",
                                "-b:a", "64k", "-vn", str(mp3)],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                mp3 = None
        if mp3 and mp3.exists():
            return quote(mp3.name)
    return quote(os.path.relpath(audio_path.resolve(), Path(out_dir)))


def write_html_report(audio_path, review, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    audio_rel = _web_audio_src(audio_path, out_path.parent)
    summ = review.get("summary", {}) or {}

    corr = ""
    for d in review.get("disagreements", []):
        base = _esc(d.get("base_text"))
        sug = _esc((d.get("llm") or {}).get("correction") or d.get("audio_text"))
        in_tr = _ctx_html(d.get("base_ctx"), d.get("base_text"))
        audio = _ctx_html(d.get("audio_ctx"),
                          (d.get("llm") or {}).get("correction") or d.get("audio_text"), cls="sug")
        corr += (f'<tr data-flag data-base="{base}" data-sug="{sug}">'
                 f'{_time_cell(d.get("start"))}'
                 f'<td>{_esc(d.get("speaker"))}</td><td>{in_tr}</td>'
                 f'<td>{audio}</td>'
                 f'<td>{_esc((d.get("llm") or {}).get("confidence"))}</td>'
                 f'{_edit_cell()}{_dec()}</tr>')
    corr = corr or '<tr><td colspan="7">None found.</td></tr>'

    om = ""
    for o in review.get("omissions", []):
        txt = _esc(o.get("audio_text"))
        heard = _ctx_html(o.get("audio_ctx"), o.get("audio_text"))
        om += (f'<tr data-flag data-base="[omission]" data-sug="{txt}">'
               f'{_time_cell(o.get("start"))}'
               f'<td>{heard}</td>{_edit_cell()}{_dec()}</tr>')
    om = om or '<tr><td colspan="4">None found.</td></tr>'

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
