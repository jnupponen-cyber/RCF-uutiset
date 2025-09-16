#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, re, time, html, requests
from urllib.parse import urlparse
from datetime import datetime, timezone

# --- ENV & oletukset ---
WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_API_BASE = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1").strip()
SUMMARY_MODEL = (os.environ.get("SUMMARY_MODEL") or "gpt-4o-mini").strip()
SUMMARY_LANG = (os.environ.get("SUMMARY_LANG") or "fi").strip().lower()

URL_LIST = os.environ.get("URL_LIST", "").strip()
PING_ROLE_ID = (os.environ.get("PING_ROLE_ID") or "").strip()
COMMENT_MAXLEN = int(os.environ.get("COMMENT_MAXLEN") or "240")
PREFER_LARGE_IMAGE = int(os.environ.get("PREFER_LARGE_IMAGE") or "1") == 1
REQUEST_TIMEOUT = 15

if not WEBHOOK:
    raise SystemExit("DISCORD_WEBHOOK_URL puuttuu (repo/secrets).")
if not OPENAI_API_KEY:
    raise SystemExit("OPENAI_API_KEY puuttuu (repo/secrets).")
if not URL_LIST:
    raise SystemExit("URL_LIST on tyhjä (workflow_dispatch input).")

# --- Arvin persoona (älä muuta tätä blokista käsin) ---
ARVI_PERSONA = (
    "Olet Arvi LindBot, suomalainen lakoninen uutistenlukija ja RCF-yhteisön seuralainen. "
    "Perusääni: tiivis, kuivakka ja usein sarkastinen, mutta välillä myös utelias tai osallistuva. "
    "Kirjoita aina selkeää ja luonnollista suomen yleiskieltä. "
    "Älä käännä englanninkielisiä sanontoja sanatarkasti; jos ilmaus ei sovi suoraan suomeen, "
    "käytä suomalaista vastaavaa tai neutraalia muotoa. "
    "Kommenttisi voivat olla 1–2 lausetta, mutta joskus saatat venyttää kolmeen, jos aihe vaatii. "
    "Sarkasmi ja kuiva ironia kuuluvat tyyliisi, mutta älä ole ilkeä. "
    "Huumorisi on lakonista ja vähäeleistä, mutta usein piikittelevää – kuin uutistenlukija, "
    "joka ei aina ota kaikkea aivan vakavasti. "
    "Käytä korkeintaan yhtä emojiä loppuun, jos se sopii luontevasti. "
    "Sallittuja emojeja ovat esimerkiksi 🤷, 🚴, 😅, 🔧, 💤, 📈, 📉, 🕰️, 📊, 📰, ☕. "
    "Ei hashtageja, ei mainoslauseita. "
    "Useimmiten olet neutraali ja lakoninen, mutta säännöllisesti ironinen ja sarkastinen, "
    "ja joskus hiukan nostalginen. "
    "Voit reagoida käyttäjien kysymyksiin Zwiftistä, RCF Cupista tai pyöräilystä kuin kokenut seuraaja, "
    "mutta muistuta välillä, ettet ole ihminen vaan botti. "
)

# --- Lähdevärit (sama idea kuin uutisbottissa) ---
SOURCE_COLORS = {
    "Zwift Insider": int("0xFF6B00", 16),
    "Zwift.com News": int("0xFF6B00", 16),
    "MyWhoosh": int("0x2196F3", 16),
    "DC Rainmaker": int("0x9C27B0", 16),
    "GPLama": int("0x00BCD4", 16),
    "GCN": int("0xE91E63", 16),
    "GCN Tech": int("0x3F51B5", 16),
    "ZRace Central": int("0x4CAF50", 16),
    "Smart Bike Trainers": int("0x795548", 16),
    "Dylan Johnson Cycling": int("0x009688", 16),
    "TrainerRoad": int("0xF44336", 16),
    "Cycling Weekly": int("0x8BC34A", 16),
    "BikeRadar": int("0x1E88E5", 16),
    "Velo": int("0x00F7FF", 16),
}

# --- OG-tagien regexpit ---
OG_IMG_RE  = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', re.I)
TW_IMG_RE  = re.compile(r'<meta[^>]+name=["\']twitter:image["\'][^>]*content=["\']([^"\']+)["\']', re.I)
OG_DESC_RE = re.compile(r'<meta[^>]+property=["\']og:description["\'][^>]*content=["\']([^"\']+)["\']', re.I)
TW_DESC_RE = re.compile(r'<meta[^>]+name=["\']twitter:description["\'][^>]*content=["\']([^"\']+)["\']', re.I)
OG_TITLE_RE= re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']', re.I)
TITLE_TAG_RE= re.compile(r'<title[^>]*>(.*?)</title>', re.I|re.S)

def clean_text(s: str | None) -> str:
    if not s: return ""
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).strip()
    s = re.sub(r"\s+", " ", s)
    return s

def truncate(s: str, maxlen: int) -> str:
    if not s: return ""
    return s if len(s) <= maxlen else (s[:maxlen-1].rstrip() + "…")

def domain_favicon(url: str) -> str | None:
    try:
        host = urlparse(url).netloc
        if not host: return None
        return f"https://www.google.com/s2/favicons?sz=64&domain={host}"
    except Exception:
        return None

