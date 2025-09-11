#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RCF Weekly Events Digest from Sesh ICS (resilient + random intro, no per-event links)
- Hakee Seshin ICS-syötteen (/link)
- Laajentaa toistuvat (recurring_ical_events), fallback yksittäisiin
- Suodattaa kuluvan viikon (ma–su) Europe/Helsinki
- Satunnainen uutis-intro (vaihtuu viikoittain)
- Ei per-tapahtuma-linkkejä; loppuun Zwift Club -linkki
- Postaa Discordiin (rivinvaihdot säilyttäen, linkkikortit estetty)
"""

import os, random, traceback
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

# Uutis-introt – botti valitsee yhden viikoittain (oma listasi säilytetty)
INTROS = [
    "☀️ Hyvää huomenta, tässä tämän viikon tärkeimmät tapahtumat.",
    "📦 Paketoituna ja valmiina: RCF-viikko yhdellä listalla.",
    "📢 Uutishuoneesta hyvää huomenta – tässä viikon nostoja.",
    "🎮 Zwift Cheat Code: Ylös, Ylös, Alas, Alas, Vasen, Oikea, Vasen, Oikea, B, A, Start = FTP +200W",
    "📻 Juuri saamamme tiedon mukaan viikko näyttää tältä:",
    "🧵 Hyvää huomenta, yhteislenkit ja kisat kootusti.",
    "💡 Vinkki: Syötä Zwiftin chatissa koodi /piss a party = peloton pysähtyy pakolliselle vessatauolle.",
    "🧭 Viikko pähkinänkuoressa: tämä kannattaa tietää.",
    "💌 Rakkauskirje Arvilta: tässä tapahtumat. XOXO.",
    "🥱 Uusi viikko, uusia pettymyksiä – tässä kuitenkin tapahtumat.",
    "📉 Odotukset matalalla, mutta ehkä tästä jotain löytyy.",
    "🙄 Viikon ohjelma: kyllä, taas näitä samoja juttuja.",
    "🕹️ Zwift-koodi: ↑ ↑ ↓ ↓ ← → ← → X, O, Start = Anti-gravity Tron bike.",
    "💀 Jos et jaksa treenata, niin koita ainakin jaksaa lukea tämä lista.",
    "🙃 Spoileri: mukana on taas yhteislenkkejä ja kisoja, wow mikä yllätys.",
    "🚴‍♂️ Uusi viikko, samat painajaiset.",
    "💡 Pro Tip: Jos ei jaksa… niin koittakaa vaan jaksaa. – Niilo 22, RCF edition.",
    "👑 Tämä lista on tärkeämpi kuin kaikki maanantaipalaverit yhteensä.",
    "🥵 Treenit valmiina, tekosyyt loppuvat tähän.",
    "🔔 Muistutus: kyllä, näitä juttuja on joka viikko.",
    "👻 Boo! Tässä viikko-ohjelma. Säikähditkö? Hyvä.",
    "📢 Viikon lista – luultavasti tärkeämpi kuin työkalenterisi.",
    "🙃 No niin, uusi viikko, samat naamat – tässä viikko-ohjelma.",
    "📰 Ajankohtaista RCF:ssä: viikon kooste."
]

# Pysyvä klubilinkki (footeriin). Kulmasulkeet + ZWSP + piste estävät korttiesikatselun.
ZWIFT_CLUB_URL = "https://www.zwift.com/clubs/3a01d4d1-3ca7-4ef6-8c93-9ec1b7ea783c/home"

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

# --- Muotoilu ----------------------------------------------------------------

def format_digest(events, now: datetime):
    # Footer: klubilinkki (kulmasulkeet + ZWSP + piste -> ei korttia)
    footer = f"🔗 Kaikki RCF:n Zwift-ajot löytyvät klubista: [Zwift Club](<{ZWIFT_CLUB_URL}>)\u200B."

    if not events:
        return "Tällä viikolla ei näytä olevan kalenterissa tapahtumia. 🚲\n\n" + footer

    # Valitaan intro deterministisesti viikon numeron mukaan (vaihtuu viikoittain)
    week = now.isocalendar().week
    random.seed(week)
    intro = random.choice(INTROS)

    by_day = {}
    for dt, title in events:
        by_day.setdefault(dt.date(), []).append((dt, title))

    lines = [
        intro,
        "",
        "🗓️ **Ride Club Finland – viikon tapahtumat**",
        ""
    ]
    for d in sorted(by_day):
        weekday = WEEKDAYS_FI[d.weekday()]
        lines.append(f"**{weekday} {d.strftime('%d.%m.')}**")
        for dt, title in sorted(by_day[d], key=lambda x: x[0]):
            lines.append(f" • {dt.strftime('%H:%M')} — {title}")
        lines.append("")

    lines.append(footer)
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
            # Tukahduta mahdolliset linkki-embed-kortit (footer-linkki)
            try:
                await msg.edit(suppress=True)
            except Exception:
                pass
    finally:
        await client.close()

if __name__ == "__main__":
    client.run(os.environ["DISCORD_TOKEN"])
