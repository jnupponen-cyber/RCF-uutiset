#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, re, json, time, html, requests
from datetime import datetime, timezone
from urllib.parse import urlparse

# --- Env ---
WEBHOOK              = os.environ["DISCORD_WEBHOOK_URL"]            # sama webhook kuin uutisbotsissa OK
OPENAI_API_KEY       = os.environ["OPENAI_API_KEY"]
OPENAI_API_BASE      = os.environ.get("OPENAI_API_BASE","https://api.openai.com/v1")
SUMMARY_MODEL        = os.environ.get("SUMMARY_MODEL","gpt-4o-mini")
COMMENT_MAXLEN       = int(os.environ.get("COMMENT_MAXLEN","240"))
REQUEST_TIMEOUT      = int(os.environ.get("REQUEST_TIMEOUT","12"))
DEBUG                = int(os.environ.get("DEBUG","1")) == 1

def logd(*a):
    if DEBUG: print("[userlink]", *a)

# --- Arvin persoona (pidetään linjassa nykyisen kanssa) ---
ARVI_PERSONA = (
    "Olet Arvi LindBot, suomalainen lakoninen uutistenlukija ja RCF-yhteisön seuralainen. "
    "Perusääni: tiivis, kuivakka ja usein sarkastinen, mutta välillä myös utelias tai osallistuva. "
    "Kirjoita aina selkeää ja luonnollista suomen yleiskieltä. "
    "Älä käännä englanninkielisiä sanontoja sanatarkasti; jos ilmaus ei sovi suoraan suomeen, "
    "käytä suomalaista vastaavaa tai neutraalia muotoa. "
    "Kommenttisi voivat olla 1–2 lausetta, joskus kolme jos aihe vaatii. "
    "Sarkasmi ja kuiva ironia kuuluvat tyyliisi, mutta älä ole ilkeä. "
    "Käytä korkeintaan yhtä emojiä lauseen loppuun, jos se sopii luontevasti. "
    "Ei hashtageja, ei mainoslauseita."
)

# --- Helpers ---
def truncate(s: str, n: int) -> str:
    s = (s or "").strip()
    if len(s) <= n: return s
    return s[:n-1].rstrip()+"…"

def favicon_for(url:str) -> str|None:
    try:
        host = urlparse(url).netloc
        return f"https://www.google.com/s2/favicons?sz=64&domain={host}" if host else None
    except: return None

def og_meta(url: str) -> tuple[str|None, str|None]:
    """(title, image) perus-OG: use fallback for non-YouTube."""
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT,
                         headers={"User-Agent":"Mozilla/5.0 (RCF UserLink Bot)", "Accept-Language":"en-US,en;q=0.9"})
        if r.status_code >= 400 or not r.text:
            return None, None
        t = r.text
        def _find(rx):
            m = re.search(rx, t, flags=re.I)
            return html.unescape(m.group(1).strip()) if m else None
        title = _find(r'<meta[^>]+property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']')
        if not title:
            m = re.search(r"<title>([^<]+)</title>", t, flags=re.I)
            title = html.unescape(m.group(1).strip()) if m else None
        image = _find(r'<meta[^>]+property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']')
        if not image:
            image = _find(r'<meta[^>]+name=["\']twitter:image["\'][^>]*content=["\']([^"\']+)["\']')
        return title, image
    except Exception as e:
        logd("og_meta fail:", e)
        return None, None

def yt_oembed(url: str) -> tuple[str|None, str|None]:
    """(title, thumb) via YouTube oEmbed."""
    try:
        r = requests.get("https://www.youtube.com/oembed",
                         params={"url": url, "format":"json"},
                         timeout=REQUEST_TIMEOUT,
                         headers={"User-Agent":"Mozilla/5.0 (RCF UserLink Bot)"})
        if r.status_code == 200:
            j = r.json()
            return j.get("title"), j.get("thumbnail_url")
        logd("oembed non-200:", r.status_code, r.text[:120])
    except Exception as e:
        logd("oembed err:", e)
    return None, None

def title_image_for(url: str) -> tuple[str|None, str|None]:
    host = (urlparse(url).netloc or "").lower()
    if "youtube.com" in host or "youtu.be" in host:
        title, img = yt_oembed(url)
        if title or img:
            return title, img
    # fallback
    return og_meta(url)

def openai_comment(title: str, url: str) -> str|None:
    user_msg = (
        "Kirjoita 1–2 lausetta suomeksi Arvi LindBotin äänellä tästä linkistä. "
        "Älä toista otsikkoa, älä käytä hashtageja. "
        f"Otsikko: {title or '-'}\nURL: {url}"
    )
    try:
        r = requests.post(
            f"{OPENAI_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type":"application/json"},
            json={
                "model": SUMMARY_MODEL,
                "messages":[
                    {"role":"system","content": ARVI_PERSONA},
                    {"role":"user","content": user_msg}
                ],
                "temperature":0.35,
                "max_tokens":220
            },
            timeout=REQUEST_TIMEOUT
        )
        if r.status_code >= 300:
            logd("openai http:", r.status_code, r.text[:200]); return None
        text = (r.json().get("choices",[{}])[0].get("message",{}) or {}).get("content","").strip()
        return truncate(text, COMMENT_MAXLEN) if text else None
    except Exception as e:
        logd("openai exc:", e); return None

def post_embed(url: str, title: str|None, image: str|None, comment: str|None):
    author = {"name": (urlparse(url).netloc or "Linkki")}
    fav = favicon_for(url)
    if fav: author["icon_url"] = fav

    description = comment or ""
    embed = {
        "type":"rich",
        "title": title or "Linkki",
        "url": url,
        "description": description,
        "author": author,
        "color": int("0x5865F2",16),
        "footer": {"text":"RCF Uutiskatsaus"},
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    if image:
        embed["image"] = {"url": image}

    payload = {
        # Ei content-kenttää → ei Discordin omaa unfurlia
        "embeds":[embed],
        "components":[
            {"type":1,"components":[{"type":2,"style":5,"label":"Avaa linkki","url":url}]}
        ]
    }

    r = requests.post(WEBHOOK, json=payload, timeout=REQUEST_TIMEOUT)
    if r.status_code == 429:
        time.sleep(float(r.headers.get("Retry-After","1")))
        r = requests.post(WEBHOOK, json=payload, timeout=REQUEST_TIMEOUT)
    if r.status_code >= 300:
        raise RuntimeError(f"Discord POST failed: {r.status_code} {r.text[:200]}")

def main():
    # Linkki annetaan GHA:sta tai paikallisesti envissä
    url = os.environ.get("USER_LINK_URL","").strip()
    if not url:
        raise SystemExit("USER_LINK_URL puuttuu.")

    logd("url =", url)

    title, image = title_image_for(url)
    logd("title:", title, "| image:", image)

    comment = openai_comment(title or "", url) or ""
    logd("comment:", comment)

    post_embed(url=url, title=title, image=image, comment=comment)

if __name__ == "__main__":
    main()