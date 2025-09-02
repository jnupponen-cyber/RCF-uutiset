#!/usr/bin/env python3
"""
RCF Discord -uutisbotti (embedit + luokittelu)

- Lukee RSS-lähteet feeds.txt:stä (samasta kansiosta kuin tämä skripti)
- Estää duplikaatit seen.jsonilla
- Postaa Discordiin webhookilla embed-kortteina:
  - otsikko linkkinä
  - lähde
  - lyhyt tiivistelmä
  - värikoodattu tagi
  - pikkukuva, jos saatavilla
"""

import os
import json
import time
import re
import html
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import requests
import feedparser

# --- Perusasetukset ---
SCRIPT_DIR = Path(__file__).resolve().parent
STATE_FILE = SCRIPT_DIR / "seen.json"
FEEDS_FILE = SCRIPT_DIR / "feeds.txt"

WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

MAX_ITEMS_PER_FEED = 10   # montako uusinta merkintää / feed tarkistetaan
POST_DELAY_SEC = 1        # pieni tauko viestien väliin
SUMMARY_MAXLEN = 160      # tiivistelmän pituus

# --- Apufunktiot ---

def load_seen(path: Path = STATE_FILE) -> set:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return set(data)
            if isinstance(data, dict) and "ids" in data:
                return set(data["ids"])
        except Exception:
            pass
    return set()

def save_seen(seen: set, path: Path = STATE_FILE) -> None:
    try:
        path.write_text(json.dumps(sorted(list(seen)), ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[WARN] save_seen failed: {e}")

def read_feeds(path: Path = FEEDS_FILE) -> list:
    feeds = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            url = line.strip()
            if url and not url.startswith("#"):
                feeds.append(url)
    return feeds

def uid_from_entry(entry) -> str:
    base = entry.get("id") or entry.get("link") or entry.get("title", "")
    return hashlib.sha256(base.encode("utf-8")).hexdigest()

def clean_summary(s: str | None, maxlen: int = SUMMARY_MAXLEN) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", s)            # poista HTML-tagit
    s = html.unescape(s).strip()
    s = re.sub(r"\s+", " ", s)
    if len(s) > maxlen:
        s = s[: maxlen - 1].rstrip() + "…"
    return s

def image_from_entry(entry) -> str | None:
    # Yritä media_thumbnail / media_content
    for key in ("media_thumbnail", "media_content"):
        if key in entry and entry[key]:
            try:
                url = entry[key][0].get("url")
                if url:
                    return url
            except Exception:
                pass
    # Fallback: etsi <img src="..."> summarystä
    html_part = entry.get("summary") or ""
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html_part, flags=re.I)
    return m.group(1) if m else None

def classify(title: str) -> tuple[str, int]:
    """Palauta (tagi, väri) Discordin embedille."""
    t = (title or "").lower()
    if any(k in t for k in ["update", "release", "patch", "notes", "päivitys"]):
        return ("#päivitys", int("0x00A3FF", 16))   # sininen
    if any(k in t for k in ["race", "zracing", "zrl", "cup", "series", "kisa"]):
        return ("#kisa", int("0xFF6B00", 16))       # oranssi
    if any(k in t for k in ["route", "climb", "portal", "course", "reitti"]):
        return ("#reitti", int("0x66BB6A", 16))     # vihreä
    if any(k in t for k in ["bike", "wheel", "frame", "hardware", "equipment"]):
        return ("#kalusto", int("0x9C27B0", 16))    # violetti
    return ("#uutinen", int("0x5865F2", 16))        # Discordin “blurple”

def post_to_discord(title: str, url: str, source: str, summary: str | None, image_url: str | None) -> None:
    if not WEBHOOK:
        raise RuntimeError("DISCORD_WEBHOOK_URL ei ole asetettu ympäristömuuttujaksi.")
    tag, color = classify(title)

    embed = {
        "type": "rich",
        "title": title,
        "url": url,
        "description": summary or "",
        "color": color,
        "author": {"name": source},
        "footer": {"text": f"{tag} · RCF-uutiset"},
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    # Pidetään viesti matalana → käytä thumbnailia ison kuvan sijaan
    if image_url:
        embed["thumbnail"] = {"url": image_url}

    payload = {"embeds": [embed]}
    resp = requests.post(WEBHOOK, json=payload, timeout=20)
    if resp.status_code >= 300:
        raise RuntimeError(f"Discord POST failed: {resp.status_code} {resp.text}")

# --- Päätoiminto ---

def main() -> None:
    feeds = read_feeds()
    if not feeds:
        print("[ERROR] feeds.txt on tyhjä tai puuttuu. Lisää RSS-osoitteet.")
        return

    seen = load_seen()
    all_new = []

    for feed_url in feeds:
        parsed = feedparser.parse(feed_url)
        source = parsed.feed.get("title", feed_url)
        entries = parsed.entries[:MAX_ITEMS_PER_FEED]
        for e in entries:
            u = uid_from_entry(e)
            if u in seen:
                continue
            title = e.get("title") or "Uusi artikkeli"
            link = e.get("link") or feed_url
            summary = clean_summary(e.get("summary"))
            img = image_from_entry(e)
            all_new.append((u, title, link, source, summary, img))

    # Postataan kronologisesti (vanhin ensin), jotta “livenä” järjestys on luonnollinen
    all_new.reverse()
    print(f"[INFO] Uusia julkaisuja: {len(all_new)}")

    for u, title, link, source, summary, img in all_new:
        try:
            post_to_discord(title, link, source, summary, img)
            seen.add(u)
            time.sleep(POST_DELAY_SEC)
        except Exception as e:
            print(f"[WARN] Postaus epäonnistui: {e}")

    save_seen(seen)

if __name__ == "__main__":
    main()
