#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RCF – Päivän Zwift-tapahtumat (otsikko alkaa 'Ride Club Finland' / 'RIDE CLUB FINLAND')

Mitä tekee:
- Klo 07:00 (Europe/Helsinki) ajettuna hakee julkisilta sivuilta (zwiftracing.app, zwifthacks.com) päivän tapahtumat
- Suodattaa vain ne, joiden TITLE alkaa 'Ride Club Finland' tai 'RIDE CLUB FINLAND'
- Muodostaa siistin Discord-embedin SUORILLA tapahtumalinkeillä
- Näyttää lähtöajan, reitin nimen ja matkan (km), jos saatavilla
- Lisää alkuun virallistyylisen juontolainan (satunnainen)

Huom: Toteutus on "best effort": sivujen HTML voi muuttua. Skripti antaa selkeää lokia, jos lähteet muuttuvat.
"""

import os
import re
import random
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Tuple

import requests
from bs4 import BeautifulSoup
from dateutil import tz, parser as dateparser

# ---------- ASETUKSET ----------
TZ = tz.gettz("Europe/Helsinki")
REQUEST_TIMEOUT = 15
USER_AGENT = {"User-Agent": "RCF Events Bot (Ride Club Finland)"}

# Discord
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL_EVENTS", "").strip() or os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

# Juonto-lainat (virallinen sävy)
QUIPS = [
    "Uutisista hyvää huomenta – tässä Ride Club Finlandin tämän päivän tapahtumat.",
    "Ja seuraavaksi urheilua: Ride Club Finlandin tämän päivän tapahtumat.",
    "Hyvää huomenta. Tässä päivän RCF-tapahtumat koottuna.",
    "RCF:n ajankohtaiset tapahtumat tälle päivälle.",
]

# Hyväksytyt otsikon alut (case-insensitive)
RCF_PREFIXES = ("ride club finland",)

# Kuinka monta tapahtumaa rikastetaan avaamalla niiden yksittäissivu (reitti/matka)
ENRICH_LIMIT = int(os.environ.get("RCF_ENRICH_LIMIT", "12"))

# ---------- Apu: suodatukset & muotoilut ----------

def title_is_rcf(title: str) -> bool:
    if not title:
        return False
    t = title.strip().lower()
    return any(t.startswith(pref) for pref in RCF_PREFIXES)

def is_today(dt: datetime) -> bool:
    if not dt:
        return False
    local = dt.astimezone(TZ)
    today_local = datetime.now(TZ).date()
    return local.date() == today_local

def clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def parse_dt_maybe(s: str) -> Optional[datetime]:
    try:
        dt = dateparser.parse(s)
        if dt is None:
            return None
        # jos ei timezonea, tulkitaan Helsingin ajaksi
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt
    except Exception:
        return None

def fmt_time(dt: datetime) -> str:
    local = dt.astimezone(TZ)
    return local.strftime("%H:%M")

def miles_to_km(mi: float) -> float:
    return mi * 1.60934

ROUTE_PATTERNS = [
    r"\broute\s*[:\-]\s*([A-Za-z0-9'’\-\s&]+)",
    r"\bcourse\s*[:\-]\s*([A-Za-z0-9'’\-\s&]+)",
    r"\bmap\s*[:\-]\s*([A-Za-z0-9'’\-\s&]+)",
    r"\bworld\s*[:\-]\s*([A-Za-z0-9'’\-\s&]+)",
]

DIST_PATTERNS = [
    r"\bdistance\s*[:\-]\s*(\d+(?:\.\d+)?)\s*(km|kilometers?)\b",
    r"\bdistance\s*[:\-]\s*(\d+(?:\.\d+)?)\s*(mi|miles?)\b",
    r"\b(\d+(?:\.\d+)?)\s*(km|kilometers?)\b",
    r"\b(\d+(?:\.\d+)?)\s*(mi|miles?)\b",
    r"\b(\d+(?:\.\d+)?)\s*(km)\s*(?:total)?\b",
]

def extract_route_distance(text: str) -> Tuple[Optional[str], Optional[float]]:
    """
    Best-effort haku reitti- ja matkatiedoille vapaasta tekstistä.
    Palauttaa (route_name, distance_km).
    """
    t = clean_text(text).lower()

    # Reitti
    route = None
    for pat in ROUTE_PATTERNS:
        m = re.search(pat, t, flags=re.I)
        if m:
            route_raw = m.group(1).strip()
            # palauta alkuperäisestä tekstistä vastaava osuus säilyttäen isot kirjaimet
            # etsitään route_raw case-insensitive alkuperäisestä:
            m2 = re.search(re.escape(route_raw), text, flags=re.I)
            route = m2.group(0).strip() if m2 else route_raw.title()
            break

    # Matka
    km = None
    for pat in DIST_PATTERNS:
        m = re.search(pat, t, flags=re.I)
        if not m:
            continue
        val = float(m.group(1))
        unit = m.group(2).lower() if len(m.groups()) >= 2 else "km"
        if unit.startswith("mi"):
            km = miles_to_km(val)
        else:
            km = val
        break

    return route, km

def fetch_html(url: str) -> Optional[str]:
    try:
        r = requests.get(url, headers=USER_AGENT, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"[WARN] GET failed {url}: {e}")
        return None

def enrich_event(ev: dict) -> dict:
    """
    Yrittää täydentää reitin ja matkan avaamalla tapahtuman yksittäissivun.
    """
    if ev.get("route") and ev.get("distance_km") is not None:
        return ev

    html = fetch_html(ev["url"])
    if not html:
        return ev

    soup = BeautifulSoup(html, "lxml")
    page_text = clean_text(soup.get_text(" "))

    # Kokeile ensin label-tyyppisiä kenttiä DOMista
    candidates = [page_text]

    # Etsi mahdollisia pieniä kenttälistoja
    for sel in ["table", ".event-details", ".details", ".info", "ul", "dl"]:
        for node in soup.select(sel):
            candidates.append(clean_text(node.get_text(" ")))

    route = ev.get("route")
    km = ev.get("distance_km")

    for blob in candidates:
        r, d = extract_route_distance(blob)
        if r and not route:
            route = r
        if (d is not None) and (km is None):
            km = d
        if route and (km is not None):
            break

    if route:
        ev["route"] = route
    if km is not None:
        ev["distance_km"] = round(km, 1)

    return ev

# ---------- Lähde 1: zwiftracing.app/events (hakusana) ----------

def fetch_from_zwiftracing() -> list[dict]:
    url = "https://www.zwiftracing.app/events?query=Ride%20Club%20Finland"
    html = fetch_html(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    events = []

    for a in soup.select("a"):
        text = clean_text(a.get_text())
        href = a.get("href", "")
        if not href or not text:
            continue
        if "/events/" in href and title_is_rcf(text):
            # kellonaika kortista (heuristiikka)
            time_text = None
            parent = a.find_parent()
            if parent:
                txt = clean_text(parent.get_text())
                m = re.search(r"\b([01]?\d|2[0-3]):[0-5]\d\b", txt)
                if m:
                    time_text = m.group(0)

            dt = None
            if time_text:
                guess = f"{date.today().isoformat()} {time_text}"
                dt = parse_dt_maybe(guess)

            link = href if href.startswith("http") else f"https://www.zwiftracing.app{href}"

            # Reitti & matka kortin tekstistä
            route, km = extract_route_distance(parent.get_text(" ") if parent else text)

            events.append({
                "source": "ZwiftRacing",
                "title": text,
                "when": dt,
                "url": link,
                "route": route,
                "distance_km": round(km, 1) if km is not None else None
            })

    return events

# ---------- Lähde 2: zwifthacks.com (hakusuodatus sivulla) ----------

def fetch_from_zwifthacks() -> list[dict]:
    url = "https://zwifthacks.com/app/events/?search=Ride%20Club%20Finland"
    html = fetch_html(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    events = []

    for a in soup.select("a"):
        text = clean_text(a.get_text())
        href = a.get("href", "")
        if not href or not text:
            continue

        if title_is_rcf(text) and ("event" in href or "zwift.com" in href):
            time_text = None
            parent = a.find_parent()
            if parent:
                txt = clean_text(parent.get_text())
                m = re.search(r"\b([01]?\d|2[0-3]):[0-5]\d\b", txt)
                if m:
                    time_text = m.group(0)

            dt = None
            if time_text:
                guess = f"{date.today().isoformat()} {time_text}"
                dt = parse_dt_maybe(guess)

            link = href if href.startswith("http") else f"https://zwifthacks.com{href}"

            # Reitti & matka kortin tekstistä
            route, km = extract_route_distance(parent.get_text(" ") if parent else text)

            events.append({
                "source": "ZwiftHacks",
                "title": text,
                "when": dt,
                "url": link,
                "route": route,
                "distance_km": round(km, 1) if km is not None else None
            })

    return events

# ---------- Discord-postaus ----------

def post_embed(events: list[dict]) -> None:
    if not DISCORD_WEBHOOK:
        print("[ERROR] DISCORD_WEBHOOK_URL_EVENTS (tai DISCORD_WEBHOOK_URL) puuttuu.")
        return
    if not events:
        print("[INFO] Ei julkaistavaa (ei tämän päivän RCF-eventtejä).")
        return

    # Lajitellaan kellonajan mukaan; ne joilla ei ole aikaa -> loppuun
    def keyfn(e):
        return (e["when"] or datetime(2100,1,1,tzinfo=TZ))
    events_sorted = sorted(events, key=keyfn)

    fields = []
    for ev in events_sorted:
        title = ev["title"]
        url = ev["url"]
        when = ev["when"]
        clock = fmt_time(when) if when else "—"

        parts = []
        if ev.get("route"):
            parts.append(f"Reitti: {ev['route']}")
        if ev.get("distance_km") is not None:
            parts.append(f"Matka: {ev['distance_km']:.1f} km")
        meta_line = " • ".join(parts) if parts else "Lisätiedot tapahtumasivulla."

        fields.append({
            "name": f"{clock} — {title}",
            "value": f"{meta_line}\n[Avaa tapahtuma]({url})",
            "inline": False
        })

    # Virallinen juonto
    content = f"_{random.choice(QUIPS)}_"

    embed = {
        "type": "rich",
        "title": "Ride Club Finland – tämän päivän tapahtumat",
        "description": "Alla tämän päivän RCF-tapahtumat suorilla linkeillä. Tervetuloa mukaan!",
        "color": int("0x5865F2", 16),
        "fields": fields,
        "footer": {"text": "Lähteet: ZwiftRacing · ZwiftHacks"},
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }

    payload = {"content": content, "embeds": [embed]}
    resp = requests.post(DISCORD_WEBHOOK, json=payload, timeout=REQUEST_TIMEOUT)
    if resp.status_code >= 300:
        print(f"[WARN] Discord POST failed: {resp.status_code} {resp.text[:200]}")
    else:
        print(f"[INFO] Lähetetty {len(events_sorted)} tapahtumaa.")

# ---------- Pää ----------

def main():
    # Hae molemmista lähteistä
    ev1 = fetch_from_zwiftracing()
    ev2 = fetch_from_zwifthacks()
    all_events = ev1 + ev2

    # Suodata vain tapahtumat, joilla on aika ja jotka tapahtuvat TÄNÄÄN
    todays = [e for e in all_events if e.get("when") and is_today(e["when"])]

    # Poista duplikaatit urlin perusteella
    uniq = {}
    for e in todays:
        uniq[e["url"]] = e
    events = list(uniq.values())

    # Rikasta reitti + matka avaamalla yksittäissivu (raja ENRICH_LIMIT)
    for i, ev in enumerate(events):
        if (not ev.get("route")) or (ev.get("distance_km") is None):
            if i < ENRICH_LIMIT:
                enrich_event(ev)

    # Lopullinen suodatus: jos ei löydy kellonaikaa, tiputetaan pois (lähtöaika oleellinen)
    events = [e for e in events if e.get("when")]

    post_embed(events)

if __name__ == "__main__":
    main()
