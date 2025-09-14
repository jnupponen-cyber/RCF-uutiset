import os, re, json, time, requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --- Env ---
DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_API_BASE = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
SUMMARY_MODEL = os.environ.get("SUMMARY_MODEL", "gpt-4o-mini")
ARVI_REPLY_MAXLEN = int(os.environ.get("ARVI_REPLY_MAXLEN", "280"))

# Kanavat: käytä joko CHANNEL_IDS (pilkuin eroteltu) tai fallback UUTISKATSAUS_CHANNEL_ID
CHANNEL_IDS_ENV = os.environ.get("CHANNEL_IDS", "").strip()
if CHANNEL_IDS_ENV:
    CHANNEL_IDS = [c.strip() for c in CHANNEL_IDS_ENV.split(",") if c.strip()]
else:
    CHANNEL_IDS = [os.environ["UUTISKATSAUS_CHANNEL_ID"]]

# --- Persona ---
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

# --- Triggerit (case-insensitive, taivutusmuodot) ---
TRIGGER_TERMS = [
    r"arvi",
    r"arvi\s*lind",
    r"arvi\s*bot",
    r"arvi\s*lind\s*bot",
    r"lindbot",
    r"uutiskatsaus",
    r"uutiskanava",
    r"uutisbot",
    r"uutisbotti",
]

# Laajenna kaikkiin suomen sijapäätteisiin
SUFFIX = r"(?:n|a|lla|lle|lta|sta|ssa|aan|in|en|e)?"
TRIGGER_RE = re.compile(
    r"\b(?:" + "|".join(f"(?:{t}){SUFFIX}" for t in TRIGGER_TERMS) + r")\b",
    re.I
)

# --- Tila ---
STATE_PATH = Path("arvi_state.json")

def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_state(state: dict):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

# --- Apurit ---
def iso_to_dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso)

def clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def trim_two_sentences(s: str) -> str:
    parts = re.split(r'(?<=[\.\!\?])\s+', s.strip())
    return " ".join([p for p in parts if p][:2]).strip() or s

# --- Discord REST ---
DISCORD_API = "https://discord.com/api/v10"
HEADERS = {"Authorization": f"Bot {DISCORD_TOKEN}"}

def fetch_messages(channel_id: str, after_id: str | None = None, limit: int = 50):
    params = {"limit": str(limit)}
    if after_id:
        params["after"] = after_id
    r = requests.get(f"{DISCORD_API}/channels/{channel_id}/messages", headers=HEADERS, params=params, timeout=15)
    r.raise_for_status()
    return r.json()

def reply_to_message(channel_id: str, msg_id: str, text: str):
    payload = {"content": text, "message_reference": {"message_id": msg_id}}
    r = requests.post(f"{DISCORD_API}/channels/{channel_id}/messages",
                      headers={**HEADERS, "Content-Type": "application/json"},
                      json=payload, timeout=15)
    if r.status_code >= 300:
        print("Discord post error:", r.status_code, r.text[:200])

# --- OpenAI ---
def call_openai(messages, temperature=0.5, max_tokens=400, retries=2):
    backoff = 1.5
    for attempt in range(retries + 1):
        try:
            r = requests.post(
                f"{OPENAI_API_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
                json={"model": SUMMARY_MODEL, "messages": messages,
                      "temperature": temperature, "max_tokens": max_tokens},
                timeout=20
            )
            if r.status_code in (429, 500, 502, 503):
                time.sleep(backoff)
                backoff *= 2
                continue
            if r.status_code >= 300:
                print("OpenAI error:", r.status_code, r.text[:200])
                return None
            data = r.json()
            return clean(data.get("choices", [{}])[0].get("message", {}).get("content", ""))
        except Exception as e:
            print("OpenAI exception:", e)
            time.sleep(backoff)
            backoff *= 2
    return None

def arvi_reply(context_text: str) -> str | None:
    user_prompt = (
        f"Vastaa Arvi LindBotin äänellä. Pituus enintään {ARVI_REPLY_MAXLEN} merkkiä. "
        f"Teksti: {context_text}"
    )
    out = call_openai(
        messages=[
            {"role": "system", "content": ARVI_PERSONA},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.5, max_tokens=400
    )
    if not out:
        return None
    return trim_two_sentences(out)[:ARVI_REPLY_MAXLEN]

def should_trigger_on_message(msg: dict) -> bool:
    content = msg.get("content", "") or ""
    if TRIGGER_RE.search(content):
        return True
    mentions = msg.get("mentions", []) or []
    if any((u.get("username", "") or "").lower().startswith("arvi") for u in mentions):
        return True
    return False

# --- Main ---
def main():
    state = load_state()
    for channel_id in CHANNEL_IDS:
        ch_state = state.get(channel_id, {})
        last_id = ch_state.get("last_processed_id")
        last_reply = ch_state.get("last_reply_text", "")

        try:
            msgs = fetch_messages(channel_id, after_id=last_id, limit=50)
        except requests.HTTPError as e:
            print(f"[WARN] fetch_messages failed for {channel_id} -> {e}")
            continue

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
        filtered = []
        for m in msgs:
            if m.get("author", {}).get("bot"):
                continue
            if not last_id:
                ts = iso_to_dt(m["timestamp"])
                if ts <= cutoff:
                    continue
            if not should_trigger_on_message(m):
                continue
            filtered.append(m)

        filtered.sort(key=lambda x: int(x["id"]))
        max_id = int(last_id) if last_id else 0
        new_last_reply = last_reply

        for m in filtered:
            msg_id = m["id"]
            author = m.get("author", {}).get("username", "user")
            text = m.get("content", "")
            context = f"{author}: {text}"

            reply = arvi_reply(context)

            if reply and reply == last_reply:
                alt = arvi_reply(context)
                if alt and alt != last_reply:
                    reply = alt
                else:
                    reply = None

            if reply:
                reply_to_message(channel_id, msg_id, reply)
                new_last_reply = reply
                time.sleep(1.0)

            max_id = max(max_id, int(msg_id))

        if max_id and (str(max_id) != (last_id or "")):
            state[channel_id] = {
                "last_processed_id": str(max_id),
                "last_reply_text": new_last_reply
            }

    save_state(state)

if __name__ == "__main__":
    main()