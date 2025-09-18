# RCF Discord uutisbot (Zwift & MyWhoosh)

Kevyt automaatio, joka hakee RSS-syötteistä tuoreita artikkeleita ja postaa ne RCF:n Discord-kanavaan **webhookilla**.

## Mitä tämä tekee?
- Lukee lähteet tiedostosta **`feeds.txt`**
- Estää duplikaatit **`seen.json`** -tiedoston avulla
- Muotoilee viestin: otsikko + lähde + linkki (+ tiivistelmä ja kuva, jos saatavilla)
- Postaa määritettyyn Discord-kanavaan 30 min välein (GitHub Actions -ajastus)

## Pikaohje (Jari / RCF)
1. **Luo Discord-webhook**
   - Server Settings → Integrations → Webhooks → *New Webhook*
   - Valitse kanava, esim. `#zwift-uutiset`
   - Kopioi **Webhook URL** talteen

2. **Tee uusi GitHub-repo tästä paketista**
   - Luo tyhjä repo GitHubiin (public tai private)
   - Lataa tämän repo-paketin sisältö (tai käytä "Upload files")

3. **Aseta salaisuudet GitHubissa**
   - Repo → *Settings* → *Secrets and variables* → *Actions* → *New repository secret*
   - Pakollinen: `DISCORD_WEBHOOK_URL` → (liitä uutiskanavan webhook-osoite)
   - Valinnainen tarkistuskanavaa varten: `DISCORD_REVIEW_WEBHOOK_URL` → (liitä tarkistuskanavan webhook)

4. **Muokkaa lähteitä tarvittaessa**
   - Avaa `feeds.txt` ja lisää/poista RSS-osoitteita.
   - Oletuksena mukana:
     - `https://zwiftinsider.com/feed/`
     - `https://www.zwift.com/news/rss`
     - `https://www.mywhoosh.com/news/feed/`

5. **Ota Actions käyttöön**
   - Repo → *Actions* → salli workflowt, jos GitHub kysyy
   - Voit myös ajaa käsin: *Actions* → *Run workflow*

6. **Valmista!**
   - Botin pitäisi postata uudet jutut valittuun kanavaan.
   - Duplikaatit vältetään `seen.json`-tiedoston avulla, joka **commitoidaan** automaattisesti repoosi.

### Tarkistuskanava (valinnainen)

Jos haluat, että uutiset menevät ensin erilliseen tarkistuskanavaan:

1. Luo Discordissa toinen webhook haluamaasi tarkistuskanavaan.
2. Tallenna osoite secretiksi nimellä `DISCORD_REVIEW_WEBHOOK_URL`.
3. Aseta workflowlle (tai paikalliseen ajoon) ympäristömuuttuja `USE_REVIEW_CHANNEL=1`
   (tai vaihtoehtoisesti `REVIEW_CHANNEL=1`).

Kun haluat palata suoraan julkaisemiseen `#uutiskatsaus`-kanavaan, poista tai aseta `USE_REVIEW_CHANNEL=0` (tai `REVIEW_CHANNEL=0`). Tällöin botti käyttää taas `DISCORD_WEBHOOK_URL`-osoitetta ilman muita muutoksia.

## Muuta hyödyllistä
- Ajastus on `*/30 * * * *` → 30 min välein (GitHub käyttää UTC-aikaa).
- Tiivistelmä (summary) ja kuva poimitaan syötteestä, jos saatavilla.
- **Vinkki:** jos haluat eri kanaville eri lähteet (esim. Zwift vs. MyWhoosh), tee kaksi workflowta ja kaksi salaisuutta (`DISCORD_WEBHOOK_URL_ZWIFT`, `DISCORD_WEBHOOK_URL_MYW`), sekä kaksi feeds-tiedostoa.

## Paikallinen testaus (valinnainen)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/...."
python fetch_and_post.py
```

## Turvallisuus ja käyttöehdot
- Käytä vain lähteitä, joiden sisältöä saat jakaa (RSS yleensä ok).
- Vältä raskasta skräpäystä, jos RSS puuttuu.
- Poista lähde `feeds.txt`:stä, jos se aiheuttaa ongelmia.

Tsemppiä ja hyviä uutisia kanavaan! 🚴‍♂️
