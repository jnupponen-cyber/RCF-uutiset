#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re, pathlib, sys
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# ----- Polut -----
BASE = pathlib.Path("rcf-discord-news")                 # <-- oikea kansio
BLOCKLIST = BASE / "blocklist.txt"
CANDIDATES = BASE / "blocklist_candidates.txt"
BASE.mkdir(parents=True, exist_ok=True)

# ----- Asetukset -----
TOP_K = 30
MIN_LEN = 3  # minimipituus sanalle
# Kevyt suomi+englanti stoplist (voit laajentaa)
STOPWORDS = {
    # fi
    "ja","ei","on","olen","olla","oli","ole","että","mutta","myös","kun","jos","tai","kuten",
    "se","ne","tämä","tuo","nämä","noin","joka","jotka","kuin","vain","koko","kai","kuten",
    "nyt","vielä","hyvin","yli","alla","päälle","vuoden","vuotta","vuosi","uusi","uus",
    # en
    "the","and","for","with","that","this","from","have","has","are","was","were","you","your",
    "a","an","of","to","in","on","by","it","as","is","be","or","at","we","our",
    # url-roskaa
    "http","https","www","com","fi","uk","de"
}

def fetch_text(url: str) -> str:
    """Hae sivu ja poimi varsinainen teksti."""
    headers = {"User-Agent": "Mozilla/5.0 (blocklist-suggester)"}
    r = requests.get(url, timeout=20, headers=headers)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    # Poista epäolennaiset osat
    for t in soup(["script", "style", "nav", "aside", "footer", "header", "noscript"]):
        t.decompose()
    text = soup.get_text(separator=" ")
    text = re.sub(r"\s+", " ", text).strip()
    return text

def to_keywords(text: str, top_k: int = TOP_K):
    # Poimi "sanat" (sallitut kirjaimet myös ääkköset ja numerot, väliviiva ok)
    words = re.findall(r"[A-Za-zÅÄÖåäö0-9\-]{%d,}" % MIN_LEN, text)
    freq = {}
    for w in words:
        lw = w.lower().strip("-")
        if not lw or lw in STOPWORDS:
            continue
        # suodata puhtaat numerot
        if lw.isdigit():
            continue
        # suodata domain-tyyppiset
        if "." in lw:
            continue
        freq[lw] = freq.get(lw, 0) + 1
    ranked = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:top_k]
    return [w for w, _ in ranked]

def read_existing(path: pathlib.Path):
    if not path.exists():
        return []
    lines = [ln.rstrip("\n") for ln in path.read_text(encoding="utf-8").splitlines()]
    # Pudota tyhjät ja placeholderit (# [NEW] tms.)
    cleaned = []
    for ln in lines:
        if not ln.strip():
            continue
        # hyväksy vain "pelkät sanat" tai ehdotukset muodossa "# CANDIDATE <sana>"
        if ln.startswith("#"):
            # jätetään muut kommentit ennalleen, mutta ei tyhjiä NEW-rivejä
            if ln.strip() in {"# [NEW]", "# [NEW] ", "# NEW"}:
                continue
        cleaned.append(ln)
    return cleaned

def main():
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print("Usage: suggest_blocklist.py <url>", file=sys.stderr)
        sys.exit(1)

    url = sys.argv[1].strip()
    # Varmuustarkistus URLille
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        print(f"Invalid URL: {url}", file=sys.stderr)
        sys.exit(2)

    text = fetch_text(url)
    cands = to_keywords(text, top_k=TOP_K)

    # Kirjoita erillinen ehdokaslista näkyviin (helpottaa debugia)
    if cands:
        CANDIDATES.write_text("\n".join(cands) + "\n", encoding="utf-8")
    else:
        CANDIDATES.write_text("(no candidates)\n", encoding="utf-8")

    existing = read_existing(BLOCKLIST)

    # Muodosta ehdotus-rivit: "# CANDIDATE <sana>" – ei tyhjiä!
    proposal_lines = [f"# CANDIDATE {w}" for w in cands if w]

    # Älä duplikoi: yhdistä ja deduplikoi järjestys säilyttäen
    seen = set()
    merged = []
    for ln in existing + proposal_lines:
        if ln not in seen:
            seen.add(ln)
            merged.append(ln)

    BLOCKLIST.write_text("\n".join(merged) + ("\n" if merged else ""), encoding="utf-8")
    print(f"Wrote {len(proposal_lines)} candidate(s) to {BLOCKLIST} and {CANDIDATES}")

if __name__ == "__main__":
    main()