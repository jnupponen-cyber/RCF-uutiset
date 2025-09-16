#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RCF Discord -uutisbotti (embedit + OG-kuvat + block/whitelist + ping + per-lähde värit + termien normalisointi)

Uudet asiat:
- Termien normalisointi CSV:stä (terms_fi.csv) ennen Discord-postia
- Arvin persoonan ohjaus käyttämään suomenkielisiä pyöräilytermejä

Ympäristömuuttujat (esimerkit):
- DISCORD_WEBHOOK_URL=...
- DEBUG=1
- BLOCK_YT_SHORTS=1
- ALLOW_SHORTS_IF_WHITELIST=0
- PREFER_LARGE_IMAGE=1
- MAX_ITEMS_PER_FEED=10
- SUMMARY_MAXLEN=200
- COMMENT_MAXLEN=240
- ENABLE_AI_SUMMARY=1
- SUMMARY_MODEL=gpt-4o-mini
- SUMMARY_LANG=fi
- OPENAI_API_KEY=...
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
WHITELIST_FILE = SCRIPT_DIR / "whitelist.txt"
TERMS_FILE = SCRIPT_DIR / "terms_fi.csv"

# Estä YouTube Shorts -URLit kovasäännöllä (oletus: päällä)
BLOCK_YT_SHORTS = int(os.environ.get("BLOCK_YT_SHORTS", "1")) == 1
# Salli Shorts jos whitelist osuu (oletus: pois)
ALLOW_SHORTS_IF_WHITELIST = int(os.environ.get("ALLOW_SHORTS_IF_WHITELIST", "0")) == 1

WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

# Ping-asetukset
MENTION_USER_ID = os.environ.get("MENTION_USER_ID", "").strip()
MENTION_ROLE_ID = os.environ.get("MENTION_ROLE_ID", "").strip()

# Ajotapa
MAX_ITEMS_PER_FEED = int(os.environ.get("MAX_ITEMS_PER_FEED", "10"))
POST_DELAY_SEC = float(os.environ.get("POST_DELAY_SEC", "1"))
SUMMARY_MAXLEN = int(os.environ.get("SUMMARY_MAXLEN", "200"))
COMMENT_MAXLEN = int(os.environ.get("COMMENT_MAXLEN", "240"))
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "12"))
PREFER_LARGE_IMAGE = int(os.environ.get("PREFER_LARGE_IMAGE", "1")) == 1

# DEBUG-moodi
DEBUG = int(os.environ.get("DEBUG", "1")) == 1
def logd(*args):
    if DEBUG:
        print("[DEBUG]", *args)

# --- AI-kommentit (Arvin persoona) ---
ENABLE_AI_SUMMARY = int(os.environ.get("ENABLE_AI_SUMMARY", "1")) == 1
SUMMARY_MODEL = os.environ.get("SUMMARY_MODEL", "gpt-4o-mini").strip()
SUMMARY_LANG = os.environ.get("SUMMARY_LANG", "fi").strip().lower()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_API_BASE = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1").strip()

ARVI_PERSONA = (
    "Olet Arvi LindBot, suomalainen lakoninen uutistenlukija RCF-yhteisölle. "
    "Perusääni: tiivis, kuivakka ja usein sarkastinen. "
    "Kirjoita aina selkeää ja luonnollista suomen yleiskieltä. "
    "Vältä anglismeja ja suoria käännöslainoja: käytä suomalaisia pyöräilytermejä. "
    "Esimerkkejä: pääjoukko (ei peloton), irtiotto (ei breakaway), vetojuna (ei leadout), "
    "loppukiri (ei sprint), peesi/peesaaminen (ei draft/drafting), aika-ajo (ei TT), "
    "kokonaiskilpailu (ei GC), isku (ei attack), vetovuoro (ei pull). "
    "Kommenttisi ovat 1–2 lausetta suomeksi. "
    "Huumorisi on lakonista ja vähäeleistä, mutta usein piikittelevää. "
    "Käytä korkeintaan yhtä emojiä loppuun, jos se sopii luontevasti. "
    "Sallittuja emojeja ovat esimerkiksi 🤷, 🚴, 😅, 🔧, 💤, 📈, 📉, 🕰️, 📊, 📰, ☕. "
    "Ei hashtageja, ei mainoslauseita. "
)

