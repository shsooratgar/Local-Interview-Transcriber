#!/usr/bin/env python3
"""Standalone, offline HTML review cockpit.

- Audio player on top; every suggested correction / recovered passage / omission
  has a ▶ play button and a clickable time that seek to ~5s before that moment.
- Both transcript columns show a few words of context with the differing span bold.
- "conf" = how sure OUR re-transcription was about the audio span (testing aid).
- Per row you either click keep/drop OR type your own correction — whichever you
  touch last wins; the other greys out (still clickable to switch).
- A running tally, "Copy accepted", and "Apply" (writes a corrected .docx via the
  local server). Choices are saved in the browser (localStorage).

For reliable local playback the audio is transcoded to a small mono .mp3 placed
NEXT TO the html (same folder, bare filename); falls back to a relative path if
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
 .spk{color:#9a3412;font-size:11px;font-weight:600;white-space:nowrap}
 .care{color:#137a3e;font-size:11px;white-space:nowrap}
 .cf{font-variant-numeric:tabular-nums;color:#666;width:46px}
 .edit{width:170px;font-size:13px;padding:4px 6px;border:1px solid #cdd6e4;border-radius:6px}
 .dec{white-space:nowrap;width:112px}
 .dec button{font-size:12px;padding:3px 9px;margin-right:4px;border:1px solid #ccc;background:#fff;border-radius:6px;cursor:pointer}
 .dec button.on{border-color:#0066cc;background:#eaf3ff;font-weight:600}
 tr[data-state=keep]{background:#eafaf0}
 tr[data-state=keep] .bt,tr[data-mode=txt] .bt{text-decoration:line-through;opacity:.5}
 tr[data-state=drop] .at{text-decoration:line-through;opacity:.5}
 tr[data-mode=txt] .dec{opacity:.4}
 tr[data-mode=btn] .edit{opacity:.4}
 .pill{display:inline-block;background:#eef2ff;color:#334;border-radius:11px;padding:2px 10px;margin-left:6px;font-size:12px}
 .note{color:#555;font-size:13px;background:#fff;border:1px solid #eee;border-radius:8px;padding:10px 12px}
 .bar{background:#fff;border:1px solid #e3e3e3;border-radius:8px;padding:8px 12px;margin:10px 0;display:flex;align-items:center;gap:12px}
 .bar button{font-size:13px;padding:4px 12px;border:1px solid #0066cc;background:#0066cc;color:#fff;border-radius:6px;cursor:pointer}
 .bar button.alt{background:#fff;color:#0066cc}
</style></head><body>
<header>
 <b>__TITLE__</b> __PILLS__
 <audio id="p" controls preload="metadata" src="__AUDIO__"></audio>
</header>
<main>
 <p class="note">Hit ▶ (or click the blue time) to hear that moment — playback starts ~5s earlier. For each row, click <b>keep</b>/<b>drop</b> OR type your own in <b>your correction</b> — whichever you touch last wins; the other greys out (still clickable to switch). "conf" is how sure our re-transcription was. Choices are saved in this browser. "Apply" writes a corrected .docx; nothing else changes your transcript file.</p>
 <h2>Summary</h2>
 <p>__SUMMARY__</p>
 <ul>__TOPICS__</ul>
 <h2>Suggested corrections</h2>
 <div class="bar"><span id="tally">…</span><button onclick="applyChanges()">Apply → corrected .docx</button><button class="alt" onclick="copyAccepted()">Copy accepted</button><button class="alt" onclick="resetState()">Reset choices</button><span id="saved" style="font-size:12px;margin-left:auto"></span></div>
 <table><tr><th class="t">time</th><th>speaker</th><th>in transcript</th><th>suggested (from audio)</th><th class="cf">conf</th><th>your correction</th><th></th></tr>__CORR__</table>
 <h2>Recovered passages <small>(transcript dropped these — often another speaker)</small></h2>
 <table><tr><th class="t">time</th><th>speaker</th><th>in transcript</th><th>recovered (from audio)</th><th class="cf">conf</th><th>your correction</th><th></th></tr>__REC__</table>
 <h2>Possible omissions <small>(heard in audio, missing from transcript)</small></h2>
 <table><tr><th class="t">time</th><th>heard in audio</th><th>your correction</th><th></th></tr>__OM__</table>
 <h2>Not heard in audio <small>(in the transcript only — possible fabrication; <b>keep</b> = remove it from the transcript, <b>drop</b> = leave it in)</small></h2>
 <table><tr><th class="t">~time</th><th>speaker</th><th>in transcript (never heard)</th><th>your correction</th><th></th></tr>__BO__</table>
</main>
<script>
 var p=document.getElementById('p');
 var LEAD=5;
 var SKEY="review:"+document.title;
 var CHOICES="__CHOICES__";   /* durable server-side store output/<stem>.choices.json; "" when opened without the server */
 function rows(){ return document.querySelectorAll('tr[data-flag]'); }
 function seek(s){ if(s===null||s===undefined) return; p.currentTime=Math.max(0,s-LEAD); p.play(); }
 function mark(btn,val){ var tr=btn.closest('tr'); var nv=tr.getAttribute('data-state')===val?'':val; tr.setAttribute('data-state',nv); var inp=tr.querySelector('input.edit'); tr.setAttribute('data-mode', nv?'btn':((inp&&inp.value.trim())?'txt':'')); tr.querySelectorAll('.dec button').forEach(function(b){ b.classList.toggle('on', b===btn && nv!==''); }); updateTally(); saveState(); }
 function onedit(inp){ var tr=inp.closest('tr'); tr.setAttribute('data-mode', inp.value.trim()?'txt':(tr.getAttribute('data-state')?'btn':'')); updateTally(); saveState(); }
 function accepted(r){ var mo=r.getAttribute('data-mode'); return mo==='txt' || (mo!=='txt' && r.getAttribute('data-state')==='keep'); }
 function updateTally(){ var k=0,d=0,rs=rows(); rs.forEach(function(r){ var mo=r.getAttribute('data-mode'),s=r.getAttribute('data-state'); if(mo==='txt')k++; else if(s==='keep')k++; else if(s==='drop')d++; }); document.getElementById('tally').textContent='kept '+k+' · dropped '+d+' · '+(rs.length-k-d)+' to review'; }
 function buildMap(){ var m={}; rows().forEach(function(r){ var st=r.getAttribute('data-state')||''; var mo=r.getAttribute('data-mode')||''; var inp=r.querySelector('input.edit'); var ed=inp?inp.value:''; if(st||ed||mo) m[r.getAttribute('data-key')]={s:st,e:ed,m:mo}; }); return m; }
 function applyMap(m){ rows().forEach(function(r){ var v=m[r.getAttribute('data-key')]; if(!v) return; if(v.s) r.setAttribute('data-state',v.s); if(v.m) r.setAttribute('data-mode',v.m); var inp=r.querySelector('input.edit'); if(inp&&v.e) inp.value=v.e; r.querySelectorAll('.dec button').forEach(function(b){ b.classList.toggle('on', b.textContent===v.s && v.m==='btn'); }); }); }
 function setSaved(ok){ var el=document.getElementById('saved'); if(!el) return; if(!CHOICES){ el.textContent=''; return; } el.textContent= ok ? ('saved ✓ '+new Date().toLocaleTimeString()) : 'NOT saved — is the server (launcher) running?'; el.style.color= ok ? '#137a3e' : '#b00020'; }
 function pushServer(m){ if(!CHOICES) return null; var pr; try{ pr=fetch('/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({decisions:m})}); }catch(e){ setSaved(false); return null; } pr.then(function(r){ setSaved(!!(r&&r.ok)); }, function(){ setSaved(false); }); return pr; }
 function saveState(){ var m=buildMap(); try{ localStorage.setItem(SKEY,JSON.stringify(m)); }catch(e){} pushServer(m); }
 function loadState(){ var local=function(){ try{ return JSON.parse(localStorage.getItem(SKEY)||'{}'); }catch(e){ return {}; } }; var done=function(m){ applyMap(m||{}); updateTally(); }; if(!CHOICES){ done(local()); return; } fetch(CHOICES+'?t='+Date.now()).then(function(r){ return r.ok?r.json():null; }).then(function(srv){ if(srv && Object.keys(srv).length){ done(srv); } else { var lm=local(); done(lm); if(Object.keys(lm).length) pushServer(lm); } }).catch(function(){ done(local()); }); }
 function resetState(){ if(!confirm('Clear all your keep/drop/edits for this file?')) return; try{ localStorage.removeItem(SKEY); }catch(e){} var go=function(){ location.reload(); }; var pr=pushServer({}); if(pr&&pr.then) pr.then(go,go); else go(); }
 function copyAccepted(){ var out=[]; rows().forEach(function(r){ var mo=r.getAttribute('data-mode'),s=r.getAttribute('data-state'),inp=r.querySelector('input.edit'); var t=null; if(mo==='txt'&&inp&&inp.value.trim()) t=inp.value.trim(); else if(mo!=='txt'&&s==='keep') t=r.getAttribute('data-sug')||''; if(t===null) return; out.push((r.getAttribute('data-base')||'')+'  ->  '+t); }); if(!out.length){ alert('Nothing accepted yet.'); return; } navigator.clipboard.writeText(out.join(String.fromCharCode(10))).then(function(){ alert('Copied '+out.length+' accepted item(s).'); }); }
 function applyChanges(){ var dec=buildMap(); pushServer(dec); fetch('/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({decisions:dec})}).then(function(r){return r.json();}).then(function(j){ if(j.error){alert('Apply failed: '+j.error);return;} alert('Created '+(j.out||'').split('/').pop()+'  ('+j.applied+' applied'+(j.skipped?', '+j.skipped+' need manual placement':'')+').'+(j.changes&&j.changes.indexOf('failed')!==0?String.fromCharCode(10)+'Change-tracked copy: '+j.changes.split('/').pop():'')); }).catch(function(){ alert('Apply needs the local server — start it with serve_review.py (or the launcher).'); }); }
 function flush(){ if(!CHOICES) return; var m=buildMap(); pushServer(m); if(navigator.sendBeacon){ try{ navigator.sendBeacon('/save', new Blob([JSON.stringify({decisions:m})],{type:'application/json'})); }catch(e){} } }
 document.addEventListener('visibilitychange', function(){ if(document.visibilityState==='hidden') flush(); });
 window.addEventListener('pagehide', flush);
 loadState(); updateTally();
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


def _care_badge(d):
    """Small ✓ when the careful re-listen reproduced the audio version."""
    if (d.get("careful") or {}).get("vote") == "audio":
        return ' <span class="care">✓ re-listen</span>'
    return ""


def _suggest_row(key, d, badge=""):
    base = _esc(d.get("base_text"))
    sug = _esc((d.get("llm") or {}).get("correction") or d.get("audio_text"))
    in_tr = _ctx_html(d.get("base_ctx"), d.get("base_text"))
    audio = _ctx_html(d.get("audio_ctx"),
                      (d.get("llm") or {}).get("correction") or d.get("audio_text"), cls="sug")
    conf = _esc(d.get("our_conf"))
    return (f'<tr data-flag data-key="{key}" data-base="{base}" data-sug="{sug}">'
            f'{_time_cell(d.get("start"))}'
            f'<td>{_esc(d.get("speaker"))}</td><td class="bt">{in_tr}</td>'
            f'<td class="at">{audio}{badge}{_care_badge(d)}</td><td class="cf">{conf}</td>'
            f'{_edit_cell()}{_dec()}</tr>')


def _web_audio_src(audio_path, out_dir):
    """A mono .mp3 next to the report (bare filename) for reliable local playback;
    falls back to a relative path if ffmpeg is unavailable."""
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
    # durable choices store served statically next to this report (origin-independent)
    choices_rel = quote(Path(audio_path).stem + ".choices.json")
    summ = review.get("summary", {}) or {}

    corr = "".join(_suggest_row(f"c{i}", d)
                   for i, d in enumerate(review.get("disagreements", []))) \
        or '<tr><td colspan="7">None found.</td></tr>'

    rec = "".join(
        _suggest_row(f"r{i}", d,
                     badge=' <span class="spk">(other speaker?)</span>' if d.get("other_speaker") else "")
        for i, d in enumerate(review.get("recovered", []))) \
        or '<tr><td colspan="7">None found.</td></tr>'

    om = ""
    for i, o in enumerate(review.get("omissions", [])):
        heard = _ctx_html(o.get("audio_ctx"), o.get("audio_text"))
        om += (f'<tr data-flag data-key="o{i}" data-base="[omission]" data-sug="{_esc(o.get("audio_text"))}">'
               f'{_time_cell(o.get("start"))}<td class="at">{heard}{_care_badge(o)}</td>{_edit_cell()}{_dec()}</tr>')
    om = om or '<tr><td colspan="4">None found.</td></tr>'

    bo = ""
    for i, d in enumerate(review.get("base_only", [])):
        in_tr = _ctx_html(d.get("base_ctx"), d.get("base_text"))
        bo += (f'<tr data-flag data-key="b{i}" data-base="{_esc(d.get("base_text"))}" data-sug="">'
               f'{_time_cell(d.get("start"))}<td>{_esc(d.get("speaker"))}</td>'
               f'<td class="bt">{in_tr}</td>{_edit_cell()}{_dec()}</tr>')
    bo = bo or '<tr><td colspan="5">None found.</td></tr>'

    topics = "".join(f"<li>{_esc(t)}</li>" for t in summ.get("topics", []))
    pills = (f'<span class="pill">match {_esc(review.get("match_coverage"))}</span>'
             f'<span class="pill">{len(review.get("disagreements", []))} corrections</span>'
             f'<span class="pill">{len(review.get("recovered", []))} recovered</span>'
             f'<span class="pill">{len(review.get("omissions", []))} omissions</span>'
             f'<span class="pill">{len(review.get("base_only", []))} not heard</span>')

    doc = (TEMPLATE
           .replace("__TITLE__", _esc(Path(audio_path).name))
           .replace("__PILLS__", pills)
           .replace("__AUDIO__", audio_rel)
           .replace("__CHOICES__", choices_rel)
           .replace("__SUMMARY__", _esc(summ.get("summary")))
           .replace("__TOPICS__", topics)
           .replace("__CORR__", corr)
           .replace("__REC__", rec)
           .replace("__OM__", om)
           .replace("__BO__", bo))
    out_path.write_text(doc, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    import json
    import sys
    review = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    print("saved ->", write_html_report(sys.argv[1], review, sys.argv[3]))
