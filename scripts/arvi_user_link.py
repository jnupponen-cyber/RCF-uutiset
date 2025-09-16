#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, re, html, time
from datetime import datetime, timezone
import requests
from urllib.parse import urlparse

# --- Env ---
WEBHOOK             = os.environ["DISCORD_WEBHOOK_URL"].strip()
OPENAI_API_KEY      = os.environ.get("OPENAI_API_KEY","").strip()
OPENAI_API_BASE     = os.environ.get("OPENAI_API_BASE","https://api.openai.com/v1").strip()
SUMMARY_MODEL       = os.environ.get("SUMMARY_MODEL","gpt-4o-mini").strip()
COMMENT_MAXLEN      = int(os.environ.get("COMMENT_MAXLEN","240"))
PREFER_LARGE_IMAGE  = int(os.environ.get("PREFER_LARGE_IMAGE","1")) == 1
SOURCE_COLOR        = int(os.environ.get("SOURCE_COLOR_HEX","0x5865F2"), 16)

INPUT_URL           = (os.environ.get("INPUT_URL","") or "").strip()
INPUT_NOTE          = (os.environ.get("INPUT_NOTE","") or "").strip()

REQUEST_TIMEOUT     = 12

# --- Arvin persona (älä muuta ilman syytä) ---
ARVI_PERSONA = (
    "Olet Arvi LindBot, suomalainen lakoninen uutistenlukija RCF-yhteisölle. "
    "Perusääni: neutraali, asiallinen ja tiivis. "
    "Kirjoita aina selkeää ja luonnollista suomen yleiskieltä. "
    "Älä käännä englanninkielisiä sanontoja sanatarkasti; jos ilmaus ei sovi suoraan suomeen, "
    "käytä suomalaista vastaavaa tai neutraalia muotoa. "
    "Voit silloin tällöin käyttää hillittyä sarkasmia tai kuivaa ironiaa, mutta älä usein. "
    "Huumorisi on vähäeleistä ja kuivakkaa, ei ilkeää. Älä liioittele. "
    "Käytä 1–2 lyhyttä lausetta suomeksi. "
    "Voit käyttää korkeintaan yhtä emojiä, jos se sopii luontevasti sävyyn, "
    "ja sijoita se aina lauseen loppuun. Esimerkiksi 🤷, 🚴, 😅, 🔧, 💤, 📈. "
    "Ei hashtageja, ei mainoslauseita. "
    "Jos aihe on triviaali, tokaise se lakonisesti. Jos aihe on ylihypetetty, "
    "voit joskus kommentoida ironisesti, esimerkiksi 'taas kerran' tai 'suurin mullistus sitten eilisen'. "
    "Voit harvakseltaan viitata RCF-yhteisöön tai muistuttaa olevasi vain botti. "
    "Vaihtele sävyä: useimmiten neutraali ja lakoninen, mutta toisinaan ironinen tai nostalginen. "
)

# --- Helpers ---
def clean_text(s: str|None) -> str:
    if not s: return ""
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

OG_IMG_RE   = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', re.I)
TW_IMG_RE   = re.compile(r'<meta[^>]+name=["\']twitter:image["\'][^>]*content=["\']([^"\']+)["\']', re.I)
OG_DESC_RE  = re.compile(r'<meta[^>]+property=["\']og:description["\'][^>]*content=["\']([^"\']+)["\']', re.I)
TW_DESC_RE  = re.compile(r'<meta[^>]+name=["\']twitter:description["\'][^>]*content=["\']([^"\']+)["\']', re.I)
OG_TITLE_RE = re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']', re.I)
TW_TITLE_RE = re.compile(r'<meta[^>]+name=["\']twitter:title["\'][^>]*content=["\']([^"\']+)["\']', re.I)
TITLE_TAG_RE= re.compile(r'<title[^>]*>(.*?)</title>', re.I|re.S)

