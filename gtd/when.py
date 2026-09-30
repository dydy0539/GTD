"""Find a date/time and a place in free text (English, Chinese, Japanese).

    地址：The Riverwalk, 20 Upper Circular Road, Singapore 058416
    时间：星期三下午2点15 @🦩sofia
      → Wed 14:15 (next Wednesday), location "The Riverwalk, …", rest "@🦩sofia"

    Haircut friday at 3pm
      → Fri 15:00, no location, rest "Haircut"

Deliberately rule-based and conservative: when in doubt it finds nothing. With a
place, a time is enough; without one, it needs both a day and a time.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

ZH_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7}
JA_DAYS = {"月": 1, "火": 2, "水": 3, "木": 4, "金": 5, "土": 6, "日": 7}
EN_DAYS = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 7}
EN_MONTHS = {m: i for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split(), start=1)}

LOCATION_LABEL = re.compile(
    r"(?im)^\s*(?:地址|地點|地点|位置|場所|住所|会場|address|location|venue|where|place)\s*[:：]\s*(.+?)\s*$")
TIME_LABEL = re.compile(r"(?im)^\s*(?:时间|時間|日时|日時|日期|time|when|date)\s*[:：]\s*")
POSTAL_LINE = re.compile(r"(?im)^.*(?:\bsingapore\s+\d{6}\b|〒\s?\d{3}-\d{4}).*$")

NEXT_WEEK = r"(?P<next>下个?|下個|下|来週|來週|next\s+)?"
WEEKDAY = re.compile(
    NEXT_WEEK + r"(?:(?:星期|周|週|礼拜|禮拜)(?P<zh>[一二三四五六日天])"
    r"|(?P<ja>[月火水木金土日])曜日?"
    r"|\b(?P<en>mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?\b)", re.I)
RELATIVE = re.compile(r"(?P<d0>今天|今日|today)|(?P<d1>明天|明日|tomorrow)|(?P<d2>后天|後天|明後日)", re.I)
ISO_DATE = re.compile(r"\b(?P<y>20\d\d)[-/.](?P<m>\d{1,2})[-/.](?P<d>\d{1,2})\b")
CJK_DATE = re.compile(r"(?:(?P<y>20\d\d)年)?(?P<m>\d{1,2})月(?P<d>\d{1,2})[日号號]")
EN_DATE = re.compile(
    r"\b(?:(?P<d1>\d{1,2})(?:st|nd|rd|th)?\s+(?P<m1>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
    r"|(?P<m2>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?P<d2>\d{1,2})(?:st|nd|rd|th)?)\b", re.I)
CJK_TIME = re.compile(
    r"(?P<ap>上午|早上|早晨|中午|下午|晚上|傍晚|午前|午後|夜)?\s*(?P<h>\d{1,2})\s*(?:点|點|時|时)"
    r"\s*(?:(?P<half>半)|(?P<m>\d{1,2})\s*分?)?")
EN_TIME = re.compile(
    r"\b(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))?\s*(?P<ap>am|pm|a\.m\.|p\.m\.)(?![a-z])"
    r"|\b(?P<h24>[01]?\d|2[0-3])[:：](?P<m24>[0-5]\d)\b", re.I)
PM_WORDS = {"下午", "晚上", "傍晚", "午後", "夜", "pm", "p.m."}


@dataclass
class Found:
    start: datetime          # naive, in the event's local time zone
    location: str
    rest: str                # the text with the time and place removed


def _time(text: str) -> tuple[time, tuple[int, int]] | None:
    m = CJK_TIME.search(text)
    if m:
        h = int(m["h"])
        minute = 30 if m["half"] else int(m["m"] or 0)
        ap = m["ap"] or ""
        if ap in PM_WORDS and h < 12:
            h += 12
        elif ap == "中午" and h < 11:
            h += 12
        if h < 24 and minute < 60:
            return time(h, minute), m.span()
    m = EN_TIME.search(text)
    if m:
        if m["h24"]:
            return time(int(m["h24"]), int(m["m24"])), m.span()
        h, minute = int(m["h"]), int(m["m"] or 0)
        pm = m["ap"].lower().startswith("p")
        if 1 <= h <= 12 and minute < 60:
            return time(h % 12 + (12 if pm else 0), minute), m.span()
    return None


def _date(text: str, today: date) -> tuple[date, tuple[int, int]] | None:
    for rx in (ISO_DATE, CJK_DATE):
        m = rx.search(text)
        if m:
            year = int(m["y"]) if m["y"] else today.year
            try:
                d = date(year, int(m["m"]), int(m["d"]))
            except ValueError:
                continue
            if not m["y"] and d < today:
                d = d.replace(year=year + 1)
            return d, m.span()
    m = EN_DATE.search(text)
    if m:
        month = EN_MONTHS[(m["m1"] or m["m2"]).lower()[:3]]
        try:
            d = date(today.year, month, int(m["d1"] or m["d2"]))
        except ValueError:
            d = None
        if d:
            return (d if d >= today else d.replace(year=today.year + 1)), m.span()
    m = RELATIVE.search(text)
    if m:
        offset = 0 if m["d0"] else 1 if m["d1"] else 2
        return today + timedelta(days=offset), m.span()
    m = WEEKDAY.search(text)
    if m:
        wd = ZH_DIGITS.get(m["zh"] or "") or JA_DAYS.get(m["ja"] or "") or EN_DAYS[(m["en"] or "mon").lower()[:3]]
        ahead = (wd - today.isoweekday()) % 7
        if m["next"]:
            ahead += 7 if ahead == 0 or not m["next"].lower().startswith("next") else 0
            if m["next"].startswith(("下", "来", "來")):  # 下周三 = Wednesday of next week
                ahead = (7 - today.isoweekday()) + wd
        return today + timedelta(days=ahead), m.span()
    return None


def find(text: str, now: datetime) -> Found | None:
    """A time (and a place, if given) in `text`, interpreted relative to `now` (local, naive)."""
    loc_match = LOCATION_LABEL.search(text) or POSTAL_LINE.search(text)
    if loc_match:
        location = (loc_match.group(1) if loc_match.re is LOCATION_LABEL else loc_match.group(0)).strip()
        rest = (text[:loc_match.start()] + text[loc_match.end():]).strip()
    else:
        location, rest = "", text.strip()

    t = _time(rest)
    if not t:
        return None
    clock, span = t
    rest = rest[:span[0]] + " " + rest[span[1]:]
    d = _date(rest, now.date())
    if d:
        day, span = d
        rest = rest[:span[0]] + " " + rest[span[1]:]
    elif not location:  # "call mum at 3pm" is a to-do, not an appointment
        return None
    else:  # a time without a day: the next time the clock shows it
        day = now.date() if clock > now.time() else now.date() + timedelta(days=1)
    rest = TIME_LABEL.sub("", rest)
    rest = re.sub(r"[ \t]+", " ", rest).strip(" \n,，。;；:：")
    rest = re.sub(r"(?i)(?:\s+(?:at|on|@|,))+$", "", rest).strip()  # "Haircut at" → "Haircut"
    return Found(datetime.combine(day, clock), location, rest)


def guess_timezone(location: str, default: str) -> str:
    loc = location.lower()
    if "singapore" in loc or "新加坡" in loc:
        return "Asia/Singapore"
    if any(k in loc for k in ("japan", "tokyo", "日本", "東京", "〒", "大阪", "osaka")):
        return "Asia/Tokyo"
    if "hong kong" in loc or "香港" in loc:
        return "Asia/Hong_Kong"
    return default
