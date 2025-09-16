#!/usr/bin/env python3
import sys, re, requests
from urllib.parse import urlparse
from bs4 import BeautifulSoup

def fetch_text(url: str) -> str:
    r = requests.get(url, timeout=15, headers={"User-Agent":"Mozilla/5.0"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    # Poista nav/aside/script/style
    for t in soup(["script","style","nav","aside","footer","header"]):
        t.decompose()
    text = soup.get_text(separator=" ")
    text = re.sub(r"\s+", " ", text).strip()
    return text

def simple_keywords(text: str, top_k: int = 30):
    # hyvin kevyt, kieleen-agnostinen poiminta: frekvenssi + pituusfiltterit
    words = re.findall(r"[A-Za-zÅÄÖåäö0-9\-]{3,}", text)
    # alas raskaasta stoplistasta: lisää tänne omasi tarvittaessa
    stop = set("the and for with that this from have has are was were you your www com http https hän se ne olla kuin sekä koska mutta myös kun joka".split())
    freq = {}
    for w in words:
        lw = w.lower()
        if lw in stop or lw.isdigit():
            continue
        freq[lw] = freq.get(lw, 0) + 1
    # pisteytä esiintymistiheydellä
    ranked = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:top_k]
    return [w for w, _ in ranked]

def main():
    url = sys.argv[1]
    text = fetch_text(url)
    cands = simple_keywords(text, top_k=30)

    # Tulosta CI-lokiin ja kirjoita ehdotukset tiedostoon
    print("CANDIDATES:", ", ".join(cands))
    with open("blocklist_candidates.txt", "w", encoding="utf-8") as f:
        for w in cands:
            f.write(w + "\n")

    # Luo blokkilistaan ehdotus-merkinnöillä (helppo karsia PR:ssä)
    try:
        existing = open("blocklist.txt","r",encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        existing = []
    merged = existing + [f"# CANDIDATE {w}" for w in cands if w not in existing]
    with open("blocklist.txt","w",encoding="utf-8") as f:
        f.write("\n".join(sorted(set(merged))))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: suggest_blocklist.py <url>")
        sys.exit(1)
    main()
