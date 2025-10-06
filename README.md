# Arvi LindBot työkalut

Tämä repo sisältää Arvi LindBotin automaatiot. Alla lyhyt ohje uuden
manuaalisen julkaisuskriptin käyttöön.

## Manuaalinen Discord-postaus

`scripts/manual_post.py` -skriptillä voi lähettää valmiiksi kirjoitetun viestin
ja valinnaisen kuvan mille tahansa Discord-kanavalle, jossa Arvilla on
kirjoitusoikeus.

1. Aseta ympäristömuuttuja `DISCORD_BOT_TOKEN` tuttuun tapaan.
2. Aja skripti esimerkiksi:

   ```bash
   python scripts/manual_post.py --channel 123456789012345678 \
       --message "Tässä päivän tiedote" --image kuva.png
   ```

   Vaihtoehtoisesti viestin voi lukea tiedostosta `--message-file`-optiolla tai
   putkittaa skriptille stdin:in kautta. Kuvat voivat olla paikallisia
   tiedostoja (`--image`), verkosta ladattavia (`--image-url`) tai suoraan
   embediin linkitettyjä (`--embed-url`).

3. Skripti tulostaa jokaisen lähetetyn viestin Discord-ID:n muodossa
   `Posted: 123456789012345678`. Pitkät viestit pilkotaan automaattisesti
   useampaan 2000 merkin palaseen.

### Ajo GitHub Actionsista

Repo sisältää työnkulun **Manual Discord Post**, joka löytyy GitHubin Actions-
välilehdeltä. `workflow_dispatch`-toiminto kysyy kanavan ID:n ja halutut
valinnaiset parametrit, minkä jälkeen työ kutsuu `scripts/manual_post.py`-
skriptiä. Työ tarvitsee salaisuuden `DISCORD_BOT_TOKEN` yhtä lailla kuin
paikallisesti ajettuna.

## Tarkistuskanavan viestien hyväksyntä

Ajettu GitHub Actions -työ **RCF Zwift & MyWhoosh uutiset** käyttää oletuksena
ympäristömuuttujaa `USE_REVIEW_CHANNEL=1`, joten salaisuuksien tulee sisältää sekä
`DISCORD_REVIEW_WEBHOOK_URL` että `DISCORD_WEBHOOK_URL`. Näin uusien kanavien käyttöönotto
onnistuu vaihtamalla molemmat webhook-osoitteet. Kun `rcf-discord-news/fetch_and_post.py`
ajetaan ympäristömuuttujalla
`USE_REVIEW_CHANNEL=1` (tai yhteensopivuuden vuoksi `REVIEW_CHANNEL=1`), kaikki uutiset
lähetetään ensin Discordin
tarkistuskanavaan. Jokainen viesti sisältää `UID`-kentän, jonka arvo vastaa
`seen.json`-tiedostoon tallennettua hashia. Samalla `pending_posts.json`
-tiedostoon tallennetaan otsikko, lähde, linkki, kuva ja Arvin kommentti
hyväksyntää odottaville uutisille.

Hyväksyntä tehdään GitHub Actionsissa työnkululla **Promote pending Discord
post**:

1. Avaa reposta Actions-välilehti ja valitse vasemmalta *Promote pending
   Discord post*.
2. Klikkaa *Run workflow* ja syötä yksi tai useampi `UID` tarkistuskanavan
   viestistä kopioituna (enintään 10 kerrallaan). Voit erotella UID:t välilyönnein,
   pilkuin tai rivinvaihdoilla.
3. Käynnistä ajo. Työnkulku lukee `pending_posts.json`-tiedostosta vastaavat
   merkinnät ja lähettää ne varsinaiseen `#uutiskatsaus`-kanavaan käyttäen samaa
   muotoilua kuin alkuperäinen skripti. Onnistuneen ajon jälkeen merkinnät
   poistuvat `pending_posts.json`-tiedostosta.

Työnkulku tarvitsee salaisuudet `DISCORD_WEBHOOK_URL`,
`DISCORD_REVIEW_WEBHOOK_URL` ja `DISCORD_BOT_TOKEN`. Sama skripti on ajettavissa
myös paikallisesti komennolla `python scripts/promote_pending.py <UID> [<UID> ...]`,
kun tarvittavat ympäristömuuttujat on asetettu. UID:t voi antaa erillisinä
argumentteina tai esimerkiksi merkkijonona `"UID1, UID2"`.