def fetch_og_meta(url: str) -> tuple[str|None, str|None, str|None]:
    """Palauttaa (title, desc, image) og-/twitter-tagien perusteella."""
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent":"Mozilla/5.0 (RCF News Bot)"})
        if r.status_code >= 400 or not r.text:
            return None, None, None
        html_txt = r.text

        title = None
        for rx in (OG_TITLE_RE,):
            m = rx.search(html_txt)
            if m:
                title = clean_text(m.group(1)); break
        if not title:
            m = TITLE_TAG_RE.search(html_txt)
            if m: title = clean_text(m.group(1))

        desc = None
        for rx in (OG_DESC_RE, TW_DESC_RE):
            m = rx.search(html_txt)
            if m: desc = clean_text(m.group(1)); break

        img = None
        for rx in (OG_IMG_RE, TW_IMG_RE):
            m = rx.search(html_txt)
            if m: img = m.group(1).strip(); break

        return title, desc, img
    except Exception:
        return None, None, None

def source_name_from_url(url: str) -> str:
    host = urlparse(url).netloc or ""
    host = host.replace("www.", "")
    # Kevyt normalisointi tunnetuille
    if "dcrainmaker" in host: return "DC Rainmaker"
    if "bikeradar" in host: return "BikeRadar"
    if "cyclingweekly" in host: return "Cycling Weekly"
    if "outsideonline" in host or "velo." in host: return "Velo"
    if "zwiftinsider" in host: return "Zwift Insider"
    if "trainerroad" in host: return "TrainerRoad"
    if "youtube.com" in host or "youtu.be" in host:
        return "YouTube"
    # Fallback: domain pääosat
    return host.capitalize() if host else "Uutinen"

def ai_make_comment(title: str, source: str, url: str, raw_summary: str | None, maxlen: int) -> str | None:
    """Generoi Arvin 1–3 lauseen kommentin (vain suomeksi, ei alkuperäistä kuvausta embedissä)."""
    if not OPENAI_API_KEY:
        return None
    system_msg = ARVI_PERSONA
    user_msg = (
        f"Kieli: {SUMMARY_LANG}\n"
        f"Maksimipituus: {maxlen} merkkiä.\n"
        f"Lähde: {source}\n"
        f"Otsikko: {title}\n"
        f"URL: {url}\n"
        f"Taustaksi tiivistelmä (voi olla englanniksi): {raw_summary or '-'}\n\n"
        "Kirjoita vain Arvin kommentti (1–3 lausetta). Älä toista otsikkoa. "
        "Älä käytä hashtageja. Yksi emoji lopussa on sallittu, jos se sopii luontevasti."
    )
    try:
        resp = requests.post(
            f"{OPENAI_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": SUMMARY_MODEL,
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg}
                ],
                "temperature": 0.35,
                "max_tokens": 300
            },
            timeout=REQUEST_TIMEOUT
        )
        if resp.status_code >= 300:
            print("OpenAI error:", resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        text = clean_text(text)
        return truncate(text, maxlen) if text else None
    except Exception as e:
        print("OpenAI exception:", e)
        return None

def post_embed(title: str, url: str, source: str,
               arvi_comment: str | None, image_url: str | None,
               ping_role_id: str | None):
    """Postaa webhookilla: embed.description = VAIN Arvin kommentti (ei alkuperäistä kuvausta)."""
    color = SOURCE_COLORS.get(source, int("0x5865F2", 16))
    footer_text = f"{source} · RCF Uutiskatsaus"

    author = {"name": source}
    fav = domain_favicon(url)
    footer = {"text": footer_text}
    if fav:
        author["icon_url"] = fav
        footer["icon_url"] = fav

    description = arvi_comment or ""

    embed = {
        "type": "rich",
        "title": title or "Uutinen",
        "url": url,
        "description": description,
        "color": color,
        "author": author,
        "footer": footer,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    if image_url:
        if PREFER_LARGE_IMAGE:
            embed["image"] = {"url": image_url}
        else:
            embed["thumbnail"] = {"url": image_url}

    # Nappi
    components = [{
        "type": 1,
        "components": [{
            "type": 2,
            "style": 5,
            "label": "Avaa artikkeli",
            "url": url
        }]
    }]

    # Ping vain roolille jos annettu
    payload = {"embeds": [embed], "components": components}
    if ping_role_id and ping_role_id.isdigit():
        payload["content"] = f"<@&{ping_role_id}>"
        payload["allowed_mentions"] = {"parse": [], "roles": [ping_role_id]}

    r = requests.post(WEBHOOK, json=payload, timeout=REQUEST_TIMEOUT)
    if r.status_code == 429:
        delay = float(r.headers.get("Retry-After", "1") or "1")
        time.sleep(max(delay, 1.0))
        r = requests.post(WEBHOOK, json=payload, timeout=REQUEST_TIMEOUT)
    if r.status_code >= 300:
        raise RuntimeError(f"Discord POST failed: {r.status_code} {r.text[:200]}")

def handle_one_url(url: str):
    url = url.strip()
    if not url: return
    title, raw_desc, img = fetch_og_meta(url)
    source = source_name_from_url(url)

    # Otsikko fallback
    if not title:
        title = url

    # Arvin kommentti (ei näytetä alkuperäistä kuvausta embedissä, tyyli pysyy samana kuin uutisbottisi uusin versio)
    comment = ai_make_comment(title=title, source=source, url=url, raw_summary=raw_desc, maxlen=COMMENT_MAXLEN)

    print(f"[DEBUG] Posting: {source} | {title} | {url}")
    post_embed(title=title, url=url, source=source,
               arvi_comment=comment, image_url=img,
               ping_role_id=PING_ROLE_ID if PING_ROLE_ID else None)

def main():
    # sallitaan myös monta linkkiä (rivi per linkki)
    urls = [u.strip() for u in URL_LIST.splitlines() if u.strip()]
    for u in urls:
        try:
            handle_one_url(u)
            time.sleep(0.8)
        except Exception as e:
            print(f"[WARN] Failed for {u}: {e}")

if __name__ == "__main__":
    main()
