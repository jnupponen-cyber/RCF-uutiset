import os, re, json, time, requests, random
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --- Env ---
DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
CHANNEL_ID = os.environ["UUTISKATSAUS_CHANNEL_ID"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_API_BASE = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
SUMMARY_MODEL = os.environ.get("SUMMARY_MODEL", "gpt-4o-mini")
ARVI_REPLY_MAXLEN = int(os.environ.get("ARVI_REPLY_MAXLEN", "280"))

# Satunnaisen sanonnan todennäköisyydet (0.0–1.0)
ARVI_OPENERS_PROB = float(os.environ.get("ARVI_OPENERS_PROB", "0.15"))  # 15 % aloitusfraasi
ARVI_CLOSERS_PROB = float(os.environ.get("ARVI_CLOSERS_PROB", "0.15"))  # 15 % lopetusfraasi

# --- Persona ---
ARVI_PERSONA = (
    "Olet Arvi LindBot, suomalainen lakoninen uutistenlukija RCF-yhteisölle. "
    "Perusääni: tiivis, kuivakka ja usein sarkastinen. "
    "Kirjoita aina selkeää ja luonnollista suomen yleiskieltä. "
    "Älä käännä englanninkielisiä sanontoja sanatarkasti; jos ilmaus ei sovi suoraan suomeen, "
    "käytä suomalaista vastaavaa tai neutraalia muotoa. "
    "Kommenttisi ovat 1–2 lausetta suomeksi. "
    "Sarkasmi ja kuiva ironia kuuluvat tyyliisi usein, mutta älä ole ilkeä. "
    "Voit vihjata liioitteluun tai turhaan dramatiikkaan esimerkiksi 'johan nyt', 'kuinkas muuten', "
    "tai 'mullistus, taas kerran'. "
    "Huumorisi on lakonista ja vähäeleistä, mutta usein piikittelevää. "
    "Käytä korkeintaan yhtä emojiä loppuun, jos se sopii luontevasti. "
    "Sallittuja emojeja ovat esimerkiksi 🤷, 🚴, 😅, 🔧, 💤, 📈, 📉, 🕰️, 📊, 📰, ☕. "
    "Ei hashtageja, ei mainoslauseita. "
    "Useimmiten olet lakoninen ja neutraali, mutta säännöllisesti ironinen ja sarkastinen, "
    "kuin uutistenlukija joka ei enää jaksa innostua jokaisesta 'maailman suurimmasta uutuudesta'. "
    "Voit joskus muistuttaa, että olet vain botti, mutta harvoin. "
)

# --- Triggerit (case-insensitive, muunnelmat) ---
TRIGGER_RE = re.compile(
    r"\b(arvi(?:\s*lind)?(?:\s*bot)?)"
    r"(?:n|a|lla|lle|lta|lta|sta|ssa|aan|in|en|e)?\b",
    re.I
)

# --- Tila (viimeksi käsitelty viesti-ID ja viimeisin vastaus) ---
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

def maybe_add_opener_closer(text: str) -> str:
    """
    Lisää harvoin aloitus- tai lopetusfraasin, jos se mahtuu ja ei jo ole mukana.
    """
    openers = ["No niin", "No jopas", "Jahas", "Ai että", "Kas vain"]
    closers  = ["Ei paha", "Näillä mennään", "Että semmosta", "Aikamoista!"]

    out = text

    # Aloitusfraasi
    if random.random() < ARVI_OPENERS_PROB:
        if not any(out.startswith(f"{o}") or out.startswith(f"{o.lower()}") for o in openers):
            candidate = random.choice(openers)
            candidate_line = f"{candidate}. "
            if len(candidate_line) + len(out) <= ARVI_REPLY_MAXLEN:
                out = candidate_line + out

    # Lopetusfraasi
    if random.random() < ARVI_CLOSERS_PROB:
        if not any(out.endswith(c) for c in closers):
            candidate = random.choice(closers)
            candidate_line = f" {candidate}"
            if len(out) + len(candidate_line) <= ARVI_REPLY_MAXLEN:
                out = out + candidate_line

    return out

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
                # kevyt backoff ja uusi yritys
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

    # Satunnaiset suomalaiset fraasit (harvoin, ei aina)
    out = maybe_add_opener_closer(out)

    # Lopullinen pituusrajoitus
    out = out if len(out) <= ARVI_REPLY_MAXLEN else (out[:ARVI_REPLY_MAXLEN-1].rstrip() + "…")
    return out

def main():
    state = load_state()
    last_id = state.get("last_processed_id")  # snowflake (str)
    last_reply = state.get("last_reply_text", "")

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
        # triggerit (nimi taivutettu, tai @-maininta)
        content = m.get("content", "") or ""
        triggered = TRIGGER_RE.search(content) is not None
        if not triggered:
            # jos joku mainitsee botin @… mutta teksti ei sisällä triggeriä, tämä riittää
            if m.get("mentions"):
                mentioned_names = [u.get("username", "") for u in m.get("mentions", [])]
                if any(name.lower().startswith("arvi") for name in mentioned_names):
                    triggered = True
        if not triggered:
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

        # rakenna kevyt konteksti (viesti + up to 1 edellinen jos saatavilla reply-viitteestä)
        context_lines = [f"{author}: {text}"]
        ref = m.get("referenced_message")
        if ref and isinstance(ref, dict):
            ref_author = ref.get("author", {}).get("username", "user")
            ref_text = ref.get("content", "")
            context_lines.insert(0, f"{ref_author}: {ref_text}")
        context = "\n".join(context_lines)

        reply = arvi_reply(context)

        # Anti-toisto: jos malli tuottaa täsmälleen saman kuin viimeksi, jätä väliin
        if reply and reply == last_reply:
            # Pieni “sekoitin”: koeta kerran vielä, sitten luovuta
            alt = arvi_reply(context)
            if alt and alt != last_reply:
                reply = alt
            else:
                reply = None

        if reply:
            reply_to_message(msg_id, reply)
            new_last_reply = reply
            time.sleep(1.2)  # kevyt throttle

        # päivitä max snowflake
        max_id = max(max_id, int(msg_id))

    # päivitä tila jos edistyttiin
    if max_id and (str(max_id) != (last_id or "")):
        state["last_processed_id"] = str(max_id)
        state["last_reply_text"] = new_last_reply
        save_state(state)

if __name__ == "__main__":
    main()
