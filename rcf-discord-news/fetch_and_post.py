#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RCF Discord -uutisbotti (embedit + OG-kuvat + esto-lista + ping + per-lähde värit + suodatusraportti)

- Lukee RSS-lähteet FEEDS_FILE-ympäristömuuttujasta tai oletuksena feeds.txt (samassa kansiossa)
- Estää duplikaatit seen.jsonilla
- Hakee kuvan ja kuvauksen myös sivun OG-tageista (og:image, og:description)
- Suodattaa artikkelit blocklist.txt:n (esto-lista) perusteella
- Postaa Discordiin webhookilla:
  - otsikko linkkinä
  - lähde + favicon
  - napakka kuvaus
  - iso kuva (tai thumbnail)
  - linkkipainike
  - pingi: käyttäjä tai rooli, jos MENTION_* -ympäristömuuttuja asetettu
  - per-lähde värikoodit (SOURCE_COLORS)
  - lokiin yhteenveto skippauksista (Shorts / globaali / lähdekohtainen)

Käyttövinkit:
- DEBUG=1 näyttää ajolokit (luetut feedit, entries-määrät, SKIP/POST-syyt).
- FEEDS_FILE=polku.txt vaihtaa syötetiedoston (esim. temp-ajoon).
"""

import os
import json
import time
import re
import html
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
import feedparser


# --- Perusasetukset ---
SCRIPT_DIR = Path(__file__).resolve().parent
STATE_FILE = SCRIPT_DIR / "seen.json"
FEEDS_FILE = Path(os.environ.get("FEEDS_FILE", SCRIPT_DIR / "feeds.txt")).resolve()
BLOCKLIST_FILE = SCRIPT_DIR / "blocklist.txt"

# Estä YouTube Shorts -URLit kovasäännöllä (oletus: päällä)
BLOCK_YT_SHORTS = int(os.environ.get("BLOCK_YT_SHORTS", "1")) == 1

WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

# Ping-asetukset: määritä jompikumpi GitHub-sekreteihin
MENTION_USER_ID = os.environ.get("MENTION_USER_ID", "").strip()   # esim. 123456789012345678
MENTION_ROLE_ID = os.environ.get("MENTION_ROLE_ID", "").strip()   # roolin ID

# Ajotapa
MAX_ITEMS_PER_FEED = 10
POST_DELAY_SEC = 1
SUMMARY_MAXLEN = 200
REQUEST_TIMEOUT = 12
PREFER_LARGE_IMAGE = int(os.environ.get("PREFER_LARGE_IMAGE", "1")) == 1

# DEBUG-moodi
DEBUG = int(os.environ.get("DEBUG", "0")) == 1
def logd(*args):
    if DEBUG:
        print("[DEBUG]", *args)

# --- Per-lähde värikoodit (voit laajentaa listaa vapaasti) ---
SOURCE_COLORS = {
    "Zwift Insider": int("0xFF6B00", 16),        # oranssi (Zwift)
    "Zwift.com News": int("0xFF6B00", 16),       # oranssi (Zwift)
    "MyWhoosh": int("0x2196F3", 16),             # sininen
    "DC Rainmaker": int("0x9C27B0", 16),         # violetti
    "GPLama": int("0x00BCD4", 16),               # turkoosi
    "GCN": int("0xE91E63", 16),                  # pinkki
    "GCN Tech": int("0x3F51B5", 16),             # sinivioletti
    "ZRace Central": int("0x4CAF50", 16),        # vihreä
    "Smart Bike Trainers": int("0x795548", 16),  # ruskea
    "Dylan Johnson Cycling": int("0x009688", 16),# teal
    "TrainerRoad": int("0xF44336", 16),          # punainen
    "Everything’s Been Done": int("0x607D8B", 16), # harmaa/sinertävä
    "Cycling Weekly": int("0x8BC34A", 16),       # kirkas vihreä
    "BikeRadar": int("0x1E88E5", 16),            # sininen (BikeRadar)
    "Velo": int("0x00F7FF", 16)                  # kirkas turkoosi (Velo)
}

# --- Regex OG-metaan ---
OG_IMG_RE  = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', re.I)
TW_IMG_RE  = re.compile(r'<meta[^>]+name=["\']twitter:image["\'][^>]*content=["\']([^"\']+)["\']', re.I)
OG_DESC_RE = re.compile(r'<meta[^>]+property=["\']og:description["\'][^>]*content=["\']([^"\']+)["\']', re.I)
TW_DESC_RE = re.compile(r'<meta[^>]+name=["\']twitter:description["\'][^>]*content=["\']([^"\']+)["\']', re.I)


# -------------------------
#        Apufunktiot
# -------------------------

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
            # sallitaan tyhjät ja kommenttirivit
            if url and not url.startswith("#"):
                feeds.append(url)
    else:
        print(f"[WARN] feeds file not found: {path}")
    return feeds

def uid_from_entry(entry) -> str:
    base = entry.get("id") or entry.get("link") or entry.get("title", "")
    return hashlib.sha256(base.encode("utf-8")).hexdigest()

def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", s)      # strip HTML
    s = html.unescape(s).strip()
    s = re.sub(r"\s+", " ", s)
    return s

def truncate(s: str, maxlen: int) -> str:
    if len(s) <= maxlen:
        return s
    return s[:maxlen-1].rstrip() + "…"

def domain_favicon(url: str) -> str | None:
    try:
        host = urlparse(url).netloc
        if not host:
            return None
        # Google s2 favicon -palvelu
        return f"https://www.google.com/s2/favicons?sz=64&domain={host}"
    except Exception:
        return None

def image_from_entry(entry) -> str | None:
    for key in ("media_thumbnail", "media_content"):
        if key in entry and entry[key]:
            try:
                url = entry[key][0].get("url")
                if url:
                    return url
            except Exception:
                pass
    # Fallback: <img src> summarystä
    html_part = entry.get("summary") or ""
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html_part, flags=re.I)
    return m.group(1) if m else None

def fetch_og_meta(url: str) -> tuple[str | None, str | None]:
    """Palauttaa (og_image, og_description) jos löytyy."""
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent":"Mozilla/5.0 (RCF News Bot)"})
        if r.status_code >= 400 or not r.text:
            return None, None
        html_txt = r.text
        img = None
        desc = None
        for rx in (OG_IMG_RE, TW_IMG_RE):
            m = rx.search(html_txt)
            if m:
                img = m.group(1).strip()
                break
        for rx in (OG_DESC_RE, TW_DESC_RE):
            m = rx.search(html_txt)
            if m:
                desc = clean_text(m.group(1))
                break
        return img, desc
    except Exception:
        return None, None

def classify(title: str) -> tuple[str, int]:
    t = (title or "").lower()
    if any(k in t for k in ["update", "release", "patch", "notes", "päivitys"]):
        return ("#päivitys", int("0x00A3FF", 16))   # sininen
    if any(k in t for k in ["race", "zracing", "zrl", "cup", "series", "kisa"]):
        return ("#kisa", int("0xFF6B00", 16))       # oranssi
    if any(k in t for k in ["route", "climb", "portal", "course", "reitti"]):
        return ("#reitti", int("0x66BB6A", 16))     # vihreä
    if any(k in t for k in ["bike", "wheel", "frame", "hardware", "equipment"]):
        return ("#kalusto", int("0x9C27B0", 16))    # violetti
    return ("#uutinen", int("0x5865F2", 16))        # blurple

# -------- Esto-lista (blocklist) --------

def load_blocklist(path: Path = BLOCKLIST_FILE):
    """
    Palauttaa:
      - global_terms: [ "smartwatch", "älykello", ... ]
      - source_terms: [ ("dc rainmaker", "watch"), ... ]  # molemmat lowercasena
    Syntaksi:
      # kommentti
      smartwatch
      älykello
      source=DC Rainmaker|watch
    """
    global_terms, source_terms = [], []
    if not path.exists():
        return global_terms, source_terms
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("source=") and "|" in line:
            left, term = line.split("|", 1)
            src = left.split("=", 1)[1].strip().lower()
            source_terms.append((src, term.strip().lower()))
        else:
            global_terms.append(line.lower())
    return global_terms, source_terms

def should_skip_article(source_name: str,
                        title: str,
                        summary: str,
                        link: str,
                        global_terms,
                        source_terms) -> tuple[bool, str | None]:
    """
    Palauttaa (skip, reason) jos artikkeli pitää ohittaa.
    - Hakee termejä otsikosta, kuvauksesta JA linkistä
    - Erikoissääntö: blokkaa YouTube Shorts -URLit (youtube.com/shorts/...), jos BLOCK_YT_SHORTS=1
    reason-arvot: 'shorts' | 'global:<termi>' | 'source:<src>|<termi>' | None
    """
    text = f"{title} {summary}".lower()
    link_l = (link or "").lower()
    src_lower = (source_name or "").lower()

    # 1) Kovasääntö: blokkaa YouTube Shorts -URLit
    if BLOCK_YT_SHORTS and ("youtube.com/shorts/" in link_l):
        return True, "shorts"

    # 2) Globaalit termit: täsmäävät jos osuvat joko tekstiin TAI linkkiin
    for t in global_terms:
        t_norm = t.strip().lower()
        if not t_norm:
            continue
        if t_norm in text or t_norm in link_l:
            return True, f"global:{t_norm}"

    # 3) Lähdekohtaiset termit (source=...|...)
    for src, t in source_terms:
        if src in src_lower and (t in text or t in link_l):
            return True, f"source:{src}|{t}"

    return False, None

# -------- Discord-postaus --------

def post_to_discord(title: str, url: str, source: str, summary: str | None, image_url: str | None) -> None:
    if not WEBHOOK:
        raise RuntimeError("DISCORD_WEBHOOK_URL ei ole asetettu ympäristömuuttujaksi.")

    # --- Per-lähde väri, tai fallback classify() ---
    if source in SOURCE_COLORS:
        color = SOURCE_COLORS[source]
        footer_text = f"{source} · RCF-uutiset"
    else:
        tag, color = classify(title)
        footer_text = f"{tag} · RCF-uutiset"

    # Linkkinappi
    components = [{
        "type": 1,  # ACTION_ROW
        "components": [{
            "type": 2,  # BUTTON
            "style": 5, # LINK
            "label": "Avaa artikkeli",
            "url": url
        }]
    }]

    author = {"name": source}
    fav = domain_favicon(url)
    if fav:
        author["icon_url"] = fav

    embed = {
        "type": "rich",
        "title": title,
        "url": url,
        "description": truncate(summary or "", SUMMARY_MAXLEN),
        "color": color,
        "author": author,
        "footer": {"text": footer_text},
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    if image_url:
        if PREFER_LARGE_IMAGE:
            embed["image"] = {"url": image_url}
        else:
            embed["thumbnail"] = {"url": image_url}

# -------- Pääsilmukka --------

def source_name_from_feed(parsed, fallback_url: str) -> str:
    try:
        name = parsed.feed.get("title")
        if name:
            return clean_text(name)
    except Exception:
        pass
    return urlparse(fallback_url).netloc

def process_feed(url: str, seen: set, global_terms, source_terms) -> dict:
    """Palauttaa tilaston: {'total': N, 'posted': M, 'skipped': K}"""
    stats = {"total": 0, "posted": 0, "skipped": 0}
    d = feedparser.parse(url, request_headers={"User-Agent": "RCF News Bot"})
    if getattr(d, "bozo", 0) and not getattr(d, "entries", None):
        logd("FEED ERROR:", url, "| bozo:", getattr(d, "bozo", 0), "| error:", getattr(d, "bozo_exception", None))
        return stats

    source_name = source_name_from_feed(d, url)
    entries = list(d.entries or [])
    stats["total"] = len(entries)
    logd("feed parsed:", source_name, "| entries:", len(entries))

    # Uusimmat ensin jos mahdollista
    try:
        entries.sort(key=lambda e: e.get("published_parsed") or e.get("updated_parsed") or 0, reverse=True)
    except Exception:
        pass

    for entry in entries[:MAX_ITEMS_PER_FEED]:
        uid = uid_from_entry(entry)
        title = clean_text(entry.get("title"))
        link = entry.get("link") or ""
        summary_html = entry.get("summary") or ""
        summary = clean_text(summary_html)

        # Skip jos olemme jo nähneet
        if uid in seen:
            stats["skipped"] += 1
            logd("SKIP(seen):", source_name, "|", title)
            continue

        # Blocklist / shorts
        skip, reason = should_skip_article(source_name, title, summary, link, global_terms, source_terms)
        if skip:
            stats["skipped"] += 1
            logd("SKIP:", source_name, "| reason:", reason, "|", title)
            continue

        # Kuva: entry -> OG fallback
        img = image_from_entry(entry)
        if not img:
            og_img, og_desc = fetch_og_meta(link)
            if og_img:
                img = og_img
            if og_desc and not summary:
                summary = og_desc

        # Postaa
        try:
            logd("POST:", source_name, "|", title, "|", link)
            post_to_discord(title=title, url=link, source=source_name, summary=summary, image_url=img)
            stats["posted"] += 1
            seen.add(uid)
            time.sleep(POST_DELAY_SEC)
        except Exception as e:
            print(f"[WARN] Discord post failed for {link}: {e}")

    return stats

def main():
    # Lataa tila ja asetukset
    seen = load_seen()
    global_terms, source_terms = load_blocklist()
    feeds = read_feeds()

    logd("FEEDS_FILE ->", str(FEEDS_FILE))
    for f in feeds:
        logd("  feed:", f)
    logd("blocklist global terms:", len(global_terms), "source terms:", len(source_terms))

    total_posted = 0
    total_skipped = 0
    total_entries = 0

    for url in feeds:
        stats = process_feed(url, seen, global_terms, source_terms)
        total_posted += stats["posted"]
        total_skipped += stats["skipped"]
        total_entries += stats["total"]

    save_seen(seen)
    logd("run complete at", datetime.now(timezone.utc).isoformat(), "UTC",
         "| feeds:", len(feeds),
         "| entries:", total_entries,
         "| posted:", total_posted,
         "| skipped:", total_skipped)

if __name__ == "__main__":
    main()
