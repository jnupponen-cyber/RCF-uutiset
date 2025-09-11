#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RCF Weekly Events Digest from Sesh ICS (resilient + links + random intro)
- Hakee Seshin ICS-syötteen (/link)
- Laajentaa toistuvat (recurring_ical_events), fallback yksittäisiin
- Suodattaa kuluvan viikon (ma–su) Europe/Helsinki
- Satunnainen uutis-intro (vaihtuu viikoittain)
- Automaattiset tapahtumalinkit (URL tai kuvauksesta)
- Postaa koosteen Discordiin (rivinvaihdot säilyttäen, linkkikortit estetty)
"""

import os, re, random, traceback
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

# Suomenkieliset viikonpäivälyhenteet (ma–su)
WEEKDAYS_FI = {0: "Ma", 1: "Ti", 2: "Ke", 3: "To", 4: "Pe", 5: "La", 6: "Su"}

# Uutis-introt – botti valitsee yhden viikoittain
INTROS = [
    "☀️ Hyvää huomenta, tässä tämän viikon tärkeimmät tapahtumat.",
    "📦 Paketoituna ja valmiina: RCF-viikko yhdellä listalla.",
    "📢 Uutishuoneesta hyvää huomenta – tässä viikon nostoja.",
    "📻 Juuri saamamme tiedon mukaan viikko näyttää tältä:",
    "🧵 Hyvää huomenta, yhteislenkit ja kisat kootusti.",
    "🧭 Viikko pähkinänkuoressa: tämä kannattaa tietää.",
    "🧭 Mihin mennään ja milloin? Tässä vastaukset.",
    "📰 Ajankohtaista RCF:ssä: viikon kooste.",
    "🔊 Aamun pääuutiset: yhteislenkit ja kisasuunnitelmat."
]

# Domain-kohtaiset linkkitekstit
DOMAIN_LABEL = {
    "zwift.com": "Zwift »",
    "mywhoosh.com": "MyWhoosh »",
    "eventbrite": "Ilmoittaudu »",
    "discord.com": "Discord »",
    "facebook.com": "Facebook »",
    "strava.com": "Strava »",
}

# --- Apurit -----------------------------------------------------------------

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

URL_RE = re.compile(r'https?://[^\s)>\]]+', re.I)
HREF_RE = re.compile(r'href=["\'](https?://[^"\']+)["\']', re.I)

def pick_url_label(url: str) -> str:
    u = url.lower()
    for key, label in DOMAIN_LABEL.items():
        if key in u:
            return label
    return "Liity »"

def extract_url_from_event(ev) -> str | None:
    """Palauta tapahtuman URL:
    1) URL property
    2) HTML/teksti DESCRIPTION (href= tai paljas linkki)
    3) LOCATION
    4) SUMMARY (joskus Sesh upottaa linkin otsikkoon)
    5) fallback: etsi koko eventistä
    """
    def _first_url_from(value: str | None) -> str | None:
        if not value:
            return None
        s = str(value)
        m = HREF_RE.search(s)
        if m:
            return m.group(1)
        m = URL_RE.search(s)
        if m:
            return m.group(0)
        return None

    # 1) URL property (case-insensitive)
    for key in ("url", "URL"):
        if ev.get(key):
            u = str(ev.get(key))
            if u.startswith("http"):
                # print(f"[DEBUG] URL property: {u}")
                return u

    # 2) DESCRIPTION (HTML tai paljas teksti)
    for key in ("description", "DESCRIPTION", "X-ALT-DESC"):  # Sesh saattaa käyttää HTML-alt-kuvausta
        u = _first_url_from(ev.get(key))
        if u:
            # print(f"[DEBUG] URL from DESCRIPTION: {u}")
            return u

    # 3) LOCATION
    for key in ("location", "LOCATION"):
        u = _first_url_from(ev.get(key))
        if u:
            # print(f"[DEBUG] URL from LOCATION: {u}")
            return u

    # 4) SUMMARY (otsikko)
    for key in ("summary", "SUMMARY"):
        u = _first_url_from(ev.get(key))
        if u:
            # print(f"[DEBUG] URL from SUMMARY: {u}")
            return u

    # 5) Fallback: yritä koko eventin stringistä
    try:
        raw = ev.to_ical().decode("utf-8", errors="ignore")
        u = _first_url_from(raw)
        if u:
            # print(f"[DEBUG] URL from raw VEVENT: {u}")
            return u
    except Exception:
        pass

    return None

# --- ICS-luku ---------------------------------------------------------------

def load_events_between_with_recurring(cal, start, end):
    """Primääri polku: käytä recurring_ical_events -kirjastoa."""
    occs = recurring_ical_events.of(cal).between(start, end)
    out = []
    for ev in occs:
        dt = ev.get('dtstart').dt
        dt = to_local(dt)
        title = str(ev.get('summary', '') or '').strip()
        loc = str(ev.get('location', '') or '').strip()
        url = extract_url_from_event(ev)
        if loc:
            title = f"{title} ({loc})"
        out.append((dt, title, url))
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
        url = extract_url_from_event(ev)
        if loc:
            title = f"{title} ({loc})"
        out.append((dt, title, url))
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

# --- Muotoilu ----------------------------------------------------------------

def format_digest(events, now: datetime):
    if not events:
        return "Tällä viikolla ei näytä olevan kalenterissa tapahtumia. 🚲"

    # Valitaan intro deterministisesti viikon numeron mukaan (vaihtuu viikoittain)
    week = now.isocalendar().week
    random.seed(week)
    intro = random.choice(INTROS)

    by_day = {}
    for dt, title, url in events:
        by_day.setdefault(dt.date(), []).append((dt, title, url))

    lines = [
        intro,
        "",
        "🗓️ **Ride Club Finland – viikon tapahtumat**",
        ""
    ]
    for d in sorted(by_day):
        weekday = WEEKDAYS_FI[d.weekday()]
        lines.append(f"**{weekday} {d.strftime('%d.%m.')}**")
        day_items = sorted(by_day[d], key=lambda x: x[0])
        for dt, title, url in day_items:
            if url:
                label = pick_url_label(url)
                # Kulmasulkeet URLin ympärillä + ZWSP + piste -> estää previewt
                lines.append(f" • {dt.strftime('%H:%M')} — {title} [{label}](<{url}>)\u200B.")
            else:
                lines.append(f" • {dt.strftime('%H:%M')} — {title}")
        lines.append("")
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

# --- Discord -----------------------------------------------------------------

intents = discord.Intents.default()
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    try:
        now = datetime.now(tz)
        monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        next_monday = monday + timedelta(days=7)

        events = load_events_between(SESH_ICS_URL, monday, next_monday)
        digest = format_digest(events, now)

        ch = await client.fetch_channel(TARGET_CHANNEL_ID)
        for chunk in chunk_by_lines(digest):
            msg = await ch.send(chunk)
            # Tukahduta mahdolliset linkki-embed-kortit
            try:
                await msg.edit(suppress=True)
            except Exception:
                pass
    finally:
        await client.close()

if __name__ == "__main__":
    client.run(os.environ["DISCORD_TOKEN"])
