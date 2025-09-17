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
