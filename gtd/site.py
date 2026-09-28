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
    "feed": "YouTube & feeds", "cli": "Laptop", "claude": "Claude",
}


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
    snippet = re.sub(r"^(View (this post|in browser)[^h]*https?://\S+\s*|View in browser\s*\|?\s*)", "", snippet, flags=re.I)
    title = cal["summary"] if cal and cal.get("summary") else i.title
    if snippet.lower().startswith(i.title.lower()[:40]):  # preview that only repeats the title
        snippet = snippet[len(i.title):].strip(" .·-—:") if len(snippet) > len(i.title) + 20 else ""
    return {
        "id": i.id, "title": title, "icon": i.icon, "channel": i.channel,
        "via": i.via, "source": SOURCES.get(i.via, i.via),
        "url": src.get("url") or src.get("link") or "",
        "at": i.captured_at.isoformat(), "who": who[:80],
        "note": i.note, "snippet": snippet[:240],
        "tags": i.tags, "priority": hints.get("priority", ""),
        "calendar": {k: cal[k] for k in ("start", "timezone", "location", "add_link", "status", "html_link")
                     if k in cal} if cal else None,
    }


def page(items: list[Item]) -> str:
    data = json.dumps({"generated": now().isoformat(), "items": [_record(i) for i in items]},
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
.empty{color:var(--muted);padding:28px 16px;text-align:center;background:var(--surface);border:1px dashed var(--line);border-radius:10px}
@media (max-width:480px){.it{grid-template-columns:24px 1fr}.age{grid-column:2;text-align:left}}
@media (prefers-reduced-motion:no-preference){.it{transition:background .15s}.it:hover{background:var(--ground)}}
</style>
<div class="wrap">
  <header class="head">
    <h1>In-tray</h1>
    <div class="sum" id="sum"></div>
    <div class="gen" id="gen"></div>
  </header>
  <div class="tools">
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
<script type="application/json" id="data">__DATA__</script>
<script>
(function(){
  const D = JSON.parse(document.getElementById('data').textContent);
  const items = D.items;
  const NOW = Date.now();
  const store = {get(k){try{return localStorage.getItem(k)}catch(e){return null}},
                 set(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
  let group = store.get('gtd.group') || 'kind', source = '', q = '';

  const hrs = it => (NOW - Date.parse(it.at)) / 36e5;
  const age = h => h < 1 ? Math.max(1, Math.round(h*60)) + 'm' : h < 48 ? Math.round(h) + 'h' : Math.round(h/24) + 'd';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmtDay = d => d.toLocaleDateString(undefined, {weekday:'short', day:'numeric', month:'short'});

  const KINDS = [
    ['attention','Needs attention', it => it.priority === 'high'],
    ['appointments','Appointments', it => !!it.calendar],
    ['notes','Notes & to-dos', it => ['text','message','image','file','audio'].includes(it.channel) && ['telegram','email-to-self','cli','claude'].includes(it.via)],
    ['research','Research to read', it => it.tags.includes('research')],
    ['pubs','Publications', it => it.tags.includes('read-later')],
    ['videos','Videos & podcasts', it => ['youtube','podcast'].includes(it.channel)],
    ['other','Other', () => true],
  ];
  const kindOf = it => KINDS.find(k => k[2](it))[0];

  // summary strip
  const oldest = items.reduce((m, it) => Math.max(m, hrs(it)), 0);
  const stale = items.filter(it => hrs(it) > 48).length;
  document.getElementById('sum').innerHTML =
    `<span><b>${items.length}</b> in the tray</span>` +
    (items.length ? `<span${oldest > 48 ? ' class="warn"' : ''}>oldest <b>${age(oldest)}</b></span>` : '') +
    (stale ? `<span class="warn"><b>${stale}</b> waiting over 2 days</span>` : '') +
    `<span><b>${items.filter(it => it.priority === 'high').length}</b> need attention</span>`;
  document.getElementById('gen').textContent =
    'Updated ' + new Date(D.generated).toLocaleString(undefined, {weekday:'short', hour:'2-digit', minute:'2-digit'});

  // source chips
  const counts = {};
  items.forEach(it => counts[it.source] = (counts[it.source] || 0) + 1);
  const chips = document.getElementById('chips');
  function drawChips(){
    chips.innerHTML = [['', 'All', items.length], ...Object.entries(counts).sort((a,b) => b[1]-a[1]).map(([s,n]) => [s,s,n])]
      .map(([v,l,n]) => `<button class="chip" data-s="${esc(v)}" aria-pressed="${v === source}">${esc(l)}<span class="n">${n}</span></button>`).join('');
  }
  chips.addEventListener('click', e => { const b = e.target.closest('.chip'); if (!b) return; source = b.dataset.s; drawChips(); draw(); });

  document.querySelectorAll('.seg button').forEach(b => b.addEventListener('click', () => {
    group = b.dataset.g; store.set('gtd.group', group); draw();
  }));
  document.getElementById('q').addEventListener('input', e => { q = e.target.value.trim().toLowerCase(); draw(); });

  function row(it){
    const h = hrs(it);
    const title = it.url ? `<a class="t" href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.title)}</a>` : `<span class="t">${esc(it.title)}</span>`;
    const meta = [it.who, it.source].filter(Boolean).map(esc).join(' · ');
    const tags = [...(it.priority === 'high' ? ['<span class="tag p-high">high</span>'] : []),
                  ...(it.priority === 'low' ? ['<span class="tag">low</span>'] : []),
                  ...it.tags.map(t => `<span class="tag">${esc(t)}</span>`)].join('');
    let cal = '';
    if (it.calendar) {
      const c = it.calendar, when = new Date(c.start);
      const label = when.toLocaleString(undefined, {weekday:'short', day:'numeric', month:'short'}) + ' ' + c.start.slice(11,16);
      const act = c.status === 'added' ? (c.html_link ? `<a href="${esc(c.html_link)}" target="_blank" rel="noopener">On your calendar ✓</a>` : 'On your calendar ✓')
                                       : `<a href="${esc(c.add_link)}" target="_blank" rel="noopener">Add to Google Calendar</a>`;
      cal = `<div class="cal">📅 <b>${esc(label)}</b><span>${esc(c.timezone.split('/').pop().replace('_',' '))} · ${esc(c.location)}</span>${act}</div>`;
    }
    return `<article class="it ${esc(it.priority)}"><div class="ic" aria-hidden="true">${esc(it.icon)}</div>
      <div class="main">${title}${meta ? `<div class="meta">${meta}</div>` : ''}
        ${it.note ? `<div class="note">${esc(it.note)}</div>` : ''}
        ${it.snippet ? `<div class="snip">${esc(it.snippet)}</div>` : ''}${cal}
        ${tags ? `<div class="tags">${tags}</div>` : ''}</div>
      <div class="age${h > 48 ? ' stale' : ''}" title="${esc(new Date(it.at).toLocaleString())}">${age(h)}</div></article>`;
  }

  function draw(){
    document.querySelectorAll('.seg button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.g === group)));
    const shown = items.filter(it => (!source || it.source === source) &&
      (!q || [it.title, it.who, it.note, it.snippet, it.tags.join(' '), it.source].join(' ').toLowerCase().includes(q)));
    const out = document.getElementById('out');
    if (!shown.length) { out.innerHTML = `<div class="empty">${items.length ? 'Nothing matches this search or filter.' : 'The tray is empty. Inbox zero.'}</div>`; return; }
    let groups;
    if (group === 'kind') groups = KINDS.map(([k, label]) => [label, shown.filter(it => kindOf(it) === k)]);
    else if (group === 'source') groups = Object.keys(counts).map(s => [s, shown.filter(it => it.source === s)]);
    else {
      const byDay = new Map();
      shown.forEach(it => { const d = fmtDay(new Date(it.at)); byDay.set(d, [...(byDay.get(d) || []), it]); });
      groups = [...byDay.entries()];
    }
    out.innerHTML = groups.filter(g => g[1].length).map(([label, list]) =>
      `<section><h2>${esc(label)} <span class="n">${list.length}</span></h2><div class="list">${list.map(row).join('')}</div></section>`).join('');
  }
  drawChips(); draw();
})();
</script>
"""
