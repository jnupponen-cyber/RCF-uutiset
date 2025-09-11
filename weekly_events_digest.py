#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RCF Weekly Events Digest (v3)
- Hakee kalenterikanavien "Event Listings" -listauksen (pinnit tai viimeiset viestit)
- Tunnistaa otsikot Today/Tomorrow/Monday..Sunday [Sep 12] + "Oct 02 19:00 …" -rivit
- Suodattaa kuluvan viikon (ma–su) tapahtumat (Europe/Helsinki)
- Postaa koosteen TARGET_CHANNEL_ID-kanavalle
"""

import os, re, textwrap
from datetime import datetime, timedelta
import zoneinfo
import discord

# ----- Asetukset -----
TZ = os.getenv("TZ", "Europe/Helsinki")
tz = zoneinfo.ZoneInfo(TZ)

GUILD_ID = int(os.environ["GUILD_ID"])
TARGET_CHANNEL_ID = int(os.environ["TARGET_CHANNEL_ID"])
CAL_CHANNEL_IDS = [int(x.strip()) for x in os.environ["CAL_CHANNEL_IDS"].split(",")]

# ----- Regexit -----
MONTHS_EN = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}

DAY_HDR = re.compile(
    r'^\s*(?:[\W_]{0,3})?(Today|Tomorrow|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*\[(\w{3})\s+(\d{1,2})\]',
    re.I | re.U
)

EVENT_LINE_CLOCK_FIRST = re.compile(r'.*?(\d{1,2})\s*[:.]\s*(\d{2})\s+(.*)$', re.U)

EVENT_LINE_MONTH_FIRST = re.compile(
    r'^\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+(\d{2})\s*[:.]\s*(\d{2})\s+(.*)$',
    re.I | re.U
)

RELATIVE_TAIL = re.compile(r'\s+(päivän|päivien|kuukauden|kuukausien|viikon|viikkojen)\s+päästä$', re.I)

def parse_events_from_text(text: str, year_hint: int, now: datetime):
    events = []
    cur_date = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        mday = DAY_HDR.match(line)
        if mday:
            mon_abbr = mday.group(2).title()
            day = int(mday.group(3))
            month = MONTHS_EN.get(mon_abbr)
            if not month:
                continue
            year = year_hint
            dt_tmp = datetime(year, month, day, tzinfo=tz)
            if month < now.month - 6:  # vuodenvaihteen yli
                dt_tmp = dt_tmp.replace(year=year + 1)
            cur_date = dt_tmp.replace(hour=0, minute=0, second=0, microsecond=0)
            continue

        m1 = EVENT_LINE_CLOCK_FIRST.match(line)
        if m1 and cur_date:
            hh, mm = int(m1.group(1)), int(m1.group(2))
            title = RELATIVE_TAIL.sub('', m1.group(3)).strip()
            events.append((cur_date.replace(hour=hh, minute=mm), title))
            continue

        m2 = EVENT_LINE_MONTH_FIRST.match(line)
        if m2:
            mon_abbr = m2.group(1).title()
            month = MONTHS_EN.get(mon_abbr)
            day = int(m2.group(2))
            hh, mm = int(m2.group(3)), int(m2.group(4))
            title = RELATIVE_TAIL.sub('', m2.group(5)).strip()
            year = year_hint
            dt = datetime(year, month, day, hh, mm, tzinfo=tz)
            if month < now.month - 6:
                dt = dt.replace(year=year + 1)
            events.append((dt, title))
            continue
    return events

def format_digest(events):
    if not events:
        return "Tällä viikolla ei näytä olevan kalenterissa tapahtumia. 🚲"
    by_day = {}
    for dt, title in events:
        by_day.setdefault(dt.date(), []).append((dt, title))
    lines = ["🗓️ **Ride Club Finland – viikon tapahtumat**", f"_Aikavyöhyke: {TZ}_\n"]
    for d in sorted(by_day):
        lines.append(f"**{d.strftime('%a %d.%m.')}**")
        for dt, title in sorted(by_day[d], key=lambda x: x[0]):
            lines.append(f"• {dt.strftime('%H:%M')} — {title}")
        lines.append("")
    lines.append("💡 Lisää tapahtuma kalenterikanavaan → mukana automaattisesti ensi koosteessa.")
    return "\n".join(lines)

# ----- Discord -----
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

def extract_text_from_message(msg: discord.Message) -> str:
    parts = []
    if msg.content:
        parts.append(msg.content)
    if msg.embeds:
        for e in msg.embeds:
            if e.title:        # << tärkeä lisäys
                parts.append(str(e.title))
            if e.description:
                parts.append(e.description)
            for f in (e.fields or []):
                if f.value:
                    parts.append(f.value)
    return "\n".join(parts).strip()

async def fetch_event_listing_text(channel: discord.TextChannel) -> str | None:
    """Hae listaus: ensin pinneistä (uudella tavalla), sitten viimeisistä viesteistä."""
    # 1) Pins (uusi API)
    pin_count = 0
    async for msg in channel.pins(limit=50):
        pin_count += 1
        text = extract_text_from_message(msg)
        if text and ("Event Listings" in text or text.startswith("Showing ") or "Times displayed" in text):
            print(f"[DEBUG] Found listing in pin {msg.id} (len={len(text)})")
            return text
    print(f"[DEBUG] Channel {channel.id} pins: {pin_count}")

    # 2) Recent messages fallback
    async for msg in channel.history(limit=200, oldest_first=False):
        text = extract_text_from_message(msg)
        if text and ("Event Listings" in text or text.startswith("Showing ") or "Times displayed" in text):
            print(f"[DEBUG] Found listing in recent message {msg.id} (len={len(text)})")
            return text
    return None

@client.event
async def on_ready():
    try:
        now = datetime.now(tz)
        monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        next_monday = monday + timedelta(days=7)

        all_events = []
        for ch_id in CAL_CHANNEL_IDS:
            ch = await client.fetch_channel(ch_id)
            text = await fetch_event_listing_text(ch)
            if not text:
                print(f"[DEBUG] Channel {ch_id}: no listing found")
                continue
            events = parse_events_from_text(text, year_hint=now.year, now=now)
            print(f"[DEBUG] Channel {ch_id}: parsed={len(events)}")
            week_ev = [(dt, t) for dt, t in events if monday <= dt < next_monday]
            print(f"[DEBUG] Channel {ch_id}: this_week={len(week_ev)}")
            all_events.extend(week_ev)

        all_events.sort(key=lambda x: x[0])
        digest = format_digest(all_events)

        target = await client.fetch_channel(TARGET_CHANNEL_ID)
        for chunk in textwrap.wrap(digest, width=1800, break_long_words=False, break_on_hyphens=False):
            await target.send(chunk)

    finally:
        await client.close()

if __name__ == "__main__":
    client.run(os.environ["DISCORD_TOKEN"])
