"""The inbox as one self-contained web page (search, filters, grouping).

`page(items)` returns the page body (title, styles, markup, data, script) for
hosts that add the document skeleton themselves (a claude.ai page);
`document(items)` wraps it into a complete HTML file for any web host.
"""
from __future__ import annotations

import json
import re

from .model import Item, now

SOURCES = {  # item.via → label shown in the filters
    "telegram": "Telegram", "email-to-self": "Email to self", "gmail": "Gmail",
    "feed": "YouTube & feeds", "cli": "Laptop", "claude": "Claude", "page": "In-tray page",
}


SHOWN = ("inbox", "later", "someday", "reference")  # statuses the page lists (trash stays out)


def _record(i: Item) -> dict:
    hints = i.extra.get("hints") or {}
    cal = i.extra.get("calendar")
    src = i.source
    if i.channel == "email":
        who = src.get("from", "")
    else:
        who = src.get("author") or src.get("site") or src.get("forwarded_from") or ""
    snippet = i.summary or (i.content if i.channel in ("text", "message", "email") else "")
    snippet = " ".join(re.sub(r"<[^>]+>", " ", snippet).split())
    snippet = re.sub(r"^(View this post on the web at\s+\S+\s*|View in browser\s*\|?\s*)", "", snippet, flags=re.I)
    title = cal["summary"] if cal and cal.get("summary") else i.title
    if snippet.lower().startswith(i.title.lower()[:40]):  # preview that only repeats the title
        snippet = snippet[len(i.title):].strip(" .·-—:") if len(snippet) > len(i.title) + 20 else ""
    return {
        "id": i.id, "status": i.status, "title": title, "icon": i.icon, "channel": i.channel,
        "via": i.via, "source": SOURCES.get(i.via, i.via),
        "url": src.get("url") or src.get("link") or "",
        "at": i.captured_at.isoformat(), "who": who[:80],
        "note": i.note, "snippet": snippet[:240],
        "tags": i.tags, "priority": hints.get("priority", ""),
        "calendar": {k: cal[k] for k in ("summary", "start", "end", "timezone", "location", "add_link", "status", "html_link")
                     if k in cal} if cal else None,
    }


def page(items: list[Item], here: str = "") -> str:
    data = json.dumps({"generated": now().isoformat(), "here": here, "items": [_record(i) for i in items]},
                      ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.replace("__DATA__", data)


def document(items: list[Item]) -> str:
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            "</head><body>" + page(items) + "</body></html>\n")


