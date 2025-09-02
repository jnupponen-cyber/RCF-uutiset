#!/usr/bin/env python3
"""
RCF Discord -uutisbotti (embedit + OG-kuvat + esto-lista)

- Lukee RSS-lähteet feeds.txt:stä (samasta kansiosta)
- Estää duplikaatit seen.jsonilla
- Hakee kuvan ja kuvauksen myös sivun OG-tageista (og:image, og:description)
- Suodattaa artikkelit blocklist.txt:n (esto-lista) perusteella
- Postaa Discordiin webhookilla:
  - otsikko linkkinä
  - lähde + favicon
  - napakka kuvaus
  - iso kuva (tai thumbnail)
  - linkkipainike
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
FEEDS_FILE = SCRIPT_DIR / "feeds.txt"
BLOCKLIST_FILE = SCRIPT_DIR / "blocklist.txt"

WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

MAX_ITEMS_PER_FEED = 10
POST_DELAY_SEC = 1
SUMMARY_MAXLEN = 200
REQUEST_TIMEOUT = 12
# Aseta 0, jos haluat mieluummin pienen kuvan kortin sivuun
PREFER_LARGE_IMAGE = int(os.environ.get("PREFER_LARGE_IMAGE", "1")) == 1

# --- Regex OG-metaan ---
OG_IMG_RE = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', re.I)
TW_IMG_RE = re.compile(r'<meta[^>]+name=["\']twitter:image["\'][^>]*content=["\']([^"\']+)["\']', re.I)
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
            if url and not url.startswith("#"):
                feeds.append(url)
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
        # Google s2 favicon -palustus
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

def should_skip_article(source_name: str, title: str, summary: str,
                        global_terms, source_terms) -> bool:
    text = f"{title} {summary}".lower()
    for t in global_terms:
        if t and t in text:
            return True
    src_lower = (source_name or "").lower()
    for src, t in source_terms:
        if src in src_lower and t in text:
            return True
    return False

# -------- Discord-postaus --------

def post_to_discord(title: str, url: str, source: str, summary: str | None, image_url: str | None) -> None:
    if not WEBHOOK:
        raise RuntimeError("DISCORD_WEBHOOK_URL ei ole asetettu ympäristömuuttujaksi.")
    tag, color = classify(title)

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
        "footer": {"text": f"{tag} · RCF-uutiset"},
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    if image_url:
        if PREFER_LARGE_IMAGE:
            embed["image"] = {"url": image_url}
        else:
            embed["thumbnail"] = {"url": image_url}

    payload = {"embeds": [embed], "components": components}
    resp = requests.post(WEBHOOK, json=payload, timeout=REQUEST_TIMEOUT)
    if resp.status_code >= 300:
        raise RuntimeError(f"Discord POST failed: {resp.status_code} {resp.text}")

# -------------------------
#         Pääohjelma
# -------------------------

def main() -> None:
    feeds = read_feeds()
    if not feeds:
        print("[ERROR] feeds.txt on tyhjä tai puuttuu.")
        return

    # Lataa estot kerran ajon alussa
    global_terms, source_terms = load_blocklist()

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
            summary = clean_text(e.get("summary"))
            img = image_from_entry(e)

            # Paranna OG:lla
            og_img, og_desc = fetch_og_meta(link)
            if not img and og_img:
                img = og_img
            if (not summary or len(summary) < 40) and og_desc:
                summary = og_desc

            # ⛔ Esto-lista: ohita, jos täsmää
            if should_skip_article(source, title, summary, global_terms, source_terms):
                continue

            all_new.append((u, title, link, source, summary, img))

    # Postataan vanhimmasta uusimpaan
    all_new.reverse()
    print(f"[INFO] Uusia julkaisuja (suodatuksen jälkeen): {len(all_new)}")

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