# --- Per-lähde värikoodit ---
SOURCE_COLORS = {
    "Zwift Insider":          int("0xFF6B00", 16),
    "Zwift.com News":         int("0xFF6B00", 16),
    "Zwift":                  int("0xFF6B00", 16),
    "DC Rainmaker":           int("0x9C27B0", 16),
    "Cycling Weekly":         int("0xdd1b21", 16),
    "Cycling Weekly RSS":     int("0xdd1b21", 16),
    "Latest from Cycling Weekly": int("0xdd1b21", 16),
    "Velo":                   int("0x00F7FF", 16),
    "Velo News":              int("0x05ffff", 16),
    "Velo – Road Gear":       int("0x05ffff", 16),
    "Velo – Road Training":   int("0x05ffff", 16),
    "Velo – Gravel Gear":     int("0x05ffff", 16),
    "TrainerRoad":            int("0xd9291c", 16),
    "BikeRadar":              int("0x2c4975", 16),
    "BikeRadar Gravel":       int("0x2c4975", 16),
    "BikeRadar Road News":    int("0x2c4975", 16),
    "BikeRadar News":         int("0x2c4975", 16),
    "BikeRadar Road":         int("0x2c4975", 16),
    "Road.cc":                int("0x1bb4e3", 16),
    "Road.cc RSS Feed":       int("0x1bb4e3", 16),
    "RoadCyclingUK":          int("0x1bb4e3", 16),
    "BikeRumor":              int("0xff9a03", 16),
    "Bicycling":              int("0xff3200", 16),
    "Training4cyclists":      int("0x455A64", 16),
    "MyWhoosh":               int("0x455A64", 16),
    "GCN":                    int("0xb80f15", 16),
    "Global Cycling Network": int("0xb80f15", 16),
    "GCN Tech":               int("0xb80f15", 16),
    "GPLama":                 int("0xffffff", 16),
    "Smart Bike Trainers":    int("0xb33e2c", 16),
    "Dylan Johnson Cycling":  int("0xe0f1fb", 16),
    "DC Rainmaker (YouTube)": int("0x9C27B0", 16),
    "Road.cc Tech of the Week": int("0x00AEEF", 16),
    "Velo | Buyer’s Guide":    int("0x05ffff", 16),
    "Velogi":                  int("0x179deb", 16),
    "ISKUS":                  int("0xc0dbfc", 16),
    "Antti Järvinen":         int("0xffffff", 16),
}

# --- Regex OG-metaan ---
OG_IMG_RE  = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', re.I)
TW_IMG_RE  = re.compile(r'<meta[^>]+name=["\']twitter:image["\'][^>]*content=["\']([^"\']+)["\']', re.I)
OG_DESC_RE = re.compile(r'<meta[^>]+property=["\']og:description["\'][^>]*content=["\']([^"\']+)["\']', re.I)
TW_DESC_RE = re.compile(r'<meta[^>]+name=["\']twitter:description["\'][^>]*content=["\']([^"\']+)["\']', re.I)

# --- Sanahaku: kokonaiset sanat + termipituusraja ---
_WORD_RE_CACHE = {}
def _word_in(text: str, term: str) -> bool:
    term = term.strip()
    if not term or len(term) < 3:
        return False
    rx = _WORD_RE_CACHE.get(term)
    if rx is None:
        rx = re.compile(rf"\b{re.escape(term)}\b", flags=re.I)
        _WORD_RE_CACHE[term] = rx
    return rx.search(text) is not None

def _valid_discord_id(s: str) -> bool:
    return bool(s) and s.isdigit() and s != "0" and len(s) >= 5

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
    else:
        print(f"[WARN] feeds file not found: {path}")
    return feeds

def uid_from_entry(entry) -> str:
    base = entry.get("id") or entry.get("link") or entry.get("title", "")
    return hashlib.sha256(base.encode("utf-8")).hexdigest()

def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", s)
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
    html_part = entry.get("summary") or ""
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html_part, flags=re.I)
    return m.group(1) if m else None

def fetch_og_meta(url: str) -> tuple[str | None, str | None]:
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

def _limit_to_two_sentences(text: str) -> str:
    parts = re.split(r'(?<=[\.\!\?])\s+', text.strip())
    short = " ".join([p for p in parts if p][:2]).strip()
    return short if short else text

# --- Termisanasto: lataus + normalisointi ---

