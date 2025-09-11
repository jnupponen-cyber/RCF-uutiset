#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RCF Weekly Events Digest from Sesh ICS
- Hakee Seshin /link-komennolla tuotetun ICS-syötteen
- Laajentaa toistuvat tapahtumat, suodattaa kuluvaan viikkoon (ma–su)
- Postaa koosteen Discordiin TARGET_CHANNEL_ID -kanavalle
"""

import os, textwrap
from datetime import datetime, timedelta, time as dtime
import zoneinfo
import requests
from icalendar import Calendar
import recurring_ical_events
import discord

TZ = os.getenv("TZ", "Europe/Helsinki")
tz = zoneinfo.ZoneInfo(TZ)

TARGET_CHANNEL_ID = int(os.environ["TARGET_CHANNEL_ID"])
SESH_ICS_URL = os.environ["SESH_ICS_URL"]

def to_local(dt):
    """Varmista aikavyöhyke ja palauta Europe/Helsinki -aikana."""
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            # oletetaan paikallinen jos tz puuttuu
            return dt.replace(tzinfo=tz)
        return dt.astimezone(tz)
    # all-day (pelkkä date) -> klo 00:00 paikallista
    return datetime.combine(dt, dtime(0, 0), tz)

def load_events_between(url, start, end):
    """Lataa ICS ja palauta [(dtstart_local, title)] annetulta aikaväliltä."""
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    cal = Calendar.from_ical(r.content)
    occs = recurring_ical_events.of(cal).between(start, end)

    out = []
    for ev in occs:
        dt = ev.get('dtstart').dt
        dt = to_local(dt)
        title = str(ev.get('summary', '') or '').strip()
        loc = str(ev.get('location', '') or '').strip()
        if loc:
            title = f"{title} ({loc})"
        out.append((dt, title))
    out.sort(key=lambda x: x[0])
    return out

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
    lines.append("💡 Lisää tapahtuma Seshillä → kooste päivittyy automaattisesti.")
    return "\n".join(lines)

# --- Discord-lähetys ---
intents = discord.Intents.default()
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    try:
        now = datetime.now(tz)
        monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        next_monday = monday + timedelta(days=7)

        events = load_events_between(SESH_ICS_URL, monday, next_monday)
        digest = format_digest(events)

        ch = await client.fetch_channel(TARGET_CHANNEL_ID)
        for chunk in textwrap.wrap(digest, width=1800, break_long_words=False, break_on_hyphens=False):
            await ch.send(chunk)
    finally:
        await client.close()

if __name__ == "__main__":
    client.run(os.environ["DISCORD_TOKEN"])
