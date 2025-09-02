#!/usr/bin/env python3
"""
RCF Discord uutisbotin "kevyt" versio.
- Lukee RSS-syötteet tiedostosta feeds.txt
- Estää duplikaatit seen.jsonin avulla
- Postaa Discord-kanavaan WEBHOOKilla
"""
import os, json, time, hashlib, html, re
from datetime import datetime, timezone
import requests
import feedparser

STATE_FILE = "seen.json"
FEEDS_FILE = "feeds.txt"
WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
MAX_ITEMS_PER_FEED = 10  # tarkistetaan vain tuoreimmat N merkintää / feed
POST_DELAY_SEC = 1       # pieni tauko Discordin rajojen kunnioittamiseksi

def load_seen(path=STATE_FILE):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
                if isinstance(data, dict) and "ids" in data:
                    return set(data["ids"])
        except Exception:
            pass
    return set()

def save_seen(seen, path=STATE_FILE):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sorted(list(seen)), f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] save_seen failed: {e}")

def read_feeds(path=FEEDS_FILE):
    feeds = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                url = line.strip()
                if url and not url.startswith("#"):
                    feeds.append(url)
    return feeds

def uid_from_entry(entry):
    base = entry.get("id") or entry.get("link") or entry.get("title","")
    return hashlib.sha256(base.encode("utf-8")).hexdigest()

def clean_summary(s, maxlen=240):
    if not s:
        return ""
    # poista HTML-tagit
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).strip()
    s = re.sub(r"\s+", " ", s)
    if len(s) > maxlen:
        s = s[:maxlen-1].rstrip() + "…"
    return s

def post_to_discord(title, url, source, summary=None, image_url=None):
    if not WEBHOOK:
        raise RuntimeError("DISCORD_WEBHOOK_URL ei ole asetettu ympäristömuuttujaksi.")
    content = f"📰 **{title}**\nLähde: {source}\n{url}"
    embeds = []
    if summary or image_url:
        embed = {"type":"rich"}
        if summary:
            embed["description"] = summary
        if image_url:
            embed["image"] = {"url": image_url}
        embeds = [embed]
    resp = requests.post(WEBHOOK, json={"content": content, "embeds": embeds}, timeout=20)
    if resp.status_code >= 300:
        raise RuntimeError(f"Discord POST failed: {resp.status_code} {resp.text}")

def image_from_entry(entry):
    # Yritetään löytää kuva: media_thumbnail, media_content, tai content:encoded:sta <img>
    for key in ("media_thumbnail", "media_content"):
        if key in entry and entry[key]:
            try:
                url = entry[key][0].get("url")
                if url: return url
            except Exception:
                pass
    # fallback: etsi mahdollinen <img src="..."> summarystä
    html_part = entry.get("summary") or ""
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html_part, flags=re.I)
    if m:
        return m.group(1)
    return None

def main():
    seen = load_seen()
    feeds = read_feeds()
    if not feeds:
        print("[ERROR] feeds.txt on tyhjä. Lisää RSS-osoitteet.")
        return
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
    # uusin ensin (oletetaan että feedparser palauttaa uudet ensin)
    all_new.reverse()
    print(f"[INFO] Uusia julkaisuja: {len(all_new)}")
    for u, title, link, source, summary, img in all_new:
        try:
            post_to_discord(title, link, source, summary=summary, image_url=img)
            seen.add(u)
            time.sleep(POST_DELAY_SEC)
        except Exception as e:
            print(f"[WARN] Postaus epäonnistui: {e}")
    save_seen(seen)

if __name__ == "__main__":
    main()
