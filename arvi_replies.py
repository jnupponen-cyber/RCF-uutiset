import os, re, json, time, requests, random
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

# Custom-emoji nimi (ilman kulmasulkeita), esim. :arvi:
ARVI_EMOJI_NAME = (os.environ.get("ARVI_EMOJI_NAME", "arvi") or "arvi").strip().lower()

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

# --- Triggerit (case-insensitive, muunnelmat) ---
TRIGGER_RE = re.compile(
    r"\b(arvi(?:\s*lind)?(?:\s*bot)?)"
    r"(?:n|a|lla|lle|lta|sta|ssa|aan|in|en|e)?\b",
    re.I
)

# :arvi: sisällössä – tunnista sekä :arvi: että <:arvi:1234567890>
def build_arvi_emoji_re(name: str) -> re.Pattern:
    safe = re.escape(name)
    return re.compile(rf"(?:<:{safe}:\d+>|:{safe}:)", re.I)

ARVI_EMOJI_RE = build_arvi_emoji_re(ARVI_EMOJI_NAME)

# --- Tila (per kanava: viimeksi käsitelty viesti-ID ja viimeisin vastaus) ---
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
    short = " ".join([p for p in parts if p][:2]).strip()
    return short or s

# --- Discord REST ---
DISCORD_API = "https://discord.com/api/v10"
HEADERS = {"Authorization": f"Bot {DISCORD_TOKEN}"}

def get_bot_user_id() -> str | None:
    # Käytä ARVI_USER_ID env jos annettu; muuten hae /users/@me
    env_id = (os.environ.get("ARVI_USER_ID") or "").strip()
    if env_id:
        return env_id
    try:
        r = requests.get(f"{DISCORD_API}/users/@me", headers=HEADERS, timeout=10)
        r.raise_for_status()
        return r.json().get("id")
    except Exception as e:
        print("WARN: could not get bot user id:", e)
        return None

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
def call_openai(messages, temperature=0.4, max_tokens=220, retries=2):
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
            if r.status_code == 429 or 500 <= r.status_code < 600:
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
        f"Vastaa lyhyesti Arvi LindBotin äänellä. 1–2 lausetta, maksimi {ARVI_REPLY_MAXLEN} merkkiä. "
        f"Teksti: {context_text}"
    )
    out = call_openai(
        messages=[
            {"role": "system", "content": ARVI_PERSONA},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.4, max_tokens=220
    )
    if not out:
        return None
    out = trim_two_sentences(out)
    out = out if len(out) <= ARVI_REPLY_MAXLEN else (out[:ARVI_REPLY_MAXLEN-1].rstrip() + "…")
    return out

# --- Triggerit ---
def is_reply_to_arvi(msg: dict, bot_user_id: str | None) -> bool:
    """
    True jos viesti on reply JA referenced_message.author.id == bot_user_id.
    """
    if not bot_user_id:
        return False
    ref = msg.get("referenced_message")
    if not ref or not isinstance(ref, dict):
        return False
    ref_author = (ref.get("author") or {}).get("id")
    return ref_author == bot_user_id

def should_trigger_on_message(msg: dict, bot_user_id: str | None) -> bool:
    """
    True, jos:
      - viesti on reply Arvin viestiin, TAI
      - sisältö sisältää Arvi-nimen muunnelmineen, @-maininnan, tai :arvi: -emojin.
    """
    # 1) Vastataanko Arvin viestiin?
    if is_reply_to_arvi(msg, bot_user_id):
        return True

    content = msg.get("content", "") or ""

    # 2) Tekstihaku nimestä
    if TRIGGER_RE.search(content):
        return True

    # 3) @-maininnat: jos joku @-mainitsee botin, username alkaa “Arvi”
    mentions = msg.get("mentions", []) or []
    if any((u.get("username", "") or "").lower().startswith("arvi") for u in mentions):
        return True

    # 4) :arvi: emoji sisällössä (tai <:arvi:12345>)
    if ARVI_EMOJI_RE.search(content):
        return True

    return False

def main():
    state = load_state()  # {channel_id: {"last_processed_id": "...", "last_reply_text": "..."}}
    bot_user_id = get_bot_user_id()

    # käsitellään kanavat yksi kerrallaan
    for channel_id in CHANNEL_IDS:
        ch_state = state.get(channel_id, {})
        last_id = ch_state.get("last_processed_id")
        last_reply = ch_state.get("last_reply_text", "")

        # Hae viestit
        try:
            msgs = fetch_messages(channel_id, after_id=last_id, limit=50)
        except requests.HTTPError as e:
            print(f"[WARN] fetch_messages 403/404? channel={channel_id} -> {e}")
            continue

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
        filtered = []
        for m in msgs:
            # ohita botit & Arvin omat viestit
            if m.get("author", {}).get("bot"):
                continue
            if bot_user_id and m.get("author", {}).get("id") == bot_user_id:
                continue

            # aikaraja vain jos last_id puuttuu
            if not last_id:
                ts = iso_to_dt(m["timestamp"])
                if ts <= cutoff:
                    continue

            # triggerit
            if not should_trigger_on_message(m, bot_user_id):
                continue
            filtered.append(m)

        # käsittele vanhimmasta uusimpaan
        filtered.sort(key=lambda x: int(x["id"]))
        max_id = int(last_id) if last_id else 0
        new_last_reply = last_reply

        for m in filtered:
            msg_id = m["id"]
            author = m.get("author", {}).get("username", "user")
            text = m.get("content", "")

            # kevyt konteksti (lisää myös reply-viitteen teksti, jos saatavilla)
            context_lines = []
            ref = m.get("referenced_message")
            if ref and isinstance(ref, dict):
                ref_author = ref.get("author", {}).get("username", "user")
                ref_text = ref.get("content", "")
                context_lines.append(f"{ref_author}: {ref_text}")
            context_lines.append(f"{author}: {text}")
            context = "\n".join(context_lines)

            reply = arvi_reply(context)

            # Anti-toisto
            if reply and reply == last_reply:
                alt = arvi_reply(context)
                if alt and alt != last_reply:
                    reply = alt
                else:
                    reply = None

            if reply:
                reply_to_message(channel_id, msg_id, reply)
                new_last_reply = reply
                time.sleep(1.2)  # kevyt throttle

            max_id = max(max_id, int(msg_id))

        # päivitä tila
        if max_id and (str(max_id) != (last_id or "")):
            state[channel_id] = {
                "last_processed_id": str(max_id),
                "last_reply_text": new_last_reply
            }

    save_state(state)

if __name__ == "__main__":
    main()