#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Emoji Reactor (scheduled, stateless)
- Hakee 5–15 minuutin tuoreet viestit valituista kanavista
- Lisää reaktiot, jos viesti osuu triggeriin
- Idempotentti: duplikaatit sivuutetaan (Discord palauttaa 400, joka ohitetaan)
"""

import os
import re
from datetime import timedelta
import asyncio
import discord

# ---------- Asetukset ympäristömuuttujista ----------
# Kanavat pilkuilla eroteltuna, esim: "123,456"
CHANNEL_IDS = {
    int(x.strip())
    for x in os.getenv("EMOJI_CHANNEL_IDS", "").split(",")
    if x.strip().isdigit()
}
try:
    LOOKBACK_MINUTES = int(os.getenv("EMOJI_LOOKBACK_MINUTES") or 15)
except ValueError:
    LOOKBACK_MINUTES = 15

# ---------- Triggerit ----------
# Voit muokata tätä sanakirjaa – avain on regex (pieniksi muunnettu teksti),
# arvo on joko yksi emoji (str) tai lista emojeja.
TRIGGERS = {
    r"\bkiitos\b": ["🙏", "💙"],
    r"\bmitä mieltä\b": ["👍", "👎"],
    r"\bgg\b": "👍",
    r"\bhienoa\b": ["🎉", "🔥"],
    r"\bostolistalla\b": "🧺",
    # lisää omia…
}

# ---------- Discord-kytkentä ----------
intents = discord.Intents.default()
intents.message_content = True  # pakollinen: luetaan viestien sisältö
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    try:
        if not CHANNEL_IDS:
            print("[WARN] EMOJI_CHANNEL_IDS ei asetettu. Lopetetaan.")
            return
        cutoff = discord.utils.utcnow() - timedelta(minutes=LOOKBACK_MINUTES)
        print(f"[INFO] Käydään kanavat läpi, lookback {LOOKBACK_MINUTES} min, cutoff={cutoff}Z")

        for cid in CHANNEL_IDS:
            try:
                ch = await client.fetch_channel(cid)
            except Exception as e:
                print(f"[WARN] Kanavaa {cid} ei saatu: {e}")
                continue

            # Hae tuore historia (rajataan viim. 100 viestiin + cutoff suodatus)
            async for msg in ch.history(limit=100, oldest_first=False, after=cutoff):
                if msg.author.bot:
                    continue
                text = (msg.content or "").lower()

                for pattern, emojis in TRIGGERS.items():
                    if re.search(pattern, text):
                        if isinstance(emojis, str):
                            emojis = [emojis]
                        for e in emojis:
                            try:
                                await msg.add_reaction(e)
                            except discord.Forbidden:
                                print(f"[WARN] Ei lupaa reagoida kanavassa {cid}.")
                            except discord.HTTPException as he:
                                # 400 (duplikaatti tms.) → ohita
                                print(f"[DEBUG] HTTPException add_reaction: {he}")
                        break  # vain 1 triggeri / viesti
        print("[INFO] Valmis.")
    finally:
        await client.close()

def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("DISCORD_TOKEN puuttuu.")
    client.run(token)

if __name__ == "__main__":
    main()
