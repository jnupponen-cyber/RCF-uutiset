#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RCF Weekly Events Digest from Sesh ICS (resilient)
- Primääri: laajentaa toistuvat tapahtumat recurring_ical_events-kirjastolla
- Fallback: jos ICS sisältää poikkeavia kenttiä (esim. DTSTART listana), parsitaan VEVENTit käsin (ei RRULE-laajennusta)
- Suodattaa kuluvan viikon (ma–su) Europe/Helsinki
- Postaa koosteen Discordiin
"""

import os, traceback
from datetime import datetime, timedelta, time as dtime
import zoneinfo
import requests
from icalendar import Calendar
import discord

# Yritetään tuoda laajennuskirjasto – jos ei onnistu, käytetään fallbackiä
try:
    import recurring_ical_events
    HAS_RECUR = True
except Exception:
    HAS_RECUR = False

TZ = os.getenv("TZ", "Europe/Helsinki")
tz = zoneinfo.ZoneInfo(TZ)

TARGET_CHANNEL_ID = int(os.environ["TARGET_CHANNEL_ID"])
SESH_ICS_URL = os.environ["SESH_ICS_URL"]

def to_local(dt):
    """Palauta aika Europe/Helsinki -aikana."""
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=tz)
        return dt.astimezone(tz)
    # All-day (pelkkä date) -> klo 00:00 paikallista
    return datetime.combine(dt, dtime(0, 0), tz)

def _get_dt(prop):
    """Hae dt arvo icalendar propertystä. Kestää listat ja puuttuvat tz:t."""
    if prop is None:
        return None
    if isinstance(prop, list) and prop:
        prop = prop[0]
    dt = getattr(prop, "dt", prop)
    return dt

def load_events_between_with_recurring(cal, start, end):
    """Primääri polku: käytä recurring_ical_events -kirjastoa."""
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

def load_events_between_fallback(cal, start, end):
    """Varapolku: käy läpi kaikki VEVENTit ja poimi yksittäiset tapaukset (ilman RRULE-laajennusta)."""
    out = []
    for ev in cal.walk('VEVENT'):
        dtstart_prop = ev.get('dtstart') or ev.get('DTSTART')
        dt = _get_dt(dtstart_prop)
        if dt is None:
            continue
        dt = to_local(dt)
        if not (start <= dt < end):
            continue
        title = str(ev.get('summary', '') or '').strip()
        loc = str(ev.get('location', '') or '').strip()
        if loc:
            title = f"{title} ({loc})"
        out.append((dt, title))
    out.sort(key=lambda x: x[0])
    return out

def load_events_between(url, start, end):
    print(f"[DEBUG] Ladataan ICS: {url}")
    print(f"[DEBUG] Aikaväli: {start} – {end}")
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    cal = Calendar.from_ical(r.content)

    if HAS_RECUR:
        try:
            events = load_events_between_with_recurring(cal, start, end)
            print(f"[DEBUG] recurring_ical_events: löytyi {len(events)} esiintymää")
            return events
        except Exception as e:
            print("[WARN ] recurring_ical_events kaatui, siirrytään fallbackiin.")
            print("       Syy:", repr(e))
            traceback.print_exc()

    events = load_events_between_fallback(cal, start, end)
    print(f"[DEBUG] Fallback VEVENT-luku: löytyi {len(events)} tapahtumaa (ilman RRULE-laajennusta)")
    return events

def format_digest(events):
    if not events:
        return "Tällä viikolla ei näytä olevan kalenterissa tapahtumia. 🚲"
    by_day = {}
    for dt, title in events:
        by_day.setdefault(dt.date(), []).append((dt, title))
    lines = [
        "🗓️ **Ride Club Finland – viikon tapahtumat**",
        ""  # tyhjä rivi
    ]
    for d in sorted(by_day):
        lines.append(f"**{d.strftime('%a %d.%m.')}**")
        for dt, title in sorted(by_day[d], key=lambda x: x[0]):
            lines.append(f" • {dt.strftime('%H:%M')} — {title}")
        lines.append("")  # tyhjä rivi päivän jälkeen
    return "\n".join(lines)

def chunk_by_lines(s: str, limit: int = 1900):
    """Pilkkoo viestin osiin säilyttäen rivinvaihdot (Discordin 2000 merk. raja huomioiden)."""
    parts, buf = [], ""
    for line in s.splitlines(True):  # säilytä \n
        if len(buf) + len(line) > limit:
            parts.append(buf)
            buf = ""
        buf += line
    if buf:
        parts.append(buf)
    return parts

# --- Discord ---
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
        for chunk in chunk_by_lines(digest):
            await ch.send(chunk)
    finally:
        await client.close()

if __name__ == "__main__":
    client.run(os.environ["DISCORD_TOKEN"])
