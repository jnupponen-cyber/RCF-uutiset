#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RCF Weekly Events Digest from Sesh ICS (resilient + links + random intro + overrides)
- Hakee Seshin ICS-syötteen (/link)
- Laajentaa toistuvat (recurring_ical_events), fallback yksittäisiin
- Suodattaa kuluvan viikon (ma–su) Europe/Helsinki
- Satunnainen uutis-intro (vaihtuu viikoittain)
- Automaattiset tapahtumalinkit (URL tai kuvauksesta)
- Manuaaliset linkkiohitukset (esim. BMX Rumble)
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
    "🎮 Zwift Cheat Code: Ylös, Ylös, Alas, Alas, Vasen, Oikea, Vasen, Oikea, B, A, Start = FTP +200W",
    "📻 Juuri saamamme tiedon mukaan viikko näyttää tältä:",
    "🧵 Hyvää huomenta, yhteislenkit ja kisat kootusti.",
    "💡 Vinkki: Syötä Zwiftin chatissa koodi /piss a party = peloton pysähtyy pakolliselle vessatauolle.",
    "🧭 Viikko pähkinänkuoressa: tämä kannattaa tietää.",
    "💌 Rakkauskirje Arvilta: tässä tapahtumat. XOXO.",
    "🥱 Uusi viikko, uusi pettymys – tässä kuitenkin tapahtumat.",
    "📉 Odotukset matalalla, mutta ehkä tästä jotain löytyy.",
    "🙄 Viikon ohjelma: kyllä, taas näitä samoja juttuja.",
    "🕹️ Zwift-koodi: ↑ ↑ ↓ ↓ ← → ← → X, O, Start = Anti-gravity Tron bike.",
    "💀 Jos et jaksa treenata, niin koita ainakin jaksaa lukea tämä lista.",
    "🙃 Spoileri: mukana on taas lenkkejä ja Zwiftiä, wow mikä yllätys.",
    "🚴‍♂️ Uusi viikko, samat painajaiset.",
    "👑 Tämä lista on tärkeämpi kuin kaikki maanantaipalaverit yhteensä.",
    "🥵 Treenit valmiina, tekosyyt loppuvat tähän.",
    "🔔 Muistutus: kyllä, näitä juttuja on joka viikko.",
    "👻 Boo! Tässä viikko-ohjelma. Säikähditkö? Hyvä.",
    "📢 Viikon lista – luultavasti tärkeämpi kuin työkalenterisi.",
    "🙃 No niin, uusi viikko, samat naamat – tässä viikko-ohjelma.",
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

# --- Manuaaliset linkkiohitukset (title-match) ------------------------------
OVERRIDE_LINKS = [
    (re.compile(r"\bbmx\s*rumble\b", re.I), "https://www.zwift.com/uk/events/view/5108964"),
    # Lisää tänne tarvittaessa muita: (re.compile(r"muu nimi", re.I), "https://…"),
]

def apply_overrides(title: str | None, url: str | None) -> str | None:
    """Jos url puuttuu, täydennä se tunnetuilla ohituksilla nimen perusteella."""
    if url:
        return url
    t = (title or "")
    for pat, link in OVERRIDE_LINKS:
        if pat.search(t):
            return link
    return None

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

def _uid_of(ev) -> str | None:
    try:
        uid = ev.get('uid') or ev.get('UID')
        return str(uid) if uid else None
    except Exception:
        return None

URL_RE  = re.compile(r'https?://[^\s)>\]]+', re.I)
HREF_RE = re.compile(r'href=["\'](https?://[^"\']+)["\']', re.I)

def pick_url_label(url: str) -> str:
    u = url.lower()
    for key, label in DOMAIN_LABEL.items():
        if key in u:
            return label
    return "Liity »"

def extract_url_from_text(value: str | None) -> str | None:
    """Etsi URL tekstistä – sallii myös rivinvaihdolla 'foldatut' linkit."""
    if not value:
        return None
    s = str(value)

    # 1) HTML-href
    m = HREF_RE.search(s)
    if m:
        return m.group(1)

    # 2) Suora URL
    m = URL_RE.search(s)
    if m:
        return m.group(0)

    # 3) URL katkennut rivinvaihtoon (folding) → poista whitespace ja yritä uudestaan
    s_compact = re.sub(r'\s+', '', s)
    m = URL_RE.search(s_compact)
    if m:
        return m.group(0)

    return None

def extract_url_from_event(ev) -> str | None:
    """Palauta tapahtuman URL prioriteetilla:
    1) URL
    2) DESCRIPTION / X-ALT-DESC (myös HTML href)
    3) LOCATION
    4) SUMMARY
    5) fallback: käy läpi KAIKKI kentät (property_items)
    6) viimeinen fallback: koko VEVENTin raakateksti
    """
    # 1) URL property
    for key in ("url", "URL"):
        if ev.get(key):
            u = str(ev.get(key))
            if u.startswith("http"):
                return u

    # 2) DESCRIPTION / X-ALT-DESC
    for key in ("description", "DESCRIPTION", "X-ALT-DESC"):
        u = extract_url_from_text(ev.get(key))
        if u:
            return u

    # 3) LOCATION
    for key in ("location", "LOCATION"):
        u = extract_url_from_text(ev.get(key))
        if u:
            return u

    # 4) SUMMARY
    for key in ("summary", "SUMMARY"):
        u = extract_url_from_text(ev.get(key))
        if u:
            return u

    # 5) Kaikki propertyt (myös custom & parametrilliset)
    try:
        for _, prop_val in ev.property_items():
            u = extract_url_from_text(prop_val)
            if u:
                return u
    except Exception:
        pass

    # 6) Raakateksti
    try:
        raw = ev.to_ical().decode("utf-8", errors="ignore")
        u = extract_url_from_text(raw)
        if u:
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
        url = apply_overrides(title, url)  # manuaaliset ohitukset
        if loc:
            title = f"{title} ({loc})"
        out.append((dt, title, url))
    out.sort(key=lambda x: x[0])
    return out

def load_events_between_fallback(cal, start, end):
    """
    Varapolku: käy läpi kaikki VEVENTit.
    - 1. kierros: rakenna UID->URL -hakemisto kaikista tapahtumista (riippumatta ajanjaksosta)
    - 2. kierros: poimi kuluvan viikon tapaukset ja täydennä URL UID-hakemistosta, jos puuttuu
    """
    # 1) UID -> URL -map kaikista VEVENTeistä
    uid_url: dict[str, str] = {}
    for ev in cal.walk('VEVENT'):
        uid = _uid_of(ev)
        if not uid:
            continue
        u = extract_url_from_event(ev)
        if u and uid not in uid_url:
            uid_url[uid] = u  # ensimmäinen löytynyt kelpaa hyvin

    # 2) Kerää kuluvan viikon tapahtumat ja täydennä URL, jos puuttuu
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

        if not url:
            uid = _uid_of(ev)
            if uid and uid in uid_url:
                url = uid_url[uid]

        # Ohitukset nimen perusteella (esim. BMX Rumble)
        url = apply_overrides(title, url)

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
