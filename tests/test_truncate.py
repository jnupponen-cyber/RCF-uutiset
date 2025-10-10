import sys
from pathlib import Path

# Lisää rcf-discord-news polkuun, jotta moduuli löytyy
sys.path.append(str(Path(__file__).resolve().parents[1] / "rcf-discord-news"))

import fetch_and_post as fp


def test_truncate_prefers_word_boundary():
    text = "Tämä on pitkä suomenkielinen lause jonka ei pitäisi katketa kesken sanan."
    result = fp.truncate(text, 40)
    assert result.endswith("…")
    assert " kes" not in result  # sana ei katkea


def test_truncate_keeps_sentence_if_possible():
    text = "Ensimmäinen lause. Toinen lause jatkuu vielä pidempään ja pidempään."
    result = fp.truncate(text, 50)
    # Pitkä raja -> ensimmäinen lause säilyy kokonaisena
    assert result.startswith("Ensimmäinen lause.")
    assert result.endswith("…")


def test_truncate_handles_short_strings():
    assert fp.truncate("Lyhyt", 20) == "Lyhyt"
