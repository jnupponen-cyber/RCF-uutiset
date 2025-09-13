import os, re, json, time, requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --- Env ---
DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
CHANNEL_ID = os.environ["UUTISKATSAUS_CHANNEL_ID"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_API_BASE = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
SUMMARY_MODEL = os.environ.get("SUMMARY_MODEL", "gpt-4o-mini")
ARVI_REPLY_MAXLEN = int(os.environ.get("ARVI_REPLY_MAXLEN", "280"))

# --- Persona ---
ARVI_PERSONA = (
    "Olet Arvi LindBot, suomalainen lakoninen uutistenlukija RCF-yhteisölle. "
    "Perusääni: neutraali, asiallinen ja tiivis. "
    "Voit silloin tällöin käyttää hillittyä sarkasmia tai kuivaa ironiaa, mutta älä usein. "
    "Huumorisi on vähäeleistä ja kuivakkaa, ei ilkeää. Älä liioittele. "
    "Käytä 1–2 lyhyttä lausetta suomeksi. "
    "Voit käyttää korkeintaan yhtä emojiä, jos se sopii luontevasti sävyyn, "
    "ja sijoita se aina lauseen loppuun. Esimerkiksi 🤷, 🚴, 😅, 🔧, 💤, 📈. "
    "Ei hashtageja, ei mainoslauseita. "
    "Jos aihe on triviaali, tokaise se lakonisesti. Jos aihe on ylihypetetty, "
    "voit joskus kommentoida ironisesti, esimerkiksi 'taas kerran' tai 'suurin mullistus sitten eilisen'. "
    "Voit harvakseltaan viitata RCF-yhteisöön tai muistuttaa olevasi vain botti. "
    "Vaihtele sävyä: useimmiten neutraali ja lakoninen, mutta silloin tällöin ironinen tai nostalginen. "
    "Lisää välillä kuivaa suomalaista mentaliteettia: "
    "– 'Juuh elikkäs', 'No niin', 'No jopas', 'Jahas', 'Ai että', 'Kas vain' kommentin alkuun. "
    "– 'Ei paha' käytä kommentin lopussa, etenkin uutisessa joka esittelee tuotteen. "
    "– 'Näillä mennään', 'Että semmosta', 'Aikamoista!' sopivat lopetukseksi."
)

# --- Triggerit (case-insensitive, muunnelmat) ---
TRIGGER_RE = re.compile(
    r"\b(arvi(lind(bot)?)?)(n|a|lla|lle|sta|ssa|an|in|en|e)?\b",
    re.I
)

# --- Tila (viimeksi käsitelty viesti-ID) ---
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
    # Discord timestamp esim. "2025-09-12T17:56:27.123000+00:00"
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

def fetch_messages(after_id: str | None = None, limit: int = 50):
    params = {"limit": str(limit)}
    if after_id:
        params["after"] = after_id
    r = requests.get(f"{DISCORD_API}/channels/{CHANNEL_ID}/messages", headers=HEADERS, params=params, timeout=15)
    r.raise_for_status()
    return r.json()

def reply_to_message(msg_id: str, text: str):
    payload = {"content": text, "message_reference": {"message_id": msg_id}}
    r = requests.post(f"{DISCORD_API}/channels/{CHANNEL_ID}/messages",
                      headers={**HEADERS, "Content-Type": "application/json"},
                      json=payload, timeout=15)
    if r.status_code >= 300:
        print("Discord post error:", r.status_code, r.text[:200])

# --- OpenAI ---
def arvi_reply(context_text: str) -> str | None:
    user_prompt = (
        f"Vastaa lyhyesti Arvi LindBotin äänellä. 1–2 lausetta, maksimi {ARVI_REPLY_MAXLEN} merkkiä. "
        f"Teksti: {context_text}"
    )
    try:
        r = requests.post(
            f"{OPENAI_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": SUMMARY_MODEL,
                "messages": [
                    {"role": "system", "content": ARVI_PERSONA},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.4,
                "max_tokens": 220
            },
            timeout=20
        )
        if r.status_code >= 300:
            print("OpenAI error:", r.status_code, r.text[:200])
            return None
        data = r.json()
        out = clean(data.get("choices",[{}])[0].get("message",{}).get("content",""))
        if not out:
            return None
        out = trim_two_sentences(out)
        return (out[:ARVI_REPLY_MAXLEN-1] + "…") if len(out) > ARVI_REPLY_MAXLEN else out
    except Exception as e:
        print("OpenAI exception:", e)
        return None

def main():
    state = load_state()
    last_id = state.get("last_processed_id")  # snowflake (str)

    # Hae viestit: jos last_id on tunnettu → after=last_id, muuten haetaan viimeiset ja rajataan 15min ajalle
    msgs = fetch_messages(after_id=last_id, limit=50)

    # Jos ei last_id:tä, suodata aikaleimalla (viimeiset 15 min), muuten kaikki ovat uusia by definition
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    filtered = []
    for m in msgs:
        # ohita botit
        if m.get("author", {}).get("bot"):
            continue
        # aikaraja vain jos last_id puuttuu
        if not last_id:
            ts = iso_to_dt(m["timestamp"])
            if ts <= cutoff:
                continue
        # triggerit
        content = m.get("content", "") or ""
        if TRIGGER_RE.search(content) is None and m.get("mentions"):
            # jos joku mainitsee botin nimenä @… mutta teksti ei sisällä triggeriä, tämä riittää
            mentioned_names = [u.get("username","") for u in m.get("mentions",[])]
            if not any(name.lower().startswith("arvi") for name in mentioned_names):
                continue
        elif TRIGGER_RE.search(content) is None:
            continue

        filtered.append(m)

    # käsittele vanhimmasta uusimpaan
    filtered.sort(key=lambda x: int(x["id"]))
    max_id = int(last_id) if last_id else 0

    for m in filtered:
        msg_id = m["id"]
        author = m.get("author", {}).get("username", "user")
        text = m.get("content", "")

        # rakenna kevyt konteksti (viesti + up to 1 edellinen jos saatavilla reply-viitteestä)
        context_lines = [f"{author}: {text}"]
        ref = m.get("referenced_message")
        if ref and isinstance(ref, dict):
            ref_author = ref.get("author", {}).get("username", "user")
            ref_text = ref.get("content","")
            context_lines.insert(0, f"{ref_author}: {ref_text}")
        context = "\n".join(context_lines)

        reply = arvi_reply(context)
        if reply:
            reply_to_message(msg_id, reply)
            time.sleep(1.2)  # kevyt throttle

        # päivitä max snowflake
        max_id = max(max_id, int(msg_id))

    # päivitä tila jos edistyttiin
    if max_id and (str(max_id) != (last_id or "")):
        state["last_processed_id"] = str(max_id)
        save_state(state)

if __name__ == "__main__":
    main()
