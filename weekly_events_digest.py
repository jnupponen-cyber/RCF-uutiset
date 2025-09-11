#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, re, asyncio, textwrap
from datetime import datetime, timedelta
import zoneinfo
import discord

TZ = os.getenv("TZ", "Europe/Helsinki")
tz = zoneinfo.ZoneInfo(TZ)

GUILD_ID = int(os.environ["GUILD_ID"])
TARGET_CHANNEL_ID = int(os.environ["TARGET_CHANNEL_ID"])
CAL_CHANNEL_IDS = [int(x.strip()) for x in os.environ["CAL_CHANNEL_IDS"].split(",")]

# ----- apurit -----
MONTHS_EN = {  # Discord/Sesh käyttää engl. kuukausilyhenteitä
    'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12
}
DAY_HDR = re.compile(r'^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*\[(\w{3})\s+(\d{1,2})\]', re.I)
EVENT_LINE = re.compile(r'^\s*(\d{1,2})\s*:\s*(\d{2})\s+(.*)$')

def parse_event_lines(block:str, year:int):
    events = []
    cur_date = None
    for raw in block.splitlines():
        raw = raw.strip()
        if not raw: 
            continue
        mday = DAY_HDR.match(raw)
        if mday:
            mon = MONTHS_EN[mday.group(2).title()]
            day = int(mday.group(3))
            cur_date = datetime(year, mon, day, tzinfo=tz)
            continue
        m = EVENT_LINE.match(raw)
        if m and cur_date:
            hh, mm = int(m.group(1)), int(m.group(2))
            dt = cur_date.replace(hour=hh, minute=mm)
            # poista häntäsanat (”neljän päivän päästä” tms.)
            text = re.sub(r'\s+\w.+päästä$', '', m.group(3)).strip()
            # jaa otsikko + linkki, jos linkki markdownina
            # (Embed-listauksessa otsikot ovat usein linkkeinä)
            title = text
            events.append((dt, title))
    return events

def format_digest(events):
    if not events:
        return "Tällä viikolla ei näytä olevan kalenterissa tapahtumia. 🚲"
    by_day = {}
    for dt, title in events:
        by_day.setdefault(dt.date(), []).append((dt, title))
    lines = ["🗓️ **Ride Club Finland – viikon tapahtumat**",
             f"_Aikavyöhyke: {TZ}_\n"]
    for d in sorted(by_day):
        lines.append(f"**{d.strftime('%a %d.%m.')}**")
        for dt, title in sorted(by_day[d], key=lambda x: x[0]):
            lines.append(f"• {dt.strftime('%H:%M')} — {title}")
        lines.append("")
    lines.append("💡 Lisää puuttuva tapahtuma kalenterikanavaan niin se tulee automaattisesti mukaan.")
    return "\n".join(lines)

# ----- Discord -----
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    try:
        guild = client.get_guild(GUILD_ID)
        now = datetime.now(tz)
        monday = now - timedelta(days=now.weekday())
        next_monday = monday + timedelta(days=7)

        all_events = []
        for ch_id in CAL_CHANNEL_IDS:
            ch = await client.fetch_channel(ch_id)
            pins = await ch.pins()
            # Etsi uusin pin, joka sisältää "Event Listings"
            pins_sorted = sorted(pins, key=lambda m: m.created_at, reverse=True)
            source_text = None
            for msg in pins_sorted:
                txt = (msg.content or "")
                if "Event Listings" in txt or any(e.title for e in msg.embeds):
                    # Käytetään mieluummin viestin plain-tekstiä (Sesh listaus)
                    source_text = txt if txt else "\n".join(
                        (e.description or "") for e in msg.embeds if e.description
                    )
                    if source_text:
                        break
            if not source_text:
                continue

            # Listauksessa voi olla useamman kuukauden blokki – käytetään kuluvaa/vuotta
            year = now.year
            events = parse_event_lines(source_text, year)

            # suodata viikon väliin [ma..su]
            week_ev = [(dt, title) for dt, title in events if monday <= dt < next_monday]
            all_events.extend(week_ev)

        digest = format_digest(sorted(all_events, key=lambda x: x[0]))
        target = await client.fetch_channel(TARGET_CHANNEL_ID)
        # Jos pitkä, jaa kahteen viestiin
        for chunk in textwrap.wrap(digest, width=1800, break_long_words=False, break_on_hyphens=False):
            await target.send(chunk)

    finally:
        await client.close()

if __name__ == "__main__":
    client.run(os.environ["DISCORD_TOKEN"])