TEMPLATE = r"""<title>GTD In-tray</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
:root{
  --ground:#F2F4F6; --surface:#FFFFFF; --ink:#18212B; --muted:#5C6977; --faint:#8A96A3;
  --line:#DDE3E9; --accent:#0F6B67; --accent-soft:#E1F0EE; --high:#B4471F; --high-soft:#F8E6DE;
  --cal:#6D4AC7; --cal-soft:#ECE6FA; --stale:#9A6B00;
  --display:"Bricolage Grotesque",ui-sans-serif,system-ui,sans-serif;
  --sans:"IBM Plex Sans",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  color-scheme:dark; --ground:#12171C; --surface:#1A2128; --ink:#E6EBF0; --muted:#9AA6B2; --faint:#6F7C88;
  --line:#2A333C; --accent:#4FC1B8; --accent-soft:#16302F; --high:#F08A5D; --high-soft:#3A2219;
  --cal:#A993F0; --cal-soft:#28213D; --stale:#E0B040;}}
:root[data-theme="dark"]{
  color-scheme:dark; --ground:#12171C; --surface:#1A2128; --ink:#E6EBF0; --muted:#9AA6B2; --faint:#6F7C88;
  --line:#2A333C; --accent:#4FC1B8; --accent-soft:#16302F; --high:#F08A5D; --high-soft:#3A2219;
  --cal:#A993F0; --cal-soft:#28213D; --stale:#E0B040;}
body{background:var(--ground);color:var(--ink);font:15px/1.45 var(--sans);}
.wrap{max-width:860px;margin:0 auto;padding-inline:16px;padding-block:20px 48px;display:grid;gap:18px}
h1{font:700 clamp(26px,5vw,34px)/1.1 var(--display);letter-spacing:-.01em;margin:0;text-wrap:balance}
.head{display:grid;gap:10px}
.sum{display:flex;flex-wrap:wrap;gap:6px 18px;color:var(--muted);font-size:14px}
.sum b{color:var(--ink);font-weight:600;font-variant-numeric:tabular-nums}
.sum .warn b{color:var(--stale)}
.gen{font:12px var(--mono);color:var(--faint)}
.tools{display:grid;gap:10px;position:sticky;top:env(safe-area-inset-top,0px);z-index:2;
  background:var(--ground);padding-block:8px;border-bottom:1px solid var(--line)}
.row1{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
#q{flex:1 1 220px;min-width:0;font:15px var(--sans);color:var(--ink);background:var(--surface);
  border:1px solid var(--line);border-radius:8px;padding:9px 12px}
#q:focus-visible,button:focus-visible,a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--surface)}
.seg button{font:500 13px var(--sans);color:var(--muted);background:none;border:0;padding:8px 12px;cursor:pointer}
.seg button[aria-pressed="true"]{background:var(--accent-soft);color:var(--accent)}
.chips{display:flex;gap:6px;flex-wrap:wrap}
.chip{font:500 13px var(--sans);color:var(--muted);background:var(--surface);border:1px solid var(--line);
  border-radius:999px;padding:5px 11px;cursor:pointer}
.chip[aria-pressed="true"]{color:var(--accent);border-color:var(--accent);background:var(--accent-soft)}
.chip .n{font-family:var(--mono);font-size:12px;margin-left:4px;color:var(--faint)}
section{display:grid;gap:8px}
section h2{display:flex;align-items:baseline;gap:8px;margin:6px 0 0;font:600 12px var(--sans);
  text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
section h2 .n{font-family:var(--mono);color:var(--faint);letter-spacing:0}
.list{display:grid;background:var(--surface);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.it{display:grid;grid-template-columns:28px 1fr auto;gap:4px 10px;padding:11px 14px 11px 12px;
  border-top:1px solid var(--line);border-left:3px solid transparent}
.it:first-child{border-top:0}
.it.high{border-left-color:var(--high)}
.it.low .t{font-weight:500}
.ic{font-size:17px;line-height:1.4;text-align:center}
.main{min-width:0;display:grid;gap:3px}
.t{font-weight:600;overflow-wrap:anywhere;color:var(--ink);text-decoration:none}
a.t:hover{text-decoration:underline;text-decoration-color:var(--faint)}
.meta{color:var(--muted);font-size:13px;overflow-wrap:anywhere}
.note{font-size:13px;color:var(--ink);border-left:2px solid var(--line);padding-left:8px}
.snip{font-size:13px;color:var(--muted);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.tags{display:flex;gap:4px;flex-wrap:wrap}
.tag{font:500 11px var(--mono);color:var(--muted);background:var(--ground);border-radius:4px;padding:1px 6px}
.tag.p-high{color:var(--high);background:var(--high-soft)}
.age{font:12px var(--mono);color:var(--faint);white-space:nowrap;text-align:right}
.age.stale{color:var(--stale)}
.cal{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;margin-top:2px;font-size:13px;
  background:var(--cal-soft);color:var(--cal);border-radius:6px;padding:6px 10px}
.cal b{font-family:var(--mono);font-weight:500}
.cal a{color:var(--cal);font-weight:600}
.views{display:flex;gap:4px;flex-wrap:wrap}
.views button{font:600 14px var(--sans);color:var(--muted);background:none;border:0;border-bottom:2px solid transparent;
  padding:6px 10px;cursor:pointer}
.views button[aria-pressed="true"]{color:var(--ink);border-bottom-color:var(--accent)}
.views .n{font:12px var(--mono);color:var(--faint);margin-left:4px}
.acts{grid-column:2/-1;display:flex;gap:6px;flex-wrap:wrap;margin-top:4px}
.act{font:500 12px var(--sans);color:var(--muted);background:var(--ground);border:1px solid var(--line);
  border-radius:6px;padding:4px 9px;cursor:pointer;min-height:28px}
.act:hover{color:var(--ink);border-color:var(--faint)}
.act.trash:hover{color:var(--high);border-color:var(--high)}
.ro{font-size:13px;color:var(--muted)}
.toast{position:fixed;left:50%;bottom:calc(16px + env(safe-area-inset-bottom,0px));transform:translateX(-50%);
  z-index:5;display:flex;gap:12px;align-items:center;max-width:calc(100vw - 32px);
  background:var(--ink);color:var(--ground);border-radius:8px;padding:10px 14px;font-size:14px;
  box-shadow:0 6px 24px rgba(0,0,0,.18)}
.toast[hidden]{display:none}
.toast span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.toast button{font:600 14px var(--sans);color:var(--accent-soft);background:none;border:0;cursor:pointer;padding:0;flex:none}
.cal-edit{font:500 12px var(--sans);color:var(--cal);background:none;border:1px solid currentColor;border-radius:6px;
  padding:2px 8px;cursor:pointer;margin-left:auto}
.cal-form{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin-top:4px;
  background:var(--cal-soft);border-radius:6px;padding:10px}
.cal-form label{display:grid;gap:3px;font-size:12px;color:var(--cal);font-weight:600}
.cal-form input{font:14px var(--sans);color:var(--ink);background:var(--surface);border:1px solid var(--line);
  border-radius:6px;padding:6px 8px;min-width:0}
.cal-form .wide{grid-column:1/-1}
.cal-form .btns{grid-column:1/-1;display:flex;gap:8px}
.cal-form .save{background:var(--cal);color:var(--surface);border-color:var(--cal)}
#proj-view,#tray-view{display:grid;gap:18px}
#proj-view[hidden],#tray-view[hidden]{display:none}
.apps{display:flex;gap:6px;padding-top:4px}
.apps a{font:600 14px var(--sans);color:var(--muted);text-decoration:none;padding:7px 14px;border-radius:999px;
  border:1px solid var(--line);background:var(--surface)}
.apps a[aria-current="page"]{color:var(--surface);background:var(--ink);border-color:var(--ink)}
.pgrid{display:grid;gap:10px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 14px;display:grid;gap:8px}
.card h3{margin:0;font:600 16px/1.3 var(--sans);display:flex;gap:8px;align-items:baseline;justify-content:space-between}
.card h3 .per{font:12px var(--mono);color:var(--faint);font-weight:400;white-space:nowrap}
.goal{font-size:13px;color:var(--muted)}
.goal b{color:var(--ink);font-weight:500}
.bar{height:8px;border-radius:99px;background:var(--ground);overflow:hidden}
.bar i{display:block;height:100%;background:var(--accent);border-radius:99px}
.bar.behind i{background:var(--stale)}
.bar.done i{background:var(--accent)}
.prog{display:flex;justify-content:space-between;gap:8px;font-size:13px;color:var(--muted);flex-wrap:wrap}
.prog b{color:var(--ink);font-variant-numeric:tabular-nums}
.prog .behind{color:var(--stale);font-weight:600}
.prog .ok{color:var(--accent);font-weight:600}
.next{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;font-size:14px;border-top:1px dashed var(--line);padding-top:8px}
.next .lbl{font:600 11px var(--sans);text-transform:uppercase;letter-spacing:.06em;color:var(--faint)}
.next .when{font:12px var(--mono);color:var(--muted)}
.next .when.over{color:var(--high);font-weight:600}
.next .when.today{color:var(--accent);font-weight:600}
.next a{font-size:12px;color:var(--cal)}
.logs{display:flex;gap:6px;flex-wrap:wrap}
.chipbtn{font:500 13px var(--sans);color:var(--accent);background:var(--accent-soft);border:1px solid transparent;
  border-radius:999px;padding:5px 11px;cursor:pointer;min-height:30px}
.recent{font-size:12px;color:var(--faint)}
.recent button{font:inherit;color:var(--faint);background:none;border:0;text-decoration:underline;cursor:pointer;padding:0}
.filed{font-size:13px;color:var(--muted);display:grid;gap:2px}
.filed a{color:var(--ink)}
.pform{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;background:var(--ground);
  border-radius:8px;padding:10px}
.pform label{display:grid;gap:3px;font-size:12px;font-weight:600;color:var(--muted)}
.pform input,.pform select{font:14px var(--sans);color:var(--ink);background:var(--surface);border:1px solid var(--line);
  border-radius:6px;padding:6px 8px;min-width:0}
.pform .wide{grid-column:1/-1}
.pform .btns{grid-column:1/-1;display:flex;gap:8px;flex-wrap:wrap}
.primary{font:600 14px var(--sans);color:var(--surface);background:var(--accent);border:0;border-radius:8px;padding:8px 14px;cursor:pointer}
.nextlist{display:grid;background:var(--surface);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.nextlist .nx{display:grid;grid-template-columns:1fr auto;gap:2px 10px;padding:9px 14px;border-top:1px solid var(--line);font-size:14px}
.nextlist .nx:first-child{border-top:0}
.nextlist .nx small{color:var(--faint);font-size:12px}
.pick{grid-column:2/-1;display:flex;gap:6px;flex-wrap:wrap;align-items:center;font-size:13px}
.pick select{font:14px var(--sans);padding:5px 8px;border-radius:6px;border:1px solid var(--line);background:var(--surface);color:var(--ink);max-width:100%}
.addbox{display:flex;gap:8px;margin-bottom:12px}
.addbox input{flex:1;min-width:0;font:15px var(--sans);color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:9px 12px}
.empty{color:var(--muted);padding:28px 16px;text-align:center;background:var(--surface);border:1px dashed var(--line);border-radius:10px}
@media (max-width:480px){.it{grid-template-columns:24px 1fr}.age{grid-column:2;text-align:left}}
@media (prefers-reduced-motion:no-preference){.it{transition:background .15s}.it:hover{background:var(--ground)}}
</style>
<div class="wrap">
  <nav class="apps" aria-label="Pages"><a href="#tray" id="to-tray">📥 In-tray</a><a href="#projects" id="to-proj">🎯 Projects</a></nav>
  <div id="proj-view" hidden>
    <header class="head">
      <h1>Projects</h1>
      <div class="sum" id="psum"></div>
    </header>
    <main id="pout"></main>
  </div>
  <div id="tray-view">
  <header class="head">
    <h1>In-tray</h1>
    <div class="sum" id="sum"></div>
    <div class="gen" id="gen"></div>
  </header>
  <div class="tools">
    <nav class="views" id="views" aria-label="View"></nav>
    <div class="row1">
      <input id="q" type="search" placeholder="Search titles, senders, notes…" aria-label="Search">
      <div class="seg" role="group" aria-label="Group by">
        <button id="g-kind" data-g="kind">Kind</button><button id="g-day" data-g="day">Day</button><button id="g-source" data-g="source">Source</button>
      </div>
    </div>
    <div class="chips" id="chips" aria-label="Filter by source"></div>
  </div>
  <main id="out"></main>
  </div>
</div>
<div class="toast" id="toast" role="status" hidden><span id="toast-msg"></span><button id="undo">Undo</button></div>
<script type="application/json" id="data">__DATA__</script>
<script>
(async function(){
  const D = JSON.parse(document.getElementById('data').textContent);
  const all = D.items;
  const NOW = Date.now();
  const store = {get(k){try{return localStorage.getItem(k)}catch(e){return null}},
                 set(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
  let group = store.get('gtd.group') || 'kind', source = '', q = '', view = 'inbox';

  // Triage choices live in the page's database (decisions/<item id> = {decision, at});
  // `gtd decide` later writes them into the items themselves.
  const VIEWS = [['inbox','In-tray'], ['later','Review later'], ['someday','Someday / maybe'], ['reference','Archive'], ['trash','Trash']];
  const ACTIONS = {trash:'🗑 Trash', later:'⏳ Review later', someday:'💭 Someday', reference:'🗄 Archive', inbox:'↩ Back to in-tray'};
  const DONE = {trash:'Moved to Trash', later:'Saved for review later', someday:'Moved to Someday / maybe', reference:'Archived for reference', inbox:'Back in the in-tray'};
  const decided = {}, edits = {};
  let editing = '', picking = '';
  const statusOf = it => (decided[it.id] && decided[it.id].decision) || it.status;
  // Appointment changes from the Edit form live in edits/<item id> = {start, end, location, summary, at}
  const pad = n => String(n).padStart(2, '0');
  const localIso = d => `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  function gcalLink(c){
    const f = s => s.replace(/[-:]/g, '').slice(0, 13) + '00';
    return 'https://calendar.google.com/calendar/render?' + new URLSearchParams({action:'TEMPLATE', text:c.summary || 'Appointment',
      dates:f(c.start) + '/' + f(c.end), ctz:c.timezone, location:c.location || '', details:'(captured in GTD inbox)'});
  }
  function calOf(it){
    const e = edits[it.id], c = it.calendar;
    if (!e) return c;
    const merged = {...(c || {timezone: 'UTC', location: ''}), ...e, status: 'proposed'};
    merged.add_link = gcalLink(merged);
    return merged;
  }
  let db = null;
  try { db = window.claude && await window.claude.use('db'); } catch (e) { db = null; }

  const hrs = it => (NOW - Date.parse(it.at)) / 36e5;
  const age = h => h < 1 ? Math.max(1, Math.round(h*60)) + 'm' : h < 48 ? Math.round(h) + 'h' : Math.round(h/24) + 'd';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmtDay = d => d.toLocaleDateString(undefined, {weekday:'short', day:'numeric', month:'short'});

  const KINDS = [
    ['attention','Needs attention', it => it.priority === 'high'],
    ['appointments','Appointments', it => !!calOf(it)],
    ['notes','Notes & to-dos', it => ['text','message','image','file','audio'].includes(it.channel) && ['telegram','email-to-self','cli','claude'].includes(it.via)],
    ['research','Research to read', it => it.tags.includes('research')],
    ['pubs','Publications', it => it.tags.includes('read-later')],
    ['videos','Videos & podcasts', it => ['youtube','podcast'].includes(it.channel)],
    ['other','Other', () => true],
  ];
  const kindOf = it => KINDS.find(k => k[2](it))[0];

  // Where am I: the phone's time zone, so "Friday 3pm" is read as local time at the next refresh
  const phoneTz = (() => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (e) { return ''; } })();
  if (db && phoneTz && phoneTz !== D.here) {
    db.doc('settings/here').set({timezone: phoneTz, at: new Date().toISOString()}).catch(() => {});
  }
  const hereLabel = z => (z || '').split('/').pop().replace(/_/g, ' ');
  document.getElementById('gen').textContent =
    'Updated ' + new Date(D.generated).toLocaleString(undefined, {weekday:'short', hour:'2-digit', minute:'2-digit'}) +
    (D.here ? ' · times in ' + hereLabel(D.here) + (phoneTz && phoneTz !== D.here ? ' → ' + hereLabel(phoneTz) + ' from next refresh' : '') : '') +
    (db ? '' : ' · read-only here: open it on claude.ai to sort items');

  function drawSummary(){
    const items = all.filter(it => statusOf(it) === 'inbox');
    const oldest = items.reduce((m, it) => Math.max(m, hrs(it)), 0);
    const stale = items.filter(it => hrs(it) > 48).length;
    document.getElementById('sum').innerHTML =
      `<span><b>${items.length}</b> in the tray</span>` +
      (items.length ? `<span${oldest > 48 ? ' class="warn"' : ''}>oldest <b>${age(oldest)}</b></span>` : '') +
      (stale ? `<span class="warn"><b>${stale}</b> waiting over 2 days</span>` : '') +
      `<span><b>${items.filter(it => it.priority === 'high').length}</b> need attention</span>`;
    document.getElementById('views').innerHTML = VIEWS.map(([v, l]) => {
      const n = all.filter(it => statusOf(it) === v).length;
      return (v === 'trash' && !n && view !== 'trash') ? '' :
        `<button data-v="${v}" aria-pressed="${v === view}">${l}<span class="n">${n}</span></button>`;
    }).join('');
  }
  document.getElementById('views').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return; view = b.dataset.v; source = ''; render();
  });

  const chips = document.getElementById('chips');
  let counts = {};
  function drawChips(){
    counts = {};
    const items = all.filter(it => statusOf(it) === view);
    items.forEach(it => counts[it.source] = (counts[it.source] || 0) + 1);
    if (source && !counts[source]) source = '';
    chips.innerHTML = [['', 'All', items.length], ...Object.entries(counts).sort((a,b) => b[1]-a[1]).map(([s,n]) => [s,s,n])]
      .map(([v,l,n]) => `<button class="chip" data-s="${esc(v)}" aria-pressed="${v === source}">${esc(l)}<span class="n">${n}</span></button>`).join('');
  }
  chips.addEventListener('click', e => { const b = e.target.closest('.chip'); if (!b) return; source = b.dataset.s; drawChips(); draw(); });

  document.querySelectorAll('.seg button').forEach(b => b.addEventListener('click', () => {
    group = b.dataset.g; store.set('gtd.group', group); draw();
  }));
  document.getElementById('q').addEventListener('input', e => { q = e.target.value.trim().toLowerCase(); draw(); });

  // ---- triage ----
  const toast = document.getElementById('toast');
  let undo = null, toastTimer = 0;
  function say(msg, undoFn){
    document.getElementById('toast-msg').textContent = msg;
    undo = undoFn; document.getElementById('undo').hidden = !undoFn;
    toast.hidden = false; clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.hidden = true; undo = null; }, 6000);
  }
  document.getElementById('undo').addEventListener('click', () => { const u = undo; toast.hidden = true; undo = null; if (u) u(); });

  async function decide(it, decision, quiet, extra){
    const before = decided[it.id];
    decided[it.id] = {decision, at: new Date().toISOString(), ...(extra || {})};
    render();
    try {
      await db.doc('decisions/' + it.id).set(decided[it.id]);
    } catch (e) {
      if (before) decided[it.id] = before; else delete decided[it.id];
      render();
      say(e && e.code === 'quota_exceeded' ? 'Storage is full: ask Claude to apply your decisions.' : 'Couldn’t save that. Try again.');
      return;
    }
    if (!quiet) {
      const prev = before ? before.decision : it.status;
      say(extra && extra.project ? `Filed under ${extra.project}: ${it.title}` : `${DONE[decision]}: ${it.title}`,
          () => decide(it, prev, true));
    }
  }
  document.getElementById('out').addEventListener('click', async e => {
    if (!db) return;
    const ed = e.target.closest('.cal-edit');
    if (ed) { editing = editing === ed.dataset.id ? '' : ed.dataset.id; draw(); return; }
    if (e.target.closest('.cal-cancel')) { editing = ''; draw(); return; }
    const sv = e.target.closest('.cal-save');
    if (sv) {
      const form = sv.closest('.cal-form'), it = all.find(x => x.id === sv.dataset.id), c = calOf(it);
      const get = n => form.querySelector(`[name=${n}]`).value.trim();
      if (!get('day') || !get('time')) { say('Pick a day and a time.'); return; }
      const start = `${get('day')}T${get('time')}`;
      const length = c && c.end ? Date.parse(c.end) - Date.parse(c.start) : 36e5;
      const change = {start, end: localIso(new Date(Date.parse(start) + (length > 0 ? length : 36e5))),
                      location: get('location'), summary: get('summary'), at: new Date().toISOString()};
      const before = edits[it.id];
      edits[it.id] = change; editing = ''; render();
      try { await db.doc('edits/' + it.id).set(change); say('Appointment updated: ' + (change.summary || it.title)); }
      catch (err) { if (before) edits[it.id] = before; else delete edits[it.id]; render(); say('Couldn’t save that. Try again.'); }
      return;
    }
    const tp = e.target.closest('.to-proj');
    if (tp) { picking = picking === tp.dataset.id ? '' : tp.dataset.id; draw(); return; }
    if (e.target.closest('.pick-cancel')) { picking = ''; draw(); return; }
    const b = e.target.closest('.act'); if (!b || !b.dataset.d) return;
    const it = all.find(x => x.id === b.dataset.id); if (it) decide(it, b.dataset.d);
  });

  if (db) {
    db.collection('decisions').onSnapshot(snap => {
      for (const k of Object.keys(decided)) delete decided[k];
      snap.docs.forEach(d => { const v = d.data(); if (v && ACTIONS[v.decision]) decided[d.id] = v; });
      render();
    }, () => { db = null; render(); });
    db.collection('adds').onSnapshot(snap => {
      for (let i = all.length - 1; i >= 0; i--) if (all[i].pending) all.splice(i, 1);
      snap.docs.forEach(d => { const v = d.data(); if (v && v.text) all.unshift({id: 'add:' + d.id, status: v.status || 'someday', pending: true,
        title: v.text, icon: '💭', channel: 'text', via: 'page', source: 'In-tray page', url: '', at: v.at || new Date().toISOString(),
        who: '', note: '', snippet: '', tags: [], priority: '', calendar: null}); });
      render();
    }, () => {});
    db.collection('edits').onSnapshot(snap => {
      for (const k of Object.keys(edits)) delete edits[k];
      snap.docs.forEach(d => { const v = d.data(); if (v && v.start) edits[d.id] = v; });
      render();
    }, () => {});
  }

  function row(it){
    const h = hrs(it);
    const titleHtml = it.url ? `<a class="t" href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.title)}</a>` : `<span class="t">${esc(it.title)}</span>`;
    const meta = [it.who, it.source].filter(Boolean).map(esc).join(' · ');
    const tags = [...(it.priority === 'high' ? ['<span class="tag p-high">high</span>'] : []),
                  ...(it.priority === 'low' ? ['<span class="tag">low</span>'] : []),
                  ...it.tags.map(t => `<span class="tag">${esc(t)}</span>`)].join('');
    let cal = '';
    const c = calOf(it);
    if (c) {
      const when = new Date(c.start);
      const label = when.toLocaleString(undefined, {weekday:'short', day:'numeric', month:'short'}) + ' ' + c.start.slice(11,16);
      const act = c.status === 'added' ? (c.html_link ? `<a href="${esc(c.html_link)}" target="_blank" rel="noopener">On your calendar ✓</a>` : 'On your calendar ✓')
                                       : `<a href="${esc(c.add_link)}" target="_blank" rel="noopener">Add to Google Calendar</a>`;
      const edit = db ? `<button class="cal-edit" data-id="${esc(it.id)}">✎ Edit</button>` : '';
      cal = `<div class="cal">📅 <b>${esc(label)}</b><span>${esc([c.timezone.split('/').pop().replace('_',' '), c.location].filter(Boolean).join(' · '))}</span>${act}${edit}</div>`;
      if (editing === it.id) cal += `<div class="cal-form" data-id="${esc(it.id)}">
        <label class="wide">What<input name="summary" value="${esc(c.summary || it.title)}"></label>
        <label>Day<input type="date" name="day" value="${esc(c.start.slice(0,10))}" required></label>
        <label>Time<input type="time" name="time" value="${esc(c.start.slice(11,16))}" required></label>
        <label class="wide">Where<input name="location" value="${esc(c.location)}" placeholder="Address or place (optional)"></label>
        <div class="btns"><button class="act save cal-save" data-id="${esc(it.id)}">Save</button><button class="act cal-cancel">Cancel</button></div></div>`;
    }
    const st = statusOf(it);
    const acts = it.pending ? '<div class="acts"><span class="ro">Saved — syncs at the next refresh</span></div>' : db ? `<div class="acts">${Object.keys(ACTIONS).filter(d => d !== st && !(st === 'trash' && d !== 'inbox'))
      .map(d => `<button class="act ${d}" data-id="${esc(it.id)}" data-d="${d}">${ACTIONS[d]}</button>`).join('')}${st !== 'trash' ? `<button class="act to-proj" data-id="${esc(it.id)}">📁 Project</button>` : ''}</div>` +
      (picking === it.id ? `<div class="pick"><select data-id="${esc(it.id)}" class="proj-pick"><option value="">File under project…</option>
        ${activeProjects().map(p => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}
        <option value="__new">➕ New project from this…</option></select><button class="act pick-cancel">Cancel</button></div>` : '') : '';
    const title = c && c.summary ? (it.url ? `<a class="t" href="${esc(it.url)}" target="_blank" rel="noopener">${esc(c.summary)}</a>` : `<span class="t">${esc(c.summary)}</span>`) : titleHtml;
    return `<article class="it ${esc(it.priority)}"><div class="ic" aria-hidden="true">${esc(it.icon)}</div>
      <div class="main">${title}${meta ? `<div class="meta">${meta}</div>` : ''}
        ${it.note ? `<div class="note">${esc(it.note)}</div>` : ''}
        ${it.snippet ? `<div class="snip">${esc(it.snippet)}</div>` : ''}${cal}
        ${tags ? `<div class="tags">${tags}</div>` : ''}</div>
      <div class="age${h > 48 ? ' stale' : ''}" title="${esc(new Date(it.at).toLocaleString())}">${age(h)}</div>${acts}</article>`;
  }

  const EMPTY = {inbox: 'The tray is empty. Inbox zero.', later: 'Nothing saved for review later.',
                 reference: 'Nothing archived yet.', trash: 'Trash is empty.',
                 someday: 'Nothing here yet — things you might do one day, but not now.'};
  function draw(){
    document.querySelectorAll('.seg button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.g === group)));
    const items = all.filter(it => statusOf(it) === view);
    const shown = items.filter(it => (!source || it.source === source) &&
      (!q || [it.title, it.who, it.note, it.snippet, it.tags.join(' '), it.source].join(' ').toLowerCase().includes(q)));
    const out = document.getElementById('out');
    const addbox = view === 'someday' && db ? `<div class="addbox"><input id="someday-new" placeholder="Something you might want to do one day…" aria-label="New someday / maybe idea" value="${esc(somedayDraft)}"><button class="primary" id="someday-add">Add</button></div>` : '';
    if (!shown.length) { out.innerHTML = addbox + `<div class="empty">${items.length ? 'Nothing matches this search or filter.' : EMPTY[view]}</div>`; return; }
    let groups;
    if (group === 'kind') groups = KINDS.map(([k, label]) => [label, shown.filter(it => kindOf(it) === k)]);
    else if (group === 'source') groups = Object.keys(counts).map(s => [s, shown.filter(it => it.source === s)]);
    else {
      const byDay = new Map();
      shown.forEach(it => { const d = fmtDay(new Date(it.at)); byDay.set(d, [...(byDay.get(d) || []), it]); });
      groups = [...byDay.entries()];
    }
    out.innerHTML = addbox + groups.filter(g => g[1].length).map(([label, list]) =>
      `<section><h2>${esc(label)} <span class="n">${list.length}</span></h2><div class="list">${list.map(row).join('')}</div></section>`).join('');
  }
  // ================= Projects =================
  // projects/<id> = {name, kind: 'oneoff'|'recurring', goal, next: {text, when}, status: 'active'|'done',
  //                  target: {amount, max, unit: 'min'|'sessions'|'books', period: 'week'|'month'}, created, updated}
  // logs/<auto>   = {project, amount, at, note}   (one document per session / book: no counters)
  const projects = {}, logs = {};
  let pform = null, doneFor = '', fileAfterCreate = '';
  const slug = name => 'project:' + String(name).toLowerCase().split(/\s+/).filter(Boolean).join('-');
  const activeProjects = () => Object.values(projects).filter(p => p.status !== 'done')
    .sort((a, b) => (a.kind === b.kind ? a.name.localeCompare(b.name) : a.kind === 'recurring' ? -1 : 1));
  const UNITS = {min: ['min', 'minutes'], sessions: ['session', 'sessions'], books: ['book', 'books']};
  const QUICK = {min: [20, 30, 45, 60], sessions: [1], books: [1]};

  function periodStart(period, d = new Date()){
    const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    if (period === 'month') x.setDate(1); else x.setDate(x.getDate() - ((x.getDay() + 6) % 7));  // Monday
    return x;
  }
  function periodEnd(period){
    const s = periodStart(period), e = new Date(s);
    if (period === 'month') e.setMonth(e.getMonth() + 1); else e.setDate(e.getDate() + 7);
    return e;
  }
  const logsFor = (p, since) => Object.entries(logs).filter(([, l]) => l.project === p.id && Date.parse(l.at) >= since)
    .sort((a, b) => Date.parse(b[1].at) - Date.parse(a[1].at));

  function whenLabel(w){
    if (!w) return ['', ''];
    const d = new Date(w.length > 10 ? w : w + 'T00:00'), today = new Date(); today.setHours(0, 0, 0, 0);
    const day = new Date(d); day.setHours(0, 0, 0, 0);
    const diff = Math.round((day - today) / 864e5);
    const txt = (diff === 0 ? 'Today' : diff === 1 ? 'Tomorrow' : diff === -1 ? 'Yesterday'
      : d.toLocaleDateString(undefined, {weekday: 'short', day: 'numeric', month: 'short'})) + (w.length > 10 ? ' ' + w.slice(11, 16) : '');
    return [txt, diff < 0 || (diff === 0 && w.length > 10 && d < new Date()) ? 'over' : diff === 0 ? 'today' : ''];
  }
  function calLink(p){
    const w = p.next && p.next.when; if (!w || w.length <= 10) return '';
    const end = localIso(new Date(Date.parse(w) + 36e5));
    return gcalLink({summary: `${p.next.text} (${p.name})`, start: w, end, timezone: D.here || phoneTz || 'UTC', location: ''});
  }

  function nextBlock(p){
    const n = p.next || {};
    if (doneFor === p.id) return `<div class="pform" data-p="${esc(p.id)}">
      <label class="wide">Next action<input name="text" placeholder="The very next physical step" required></label>
      <label>When<input type="datetime-local" name="when"></label>
      <div class="btns"><button class="primary pn-save" data-p="${esc(p.id)}">Save next action</button><button class="act pn-cancel">Cancel</button></div></div>`;
    if (!n.text) return `<div class="next"><span class="lbl">Next</span><span class="goal">No next action yet</span>
      ${db ? `<button class="act p-done" data-p="${esc(p.id)}">+ Add next action</button>` : ''}</div>`;
    const [w, cls] = whenLabel(n.when), link = calLink(p);
    return `<div class="next"><span class="lbl">Next</span><span>${esc(n.text)}</span>
      ${w ? `<span class="when ${cls}">${esc(w)}</span>` : '<span class="when">no date</span>'}
      ${link ? `<a href="${esc(link)}" target="_blank" rel="noopener">📅 Add</a>` : ''}
      ${db ? `<button class="act p-done" data-p="${esc(p.id)}">✓ Done → next</button>` : ''}</div>`;
  }

  function recurringCard(p){
    const t = p.target || {}, start = periodStart(t.period).getTime(), end = periodEnd(t.period).getTime();
    const mine = logsFor(p, start), got = mine.reduce((n, [, l]) => n + (+l.amount || 0), 0);
    const goal = +t.amount || 1, pct = Math.min(100, Math.round(got / goal * 100));
    const elapsed = Math.min(1, (Date.now() - start) / (end - start));
    const state = got >= goal ? 'done' : got < goal * elapsed * 0.8 ? 'behind' : 'ok';
    const unit = UNITS[t.unit] || ['', ''], left = Math.max(0, goal - got);
    const daysLeft = Math.ceil((end - Date.now()) / 864e5);
    const per = t.period === 'month' ? 'this month' : 'this week';
    const quick = (QUICK[t.unit] || [1]).map(a => `<button class="chipbtn p-log" data-p="${esc(p.id)}" data-a="${a}">+${a}${t.unit === 'min' ? ' min' : ''}</button>`).join('')
      + (t.unit === 'min' ? `<button class="chipbtn p-log" data-p="${esc(p.id)}" data-a="?">+ other</button>` : '');
    const recent = mine.slice(0, 3).map(([id, l]) =>
      `${esc(new Date(l.at).toLocaleDateString(undefined, {weekday: 'short'}))} +${esc(l.amount)}${db ? ` <button class="p-unlog" data-l="${esc(id)}">undo</button>` : ''}`).join(' · ');
    return `<article class="card"><h3>${esc(p.name)}<span class="per">${esc(t.max ? `${t.amount}–${t.max}` : t.amount)} ${esc(unit[1])} / ${esc(t.period || 'week')}</span></h3>
      ${p.goal ? `<div class="goal"><b>Goal:</b> ${esc(p.goal)}</div>` : ''}
      <div class="bar ${state}"><i style="width:${pct}%"></i></div>
      <div class="prog"><span><b>${esc(got)}</b> / ${esc(goal)} ${esc(unit[1])} ${per}</span>
        <span class="${state === 'behind' ? 'behind' : 'ok'}">${state === 'done' ? (t.max && got < t.max ? `✓ target met · ${t.max - got} to stretch` : '✓ done') : state === 'behind' ? `behind · ${left} to go, ${daysLeft}d left` : `${left} to go · ${daysLeft}d left`}</span></div>
      ${db ? `<div class="logs">${quick}</div>` : ''}
      ${recent ? `<div class="recent">${recent}</div>` : ''}
      ${nextBlock(p)}
      ${db ? `<div class="acts" style="grid-column:auto;margin:0"><button class="act p-edit" data-p="${esc(p.id)}">✎ Edit</button></div>` : ''}
    </article>`;
  }

  function oneoffCard(p){
    const tag = slug(p.name);
    const filed = all.filter(it => it.tags.includes(tag) || (decided[it.id] && decided[it.id].project === p.name));
    return `<article class="card"><h3>${esc(p.name)}<span class="per">${p.status === 'done' ? 'done' : 'one-off'}</span></h3>
      <div class="goal"><b>End goal:</b> ${p.goal ? esc(p.goal) : '<i>not set yet — what does done look like?</i>'}</div>
      ${p.status !== 'done' ? nextBlock(p) : ''}
      ${filed.length ? `<div class="filed"><span class="lbl" style="font:600 11px var(--sans);text-transform:uppercase;letter-spacing:.06em;color:var(--faint)">Material (${filed.length})</span>
        ${filed.slice(0, 6).map(it => it.url ? `<a href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.icon)} ${esc(it.title)}</a>` : `<span>${esc(it.icon)} ${esc(it.title)}</span>`).join('')}</div>` : ''}
      ${db ? `<div class="acts" style="grid-column:auto;margin:0"><button class="act p-edit" data-p="${esc(p.id)}">✎ Edit</button>
        <button class="act p-finish" data-p="${esc(p.id)}">${p.status === 'done' ? '↩ Reopen' : '🏁 Project done'}</button></div>` : ''}
    </article>`;
  }

  function formHtml(f){
    const p = f.id ? projects[f.id] : {kind: f.kind || 'oneoff', name: f.name || '', goal: '', next: {}, target: {unit: 'min', period: 'week'}};
    const t = p.target || {unit: 'min', period: 'week'}, rec = (f.kind || p.kind) === 'recurring';
    return `<div class="pform" id="pform">
      <label>Type<select name="kind"><option value="oneoff"${rec ? '' : ' selected'}>One-off (has an end)</option><option value="recurring"${rec ? ' selected' : ''}>Recurring (a standard to keep)</option></select></label>
      <label class="wide">Name<input name="name" value="${esc(p.name)}" placeholder="${rec ? 'Zone 2 cardio' : 'Research: NVIDIA'}"></label>
      <label class="wide">${rec ? 'Why / goal' : 'End goal — what does done look like?'}<input name="goal" value="${esc(p.goal || '')}" placeholder="${rec ? 'Aerobic base for longevity' : 'Decide buy / pass with a one-page thesis'}"></label>
      ${rec ? `<label>Target<input type="number" min="1" name="amount" value="${esc(t.amount || '')}"></label>
        <label>Stretch (optional)<input type="number" min="1" name="max" value="${esc(t.max || '')}"></label>
        <label>Unit<select name="unit">${Object.keys(UNITS).map(u => `<option value="${u}"${t.unit === u ? ' selected' : ''}>${UNITS[u][1]}</option>`).join('')}</select></label>
        <label>Per<select name="period"><option value="week"${t.period !== 'month' ? ' selected' : ''}>week</option><option value="month"${t.period === 'month' ? ' selected' : ''}>month</option></select></label>` : ''}
      <label class="wide">Next action<input name="next" value="${esc((p.next || {}).text || '')}" placeholder="The very next physical step"></label>
      <label>When<input type="datetime-local" name="when" value="${esc(((p.next || {}).when || '').slice(0, 16))}"></label>
      <div class="btns"><button class="primary pf-save">${f.id ? 'Save' : 'Create project'}</button><button class="act pf-cancel">Cancel</button>
        ${f.id ? `<button class="act trash pf-delete" style="margin-left:auto">Delete project</button>` : ''}</div></div>`;
  }

  function drawProjects(){
    const act = activeProjects(), rec = act.filter(p => p.kind === 'recurring'), one = act.filter(p => p.kind !== 'recurring');
    const done = Object.values(projects).filter(p => p.status === 'done');
    const withNext = act.filter(p => p.next && p.next.text)
      .sort((a, b) => (a.next.when || '9999').localeCompare(b.next.when || '9999'));
    const over = withNext.filter(p => whenLabel(p.next.when)[1] === 'over').length;
    document.getElementById('psum').innerHTML = `<span><b>${one.length}</b> one-off</span><span><b>${rec.length}</b> recurring</span>` +
      (over ? `<span class="warn"><b>${over}</b> overdue</span>` : '') + (db ? '' : '<span>read-only here</span>');
    const out = document.getElementById('pout');
    if (!db && !act.length) { out.innerHTML = '<div class="empty">Open this page on claude.ai to see and edit your projects.</div>'; return; }
    const sec = (label, n, body) => `<section><h2>${esc(label)} <span class="n">${n}</span></h2>${body}</section>`;
    out.innerHTML =
      (pform ? sec(pform.id ? 'Edit project' : 'New project', '', formHtml(pform)) : (db ? `<div><button class="primary" id="p-new">+ New project</button></div>` : '')) +
      (withNext.length ? sec('Next actions', withNext.length, `<div class="nextlist">${withNext.map(p => {
        const [w, cls] = whenLabel(p.next.when);
        return `<div class="nx"><span>${esc(p.next.text)}<br><small>${esc(p.name)}</small></span><span class="when ${cls}" style="font:12px var(--mono)">${esc(w || '—')}</span></div>`;
      }).join('')}</div>`) : '') +
      (rec.length ? sec('Recurring', rec.length, `<div class="pgrid">${rec.map(recurringCard).join('')}</div>`) : '') +
      (one.length ? sec('One-off', one.length, `<div class="pgrid">${one.map(oneoffCard).join('')}</div>`) : '') +
      (done.length ? sec('Done', done.length, `<div class="pgrid">${done.map(oneoffCard).join('')}</div>`) : '') +
      (!act.length && !pform ? '<div class="empty">No projects yet.</div>' : '');
  }

  async function saveProject(id, data){
    const now = new Date().toISOString();
    const ref = id ? db.doc('projects/' + id) : db.collection('projects').doc();
    const body = {...(id ? projects[id] : {created: now, status: 'active'}), ...data, updated: now};
    delete body.id;
    projects[ref.id] = {...body, id: ref.id}; render();
    try { await ref.set(body); return ref.id; }
    catch (e) { say('Couldn’t save the project. Try again.'); return null; }
  }

  document.getElementById('pout').addEventListener('click', async e => {
    if (!db) return;
    const t = e.target, pid = (t.closest('[data-p]') || {}).dataset?.p;
    if (t.closest('#p-new')) { pform = {kind: 'oneoff'}; drawProjects(); return; }
    if (t.closest('.pf-cancel')) { pform = null; fileAfterCreate = ''; drawProjects(); return; }
    if (t.closest('.p-edit')) { pform = {id: pid, kind: projects[pid].kind}; drawProjects(); window.scrollTo({top: 0}); return; }
    if (t.closest('.pf-delete')) {
      if (!confirm('Delete this project? Its logged sessions stay in the history.')) return;
      const id = pform.id; delete projects[id]; pform = null; render();
      try { await db.doc('projects/' + id).delete(); } catch (err) { say('Couldn’t delete. Try again.'); }
      return;
    }
    if (t.closest('.pf-save')) {
      const f = document.getElementById('pform'), v = n => (f.querySelector(`[name=${n}]`) || {}).value?.trim() || '';
      if (!v('name')) { say('Give the project a name.'); return; }
      const kind = v('kind'), data = {name: v('name'), kind, goal: v('goal'), next: {text: v('next'), when: v('when')}};
      if (kind === 'recurring') {
        if (!(+v('amount') > 0)) { say('Set a target, e.g. 150.'); return; }
        data.target = {amount: +v('amount'), unit: v('unit'), period: v('period'), ...(+v('max') > +v('amount') ? {max: +v('max')} : {})};
      }
      const id = await saveProject(pform.id, data);
      pform = null;
      if (id && fileAfterCreate) { const it = all.find(x => x.id === fileAfterCreate); if (it) decide(it, 'reference', false, {project: data.name}); }
      fileAfterCreate = ''; render();
      return;
    }
    if (t.closest('.p-done')) { doneFor = pid; drawProjects(); return; }
    if (t.closest('.pn-cancel')) { doneFor = ''; drawProjects(); return; }
    if (t.closest('.pn-save')) {
      const f = t.closest('.pform'), text = f.querySelector('[name=text]').value.trim(), when = f.querySelector('[name=when]').value;
      const p = projects[pid], prev = p.next && p.next.text;
      doneFor = '';
      await saveProject(pid, {next: {text, when}, ...(prev ? {last_done: {text: prev, at: new Date().toISOString()}} : {})});
      say(prev ? `Done: ${prev}` : 'Next action saved');
      return;
    }
    if (t.closest('.p-finish')) {
      const p = projects[pid];
      await saveProject(pid, {status: p.status === 'done' ? 'active' : 'done', ...(p.status === 'done' ? {} : {finished: new Date().toISOString()})});
      say(p.status === 'done' ? `Reopened ${p.name}` : `🏁 ${p.name} done`);
      return;
    }
    const lg = t.closest('.p-log');
    if (lg) {
      const p = projects[pid], unit = (p.target || {}).unit;
      let amount = lg.dataset.a;
      if (amount === '?') { amount = prompt('How many minutes?'); if (!amount) return; }
      amount = +amount; if (!(amount > 0)) return;
      const entry = {project: pid, amount, at: new Date().toISOString()};
      const ref = db.collection('logs').doc(); logs[ref.id] = entry; drawProjects();
      try { await ref.set(entry); say(`Logged ${amount} ${UNITS[unit] ? UNITS[unit][amount === 1 ? 0 : 1] : ''} · ${p.name}`, async () => {
        delete logs[ref.id]; drawProjects(); try { await ref.delete(); } catch (err) {} });
      } catch (err) { delete logs[ref.id]; drawProjects(); say('Couldn’t log that. Try again.'); }
      return;
    }
    const ul = t.closest('.p-unlog');
    if (ul) { const id = ul.dataset.l; const keep = logs[id]; delete logs[id]; drawProjects();
      try { await db.doc('logs/' + id).delete(); } catch (err) { logs[id] = keep; drawProjects(); } }
  });
  document.getElementById('pout').addEventListener('change', e => {
    if (e.target.name === 'kind' && pform) {  // switching type redraws the form, keeping what was typed
      const f = document.getElementById('pform');
      pform = {...pform, kind: e.target.value, name: f.querySelector('[name=name]').value};
      drawProjects();
    }
  });
  // Someday / maybe: type an idea straight in
  let somedayDraft = '';
  async function addSomeday(){
    const box = document.getElementById('someday-new'); const text = (box && box.value || '').trim();
    if (!text || !db) return;
    somedayDraft = '';
    try { await db.collection('adds').doc().set({text, status: 'someday', at: new Date().toISOString()}); say('Added to Someday / maybe: ' + text); }
    catch (e) { somedayDraft = text; draw(); say('Couldn’t save that. Try again.'); }
  }
  document.getElementById('out').addEventListener('input', e => { if (e.target.id === 'someday-new') somedayDraft = e.target.value; });
  document.getElementById('out').addEventListener('keydown', e => { if (e.target.id === 'someday-new' && e.key === 'Enter') addSomeday(); });
  document.getElementById('out').addEventListener('click', e => { if (e.target.closest('#someday-add')) addSomeday(); });
  // In-tray row → project
  document.getElementById('out').addEventListener('change', e => {
    const sel = e.target.closest('.proj-pick'); if (!sel || !sel.value) return;
    const it = all.find(x => x.id === sel.dataset.id); picking = '';
    if (sel.value === '__new') { pform = {kind: 'oneoff', name: it.title.slice(0, 80)}; fileAfterCreate = it.id; location.hash = 'projects'; return; }
    decide(it, 'reference', false, {project: projects[sel.value].name});
  });

  if (db) {
    db.collection('projects').onSnapshot(snap => {
      for (const k of Object.keys(projects)) delete projects[k];
      snap.docs.forEach(d => { const v = d.data(); if (v && v.name) projects[d.id] = {...v, id: d.id}; });
      render();
    }, () => {});
    const since = new Date(); since.setDate(1); since.setMonth(since.getMonth() - 1);  // this and last month
    db.collection('logs').where('at', '>=', since.toISOString()).onSnapshot(snap => {
      for (const k of Object.keys(logs)) delete logs[k];
      snap.docs.forEach(d => { logs[d.id] = d.data(); });
      render();
    }, () => {});
  }

  function route(){
    const proj = location.hash === '#projects';
    document.getElementById('proj-view').hidden = !proj;
    document.getElementById('tray-view').hidden = proj;
    document.getElementById('to-proj').setAttribute('aria-current', proj ? 'page' : 'false');
    document.getElementById('to-tray').setAttribute('aria-current', proj ? 'false' : 'page');
    render();
  }
  window.addEventListener('hashchange', route);

  function render(){ drawSummary(); drawChips(); draw(); if (location.hash === '#projects') drawProjects(); }
  route();
})();
</script>
"""