def load_terms_csv(path: Path = TERMS_FILE):
    """
    CSV-muoto: 'väärin;oikein;tiukka'
    - väärin: plain string tai regex (tarvittaessa)
    - oikein: korvausteksti
    - tiukka: '1' = lisätään automaattisesti sanansidokset \b...\\b jos niitä ei ole
    """
    rules = []
    if not path.exists():
        logd("terms.csv not found:", str(path))
        return rules
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 3:
            continue
        wrong, correct, strict = parts[0], parts[1], parts[2]
        strict = str(strict).strip().lower() in ("1", "true", "yes")
        # Jos käyttäjä ei itse lisännyt \b rajoja ja strict=1, lisää ne
        if strict and not wrong.startswith(r"\b"):
            wrong = r"\b" + wrong
        if strict and not wrong.endswith(r"\b"):
            wrong = wrong + r"\b"
        try:
            rx = re.compile(wrong, flags=re.IGNORECASE)
            rules.append((rx, correct))
        except re.error as e:
            logd("terms regex error, skipping:", wrong, "|", e)
            continue
    logd("terms loaded:", len(rules))
    return rules

_TERMS_RULES = None  # ladataan laiskasti, jotta testit voivat yliajaa polun

def _preserve_case(src: str, repl: str) -> str:
    """
    Säilytä lähteen kirjainkoko järkevästi:
    - kaikki caps -> myös korvaus caps
    - alkukirjain iso -> tee korvauksessa alkukirjain isoksi
    - muutoin anna korvauksen olla sellaisenaan
    """
    if not src:
        return repl
    if src.isupper():
        return repl.upper()
    if src[0].isupper():
        return repl[0].upper() + repl[1:]
    return repl

def normalize_terms(text: str) -> str:
    """
    Korvaa väärät/englannista lainatut termit oikeilla.
    """
    global _TERMS_RULES
    if _TERMS_RULES is None:
        _TERMS_RULES = load_terms_csv()
    if not text or not _TERMS_RULES:
        return text
    out = text
    for rx, correct in _TERMS_RULES:
        def _sub(m):
            return _preserve_case(m.group(0), correct)
        out = rx.sub(_sub, out)
    # Kevyt siistintä
    out = re.sub(r"\s{2,}", " ", out).strip()
    out = re.sub(r"\s+([,.!?:;])", r"\1", out)
    return out

