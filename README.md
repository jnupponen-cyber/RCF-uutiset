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

   Viestin voi antaa myös tiedostosta `--message-file polku.txt` tai putkittaa
   sen skriptille standard inputin kautta.

3. Onnistunut ajo tulostaa vahvistuksen `✅ Viesti lähetetty onnistuneesti.`

Discord rajoittaa viestisisällön 2000 merkkiin ja hyväksyy vain yhden liitetyn
kuvan tämän skriptin kautta.
