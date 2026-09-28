"""Human-readable views of the inbox: terminal list, INBOX.md, inbox.html."""
from __future__ import annotations

import html
from datetime import datetime
from itertools import groupby

from .model import Item, now


def age(ts: datetime, ref: datetime | None = None) -> str:
    secs = int(((ref or now()) - ts).total_seconds())
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= size:
            return f"{secs // size}{unit}"
    return "now"


def day_label(ts: datetime, ref: datetime | None = None) -> str:
    local, today = ts.astimezone(), (ref or now()).astimezone()
    delta = (today.date() - local.date()).days
    return {0: "Today", 1: "Yesterday"}.get(delta, local.strftime("%a %d %b"))


def preview(item: Item) -> str:
    bits = []
    if item.channel == "email" and item.source.get("from"):
        bits.append(f"from {item.source['from']}")
    elif item.source.get("site"):
        bits.append(item.source["site"])
    if item.note:
        bits.append(f'"{item.note.splitlines()[0]}"')
    return " — ".join(bits)


def _grouped(items: list[Item]):
    return groupby(items, key=lambda i: day_label(i.captured_at))


def header(items: list[Item]) -> str:
    if not items:
        return "Inbox — empty. 🎉 Inbox zero."
    oldest = min(i.captured_at for i in items)
    return f"Inbox — {len(items)} item{'s' * (len(items) != 1)} (oldest {age(oldest)})"


def as_text(items: list[Item]) -> str:
    out = [header(items)]
    for day, group in _grouped(items):
        out.append(f"\n{day}")
        for i in group:
            extra = f"  {preview(i)}" if preview(i) else ""
            out.append(f"  {i.icon}  {i.id}  {i.title[:60]}{flags(i)}{extra}  ·{age(i.captured_at)}")
    return "\n".join(out)


def flags(item: Item) -> str:
    hints = item.extra.get("hints") or {}
    out = " ❗" if hints.get("priority") == "high" else ""
    return out + (f" `{hints['area']}`" if hints.get("area") else "")


def as_markdown(items: list[Item]) -> str:
    """Deterministic (no relative times) so the file only changes when items do."""
    if items:
        oldest = min(i.captured_at for i in items).astimezone()
        head = f"# Inbox — {len(items)} item{'s' * (len(items) != 1)}\n\nOldest: {oldest:%a %d %b %Y}"
    else:
        head = "# Inbox — empty 🎉"
    out = [head]
    for day, group in groupby(items, key=lambda i: i.captured_at.astimezone().strftime("%a %d %b %Y")):
        out += ["", f"## {day}", ""]
        for i in group:
            link = i.source.get("url") or i.source.get("link")
            title = f"[{i.title}]({link})" if link else i.title
            line = f"- {i.icon} **{title}**{flags(i)} · {i.captured_at.astimezone():%H:%M} · `{i.id}`"
            if preview(i):
                line += f"  \n  {preview(i)}"
            snippet = i.summary or (i.content if i.channel in ("text", "chat", "email") else "")
            first = snippet.strip().splitlines()[0][:160] if snippet.strip() else ""
            if first and first != i.title:
                line += f"  \n  > {first}"
            out.append(line)
    return "\n".join(out) + "\n"


def as_html(items: list[Item]) -> str:
    e = html.escape
    channels = sorted({i.channel for i in items})
    cards = []
    for i in items:
        link = i.source.get("url")
        title = f'<a href="{e(link)}">{e(i.title)}</a>' if link else e(i.title)
        body = e((i.summary or i.content)[:400])
        cards.append(
            f'<article data-ch="{e(i.channel)}"><header><span class="ic">{i.icon}</span>'
            f"<h3>{title}</h3><time>{e(age(i.captured_at))}</time></header>"
            f'<p class="meta">{e(day_label(i.captured_at))} · {e(i.channel)} via {e(i.via)}'
            f"{' · ' + e(preview(i)) if preview(i) else ''}</p>"
            f'<p class="body">{body}</p><code>{e(i.id)}</code></article>'
        )
    buttons = "".join(f'<button data-f="{e(c)}">{e(c)}</button>' for c in channels)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>GTD Inbox</title>
<style>
:root{{--bg:#fafaf9;--card:#fff;--fg:#1c1917;--mut:#78716c;--line:#e7e5e4;--acc:#2563eb}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1c1917;--card:#292524;--fg:#f5f5f4;--mut:#a8a29e;--line:#44403c;--acc:#60a5fa}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:760px;margin:auto;padding:24px 16px}}
h1{{font-size:22px;margin:0 0 12px}} a{{color:var(--acc)}}
nav{{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}}
nav input{{flex:1 1 200px;padding:6px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg)}}
button{{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:999px;padding:4px 10px;cursor:pointer}}
button.on{{background:var(--acc);color:#fff;border-color:var(--acc)}}
article{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:10px 0}}
article header{{display:flex;gap:8px;align-items:baseline}} h3{{flex:1;margin:0;font-size:16px;overflow-wrap:anywhere}}
time,.meta,code{{color:var(--mut);font-size:13px}} .body{{white-space:pre-wrap;margin:6px 0;overflow-wrap:anywhere}}
</style></head><body><main><h1>{e(header(items))}</h1>
<nav><input id="q" placeholder="Search…"><button data-f="" class="on">all</button>{buttons}</nav>
{''.join(cards)}
</main><script>
let f="";const q=document.getElementById("q");
function apply(){{const s=q.value.toLowerCase();document.querySelectorAll("article").forEach(a=>{{
a.hidden=(f&&a.dataset.ch!==f)||(s&&!a.textContent.toLowerCase().includes(s));}});}}
document.querySelectorAll("nav button").forEach(b=>b.onclick=()=>{{f=b.dataset.f;
document.querySelectorAll("nav button").forEach(x=>x.classList.toggle("on",x===b));apply();}});
q.oninput=apply;
</script></body></html>
"""