# --- AI-kommentti (Arvin persoonalla) ---
def ai_make_comment(title: str, source: str, url: str, raw_summary: str, maxlen: int) -> str | None:
    if not ENABLE_AI_SUMMARY or not OPENAI_API_KEY:
        return None

    system_msg = ARVI_PERSONA
    # Pieni sanastolista mallille (deterministinen korjaus tehdään joka tapauksessa normalize_termsilla)
    glossary_hint = (
        "Termisanasto (käytä näitä muotoja): "
        "peloton=pääjoukko; breakaway=irtiotto; leadout=vetojuna; sprint=loppukiri; "
        "draft=peesi; drafting=peesaaminen; GC=kokonaiskilpailu; TT=aika-ajo; "
        "attack=isku; pull=vetovuoro."
    )

    user_msg = (
        f"Kieli: {SUMMARY_LANG}\n"
        f"Maksimipituus: {maxlen} merkkiä.\n"
        f"Lähde: {source}\n"
        f"Otsikko: {title}\n"
        f"URL: {url}\n"
        f"Alkuperäinen kuvaus (voi olla englanniksi, käytä vain jos auttaa kiteytyksessä): {raw_summary or '-'}\n\n"
        f"{glossary_hint}\n"
        "Kirjoita vain 1–2 lausetta suomeksi. Älä toista otsikkoa. "
        "Ei hashtageja/emojeja ellei yksi sovi luonnollisesti loppuun."
    )

    try:
        payload = {
            "model": SUMMARY_MODEL,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.3,
            "max_tokens": 220,
        }
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        resp = requests.post(f"{OPENAI_API_BASE}/chat/completions", headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
        if resp.status_code >= 300:
            logd("AI SUMMARY HTTP ERROR:", resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        text = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""
        text = clean_text(text)
        if not text:
            return None
        text = _limit_to_two_sentences(text)
        return truncate(text, maxlen)
    except Exception as e:
        logd("AI SUMMARY EXC:", e)
        return None

# -------- Listat (block/white) --------
def load_blocklist(path: Path = BLOCKLIST_FILE):
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
            global_terms.append(line)
    return global_terms, source_terms

def load_whitelist(path: Path = WHITELIST_FILE):
    global_terms, source_terms, sources = [], [], []
    if not path.exists():
        return global_terms, source_terms, sources
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        low = line.lower()
        if low.startswith("source=") and "|" in line:
            left, term = line.split("|", 1)
            src = left.split("=", 1)[1].strip().lower()
            source_terms.append((src, term.strip().lower()))
        elif low.startswith("allow_source="):
            sources.append(line.split("=", 1)[1].strip().lower())
        else:
            global_terms.append(line)
    return global_terms, source_terms, sources

def is_whitelisted(source_name: str, title: str, summary: str, link: str,
                   wl_global, wl_source_terms, wl_sources) -> bool:
    text = f"{title} {summary}"
    link_l = link or ""
    src_lower = (source_name or "").lower()
    if src_lower in wl_sources:
        return True
    for t in wl_global:
        if _word_in(text, t) or _word_in(link_l, t):
            return True
    for src, t in wl_source_terms:
        if src in src_lower and (_word_in(text, t) or _word_in(link_l, t)):
            return True
    return False

def should_skip_article(source_name: str,
                        title: str,
                        summary: str,
                        link: str,
                        bl_global,
                        bl_source,
                        wl_global,
                        wl_source,
                        wl_sources) -> tuple[bool, str | None]:
    text = f"{title} {summary}"
    link_l = (link or "")
    src_lower = (source_name or "").lower()

    if is_whitelisted(source_name, title, summary, link, wl_global, wl_source, wl_sources):
        if BLOCK_YT_SHORTS and ("youtube.com/shorts/" in link_l.lower()) and not ALLOW_SHORTS_IF_WHITELIST:
            return True, "shorts"
        return False, None

    if BLOCK_YT_SHORTS and ("youtube.com/shorts/" in link_l.lower()):
        return True, "shorts"

    for t in bl_global:
        if _word_in(text, t) or _word_in(link_l, t):
            return True, f"global:{t.strip().lower()}"

    for src, t in bl_source:
        if src in src_lower and (_word_in(text, t) or _word_in(link_l, t)):
            return True, f"source:{src}|{t}"

    return False, None

# -------- Discord-postaus --------
def post_to_discord(title: str, url: str, source: str,
                    raw_summary: str | None, image_url: str | None,
                    ai_comment: str | None = None) -> None:
    """
    Embed.description = VAIN Arvin kommentti (ei alkuperäistä kuvausta).
    """
    if not WEBHOOK:
        raise RuntimeError("DISCORD_WEBHOOK_URL ei ole asetettu ympäristömuuttujaksi.")

    # Valmistellaan teksti: vain Arvin kommentti
    comment = truncate((ai_comment or "").strip(), COMMENT_MAXLEN) if ai_comment else ""
    description = comment if comment else "(ei kommenttia)"

    # Väri ja footer
    color = SOURCE_COLORS.get(source, int("0x5865F2", 16))
    footer_text = f"{source} · RCF Uutiskatsaus"

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

    # Author + favicon
    author = {"name": source}
    fav = domain_favicon(url)
    footer = {"text": footer_text}
    if fav:
        author["icon_url"] = fav
        footer["icon_url"] = fav

    embed = {
        "type": "rich",
        "title": title,
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

    # Pingi (content)
    content = None
    allowed = {"parse": []}
    if _valid_discord_id(MENTION_USER_ID):
        content = f"<@{MENTION_USER_ID}>"
        allowed["users"] = [MENTION_USER_ID]
    elif _valid_discord_id(MENTION_ROLE_ID):
        content = f"<@&{MENTION_ROLE_ID}>"
        allowed["roles"] = [MENTION_ROLE_ID]

    payload = {"embeds": [embed], "components": components}
    if content:
        payload["content"] = content
        payload["allowed_mentions"] = allowed

    resp = requests.post(WEBHOOK, json=payload, timeout=REQUEST_TIMEOUT)
    if resp.status_code == 429:
        try:
            delay = float(resp.headers.get("Retry-After", "1"))
        except Exception:
            delay = 1.0
        time.sleep(max(delay, 1.0))
        resp = requests.post(WEBHOOK, json=payload, timeout=REQUEST_TIMEOUT)

    if resp.status_code >= 300:
        raise RuntimeError(f"Discord POST failed: {resp.status_code} {resp.text}")

# -------- Feed-haku --------
def parse_feed(url: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (RCF News Bot; +https://github.com/rcf)",
        "Accept": "application/atom+xml, application/rss+xml;q=0.9, application/xml;q=0.8, text/xml;q=0.7, */*;q=0.5",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200 and r.content:
            return feedparser.parse(r.content)
        else:
            logd("FEED HTTP:", url, "| status:", r.status_code)
    except Exception as e:
        logd("FEED REQ EXC:", url, "| err:", e)
    return feedparser.parse(url, request_headers=headers)

# -------- Pääsilmukka --------
def source_name_from_feed(parsed, fallback_url: str) -> str:
    try:
        name = parsed.feed.get("title")
        if name:
            return clean_text(name)
    except Exception:
        pass
    return urlparse(fallback_url).netloc

def process_feed(url: str, seen: set,
                 bl_global, bl_source,
                 wl_global, wl_source, wl_sources) -> dict:
    stats = {"total": 0, "posted": 0, "skipped": 0}

    d = parse_feed(url)
    if getattr(d, "bozo", 0) and not getattr(d, "entries", None):
        logd("FEED ERROR:", url, "| bozo:", getattr(d, "bozo", 0), "| error:", getattr(d, "bozo_exception", None))
        return stats

    source_name = source_name_from_feed(d, url)
    entries = list(d.entries or [])
    stats["total"] = len(entries)
    logd("feed parsed:", source_name, "| entries:", len(entries))

    try:
        entries.sort(key=lambda e: e.get("published_parsed") or e.get("updated_parsed") or 0, reverse=True)
    except Exception:
        pass

    for entry in entries[:MAX_ITEMS_PER_FEED]:
        uid = uid_from_entry(entry)
        title = clean_text(entry.get("title"))
        link = entry.get("link") or ""
        summary_html = entry.get("summary") or ""
        raw_summary = clean_text(summary_html)

        # Skip jos nähty
        if uid in seen:
            stats["skipped"] += 1
            logd("SKIP(seen):", source_name, "|", title)
            continue

        # Whitelist / Blocklist / Shorts
        skip, reason = should_skip_article(
            source_name, title, raw_summary, link,
            bl_global, bl_source, wl_global, wl_source, wl_sources
        )
        if skip:
            stats["skipped"] += 1
            logd("SKIP:", source_name, "| reason:", reason, "|", title)
            continue

        # Kuva + OG-fallback
        img = image_from_entry(entry)
        if not img or not raw_summary:
            og_img, og_desc = fetch_og_meta(link)
            if not img and og_img:
                img = og_img
            if not raw_summary and og_desc:
                raw_summary = og_desc

        # Arvin kommentti
        ai_comment = ai_make_comment(
            title=title,
            source=source_name,
            url=link,
            raw_summary=raw_summary,
            maxlen=COMMENT_MAXLEN
        )

        # Termien normalisointi (varmistuskerros)
        if ai_comment:
            ai_comment = normalize_terms(ai_comment)

        # Postaa
        try:
            logd("POST:", source_name, "|", title, "|", link)
            post_to_discord(
                title=title,
                url=link,
                source=source_name,
                raw_summary=raw_summary,
                image_url=img,
                ai_comment=ai_comment
            )
            stats["posted"] += 1
            seen.add(uid)
            time.sleep(POST_DELAY_SEC)
        except Exception as e:
            print(f"[WARN] Discord post failed for {link}: {e}")

    return stats

def main():
    # Lataa termit laiskasti, mutta varmista että _TERMS_RULES on olemassa alussa
    global _TERMS_RULES
    _TERMS_RULES = load_terms_csv()

    seen = load_seen()
    bl_global, bl_source = load_blocklist()
    wl_global, wl_source, wl_sources = load_whitelist()
    feeds = read_feeds()

    logd("FEEDS_FILE ->", str(FEEDS_FILE))
    for f in feeds:
        logd("  feed:", f)
    logd("blocklist global terms:", len(bl_global), "source terms:", len(bl_source))
    logd("whitelist global terms:", len(wl_global), "source terms:", len(wl_source), "allow_sources:", len(wl_sources))
    logd("terms rules:", len(_TERMS_RULES))

    total_posted = 0
    total_skipped = 0
    total_entries = 0

    for url in feeds:
        stats = process_feed(url, seen, bl_global, bl_source, wl_global, wl_source, wl_sources)
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
