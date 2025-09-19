#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, re, time, html, requests
from datetime import datetime, timezone
from urllib.parse import urlparse

# --- Env ---
WEBHOOK              = os.environ["DISCORD_WEBHOOK_URL"]            # sama webhook kuin uutisbotsissa OK
OPENAI_API_KEY       = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_API_BASE      = os.environ.get("OPENAI_API_BASE","https://api.openai.com/v1")
SUMMARY_MODEL        = os.environ.get("SUMMARY_MODEL","gpt-4o-mini")
COMMENT_MAXLEN       = int(os.environ.get("COMMENT_MAXLEN","240"))
REQUEST_TIMEOUT      = int(os.environ.get("REQUEST_TIMEOUT","12"))
DEBUG                = int(os.environ.get("DEBUG","1")) == 1
PREFER_LARGE_IMAGE   = int(os.environ.get("PREFER_LARGE_IMAGE","1")) == 1
SOURCE_COLOR_HEX     = os.environ.get("SOURCE_COLOR_HEX","0x5865F2")
FOOTER_TEXT          = os.environ.get("FOOTER_TEXT","RCF Uutiskatsaus")

def logd(*a):
    if DEBUG: print("[userlink]", *a)

# --- Arvin persoona (pidetään linjassa nykyisen kanssa) ---
ARVI_PERSONA = (
    "Olet Arvi LindBot, suomalainen lakoninen uutistenlukija RCF-yhteisölle. "
    "Perusääni: tiivis, kuivakka ja usein sarkastinen. "
    "Kirjoita aina selkeää ja luonnollista suomen yleiskieltä. "
    "Vältä anglismeja ja suoria käännöslainoja: käytä suomalaisia pyöräilytermejä. "
    "Esimerkkejä: pääjoukko (ei peloton), irtiotto (ei breakaway), vetojuna (ei leadout), "
    "loppukiri (ei sprint), peesi/peesaaminen (ei draft/drafting), aika-ajo (ei TT), "
    "kokonaiskilpailu (ei GC), isku (ei attack), vetovuoro (ei pull). "
    "Älä mainitse sanaa \"pääjoukko\" ellei keskustelu oikeasti käsittele kilpapyöräilyn pääjoukkoa. "
    "Kommenttisi ovat 1–2 lausetta suomeksi. "
    "Huumorisi on lakonista ja vähäeleistä, mutta usein piikittelevää. "
    "Käytä korkeintaan yhtä emojiä loppuun, jos se sopii luontevasti. "
    "Sallittuja emojeja ovat esimerkiksi 🤷, 🚴, 😅, 🔧, 💤, 📈, 📉, 🕰️, 📊, 📰, ☕. "
    "Ei hashtageja, ei mainoslauseita. "
)

def parse_color(value: str, default: int) -> int:
    value = (value or "").strip()
    if not value:
        return default
    try:
        if value.startswith("#"):
            return int(value[1:], 16)
        if value.lower().startswith("0x"):
            return int(value, 16)
        try:
            return int(value, 16)
        except ValueError:
            return int(value, 10)
    except ValueError:
        logd("color parse fail:", value)
        return default

EMBED_COLOR = parse_color(SOURCE_COLOR_HEX, int("0x5865F2", 16))

# --- Helpers ---
def truncate(s: str, n: int) -> str:
    s = (s or "").strip()
    if len(s) <= n: return s
    return s[:n-1].rstrip()+"…"

def first_env(*names: str) -> str:
    for name in names:
        val = os.environ.get(name)
        if val and val.strip():
            return val.strip()
    return ""

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

def openai_comment(title: str, url: str, note: str = "") -> str|None:
    if not OPENAI_API_KEY:
        return None
    note = (note or "").strip()
    user_msg = [
        "Kirjoita 1–2 lausetta suomeksi Arvi LindBotin äänellä tästä linkistä.",
        "Älä toista otsikkoa, älä käytä hashtageja.",
        f"Otsikko: {title or '-'}",
        f"URL: {url}"
    ]
    if note:
        user_msg.append(f"Lisätieto: {note}")
    user_msg = "\n".join(user_msg)
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

def post_embed(url: str, title: str|None, image: str|None, comment: str|None, note: str|None):
    author = {"name": (urlparse(url).netloc or "Linkki")}
    fav = favicon_for(url)
    footer = {"text": FOOTER_TEXT}
    if fav:
        author["icon_url"] = fav
        footer["icon_url"] = fav

    description = comment or (note.strip() if note else "")
    embed = {
        "type":"rich",
        "title": title or "Linkki",
        "url": url,
        "description": description,
        "author": author,
        "color": EMBED_COLOR,
        "footer": footer,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    if image:
        key = "image" if PREFER_LARGE_IMAGE else "thumbnail"
        embed[key] = {"url": image}

    payload = {
        # Ei content-kenttää → ei Discordin omaa unfurlia
        "embeds":[embed],
        "components":[
            {"type":1,"components":[{"type":2,"style":5,"label":"Avaa artikkeli","url":url}]}
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
    url = first_env("USER_LINK_URL", "INPUT_URL", "URL")
    if not url:
        raise SystemExit("USER_LINK_URL puuttuu.")
    note = first_env("USER_LINK_NOTE", "INPUT_NOTE", "NOTE")

    logd("url =", url)
    if note:
        logd("note =", note)

    title, image = title_image_for(url)
    logd("title:", title, "| image:", image)

    comment = openai_comment(title or "", url, note) or ""
    logd("comment:", comment)

    post_embed(url=url, title=title, image=image, comment=comment, note=note)

if __name__ == "__main__":
    main()