def fetch_og(url: str) -> tuple[str, str, str]:
    """
    Palauttaa (title, description, image_url).
    Fallbackit: <title>, domain-nimi, tyhjä.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (RCF User Link Bot)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"
    }
    try:
        r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if r.status_code >= 400 or not r.text:
            raise RuntimeError(f"HTTP {r.status_code}")
        html_txt = r.text
    except Exception:
        # OG epäonnistui -> palauta edes domain otsikoksi
        dom = urlparse(url).netloc or "Linkki"
        return dom, "", None

    title = None
    desc  = None
    img   = None

    for rx in (OG_TITLE_RE, TW_TITLE_RE):
        m = rx.search(html_txt)
        if m:
            title = clean_text(m.group(1)); break
    if not title:
        m = TITLE_TAG_RE.search(html_txt)
        title = clean_text(m.group(1)) if m else None

    for rx in (OG_DESC_RE, TW_DESC_RE):
        m = rx.search(html_txt)
        if m:
            desc = clean_text(m.group(1)); break

    for rx in (OG_IMG_RE, TW_IMG_RE):
        m = rx.search(html_txt)
        if m:
            img = clean_text(m.group(1)); break

    if not title:
        title = urlparse(url).netloc or "Linkki"
    return title, (desc or ""), img

def truncate(s: str, n: int) -> str:
    if len(s) <= n: return s
    return s[:n-1].rstrip()+"…"

def domain_favicon(url: str) -> str|None:
    try:
        host = urlparse(url).netloc
        if not host: return None
        return f"https://www.google.com/s2/favicons?sz=64&domain={host}"
    except Exception:
        return None

def ai_comment(title: str, source: str, url: str, raw_desc: str, note: str|None) -> str|None:
    if not OPENAI_API_KEY:  # ilman avainta postataan silti, mutta ilman Arvia
        return None
    user_msg = (
        f"Otsikko: {title}\n"
        f"Lähde: {source}\n"
        f"URL: {url}\n"
        f"Kuvaus (voi olla englanniksi): {raw_desc or '-'}\n"
    )
    if note:
        user_msg += f"Konteksti / huomio: {note}\n"
    user_msg += (
        f"\nKirjoita 1–2 lausetta suomeksi Arvi LindBotin äänellä. "
        f"Pituus enintään {COMMENT_MAXLEN} merkkiä. Älä toista otsikkoa."
    )
    try:
        resp = requests.post(
            f"{OPENAI_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type":"application/json"},
            json={
                "model": SUMMARY_MODEL,
                "messages":[
                    {"role":"system","content": ARVI_PERSONA},
                    {"role":"user","content": user_msg}
                ],
                "temperature": 0.3,
                "max_tokens": 220
            },
            timeout=REQUEST_TIMEOUT
        )
        if resp.status_code >= 300:
            print("OpenAI error:", resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        out = clean_text((data.get("choices",[{}])[0].get("message",{}) or {}).get("content",""))
        return truncate(out, COMMENT_MAXLEN) if out else None
    except Exception as e:
        print("AI exception:", e)
        return None

def post_discord(title: str, url: str, source: str, image_url: str|None, arvi: str|None):
    # Embed.description: vain Arvin kommentti (ei alkuperäistä kuvausta)
    description = arvi or ""
    favicon = domain_favicon(url)
    footer_text = f"{source} · RCF Uutiskatsaus"

    embed = {
        "type":"rich",
        "title": title,
        "url":   url,
        "description": description,
        "color": SOURCE_COLOR,
        "author": {"name": source, **({"icon_url": favicon} if favicon else {})},
        "footer": {"text": footer_text, **({"icon_url": favicon} if favicon else {})},
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    if image_url:
        if PREFER_LARGE_IMAGE:
            embed["image"] = {"url": image_url}
        else:
            embed["thumbnail"] = {"url": image_url}

    # Linkkipainike
    components = [{
        "type": 1,
        "components": [{
            "type": 2, "style": 5,
            "label": "Avaa artikkeli",
            "url": url
        }]
    }]

    payload = {"embeds":[embed], "components": components}

    r = requests.post(WEBHOOK, json=payload, timeout=REQUEST_TIMEOUT)
    if r.status_code == 429:
        # yksinkertainen retry
        time.sleep(1.2)
        r = requests.post(WEBHOOK, json=payload, timeout=REQUEST_TIMEOUT)
    if r.status_code >= 300:
        raise RuntimeError(f"Discord POST failed {r.status_code}: {r.text[:200]}")

def main():
    if not INPUT_URL:
        raise SystemExit("INPUT_URL puuttuu. Aja workflow_dispatch syöttämällä URL.")

    # OG-metat sivulta
    title, raw_desc, og_img = fetch_og(INPUT_URL)
    source = urlparse(INPUT_URL).netloc or "Linkki"

    # Arvin kommentti (vain suomeksi; ei liitetä alkuperäistä kuvausta)
    comment = ai_comment(title=title, source=source, url=INPUT_URL, raw_desc=raw_desc, note=INPUT_NOTE)

    post_discord(
        title=title,
        url=INPUT_URL,
        source=source,
        image_url=og_img,
        arvi=comment
    )

if __name__ == "__main__":
    main()
