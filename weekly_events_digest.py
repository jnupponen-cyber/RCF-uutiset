#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RCF Weekly Events Digest
- Lukee kalenterikanavien pinnatun "Event Listings" -viestin
- Parsii viikon (ma–su) tapahtumat
- Postaa koosteen TARGET_CHANNEL_ID-kanavalle
"""

import os, re, asyncio, textwrap
from datetime import datetime, timedelta
import zoneinfo
import discord

# ---------- Asetukset ympäristömuuttujista ----------
TZ = os.getenv("TZ", "Europe/Helsinki")
tz = zoneinfo.ZoneInfo(TZ)

GUILD_ID = int(os.environ["GUILD_ID"])
TARGET_CHANNEL_ID = int(os.environ["TARGET_CHANNEL_ID"])
CAL_CHANNEL_IDS = [int(x.strip()) for x in os.environ["CAL_CHANNEL_IDS"].split(",")]

# ---------- Regexit ja apusanakirjat ----------
MONTHS_EN = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}

# Otsikko: "Today [Sep 12]" / "Friday [Sep 12]"
DAY_HDR = re.compile(
    r'^(Today|Tomorrow|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*\[(\w{3})\s+(\d{1,2})\]',
    re.I
)

# Rivi päiväotsikon alla: "08:00 Title …"
EVENT_LINE_CLOCK_FIRST = re.compile(r'^\s*(\d{1,2})\s*:\s*(\d{2})\s+(.*)$')

# Rivi kuukauden alla ilman päiväotsikkoa: "Oct 02 19:00 Title …"
EVENT_LINE_MONTH_FIRST = re.compile(
    r'^\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+(\d{2})\s*:\s*(\d{2})\s+(.*)$',
    re.I
)

RELATIVE_TAIL = re.compile(r'\s+(päivän|päivien|kuukauden|kuukausien|viikon|viikkojen)\s+päästä$', re.I)

# ---------- Parseri ----------
def parse_events_from_text(text: str, year_hint: int, now: datetime):
    """
    Palauttaa listan (datetime, title)
    Hyväksyy kolme muotoa: DAY_HDR + HH:MM, sekä "Mon dd HH:MM" rivit.
    """
    events = []
    cur_date = None  # asetetaan kun kohdataan DAY_HDR

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        # 1) Päiväotsikko
        mday = DAY_HDR.match(line)
        if mday:
            mon_abbr = mday.group(2).title()
            day = int(mday.group(3))
            month = MONTHS_EN.get(mon_abbr)
            if not month:
                continue
            # Vuoden arvio: jos listaus menee vuodenvaihteen yli, säädä tarvittaessa
            year = year_hint
            dt_tmp = datetime(year, month, day, tzinfo=tz)
            if (month < now.month - 6):  # esim. tammi helmikuu näkyy joulukuussa → seuraava vuosi
                year += 1
                dt_tmp = dt_tmp.replace(year=year)
            cur_date = dt_tmp.replace(hour=0, minute=0, second=0, microsecond=0)
            continue

        # 2) HH:MM -rivi päiväotsikon alla
        m1 = EVENT_LINE_CLOCK_FIRST.match(line)
        if m1 and cur_date:
            hh, mm = int(m1.group(1)), int(m1.group(2))
            title = RELATIVE_TAIL.sub('', m1.group(3)).strip()
            dt = cur_date.replace(hour=hh, minute=mm)
            events.append((dt, title))
            continue

        # 3) "Oct 02 19:00 Title" -rivi ilman päiväotsikkoa
        m2 = EVENT_LINE_MONTH_FIRST.match(line)
        if m2:
            mon_abbr = m2.group(1).title()
            month = MONTHS_EN.get(mon_abbr)
            day = int(m2.group(2))
            hh, mm = int(m2.group(3)), int(m2.group(4))
            title = RELATIVE_TAIL.sub('', m2.group(5)).strip()
            year = year_hint
            dt = datetime(year, month, day, hh, mm, tzinfo=tz)
            # vuodenvaihteen korjaus
            if (month < now.month - 6):
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
    lines = [
        "🗓️ **Ride Club Finland – viikon tapahtumat**",
        f"_Aikavyöhyke: {TZ}_\n"
    ]
    for d in sorted(by_day):
        lines.append(f"**{d.strftime('%a %d.%m.')}**")
        for dt, title in sorted(by_day[d], key=lambda x: x[0]):
            lines.append(f"• {dt.strftime('%H:%M')} — {title}")
        lines.append("")
    lines.append("💡 Lisää tapahtuma kalenterikanavaan → mukana automaattisesti ensi koosteessa.")
    return "\n".join(lines)

# ---------- Discord-client ----------
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    try:
        now = datetime.now(tz)
        monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        next_monday = monday + timedelta(days=7)

        all_events = []

        for ch_id in CAL_CHANNEL_IDS:
            ch = await client.fetch_channel(ch_id)
            pins = await ch.pins()

            # Etsi uusin pin, joka sisältää listauksen
            pins_sorted = sorted(pins, key=lambda m: m.created_at, reverse=True)
            source_text = None

            for msg in pins_sorted:
                # 1) Plain text
                if msg.content and ("Event Listings" in msg.content or "[" in msg.content):
                    source_text = msg.content
                # 2) Embed-kuvaukset varalle
                elif msg.embeds:
                    parts = []
                    for e in msg.embeds:
                        if e.description:
                            parts.append(e.description)
                        # joskus listaus on kentissä
                        for f in (e.fields or []):
                            if f.value:
                                parts.append(f.value)
                    if parts:
                        source_text = "\n".join(parts)

                if source_text:
                    break

            if not source_text:
                continue  # ei sopivaa pinniä

            events = parse_events_from_text(source_text, year_hint=now.year, now=now)
            # suodata kuluvan viikon väliin
            week_ev = [(dt, title) for dt, title in events if monday <= dt < next_monday]
            all_events.extend(week_ev)

        all_events.sort(key=lambda x: x[0])
        digest = format_digest(all_events)

        target = await client.fetch_channel(TARGET_CHANNEL_ID)
        # Pilko tarvittaessa kahteen viestiin
        for chunk in textwrap.wrap(digest, width=1800, break_long_words=False, break_on_hyphens=False):
            await target.send(chunk)

    finally:
        await client.close()

if __name__ == "__main__":
    client.run(os.environ["DISCORD_TOKEN"])
