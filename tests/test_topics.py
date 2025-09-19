import sys
from pathlib import Path

# Lisää uutisskriptin hakemisto polulle, jotta voimme tuoda sen suoraan testeissä.
sys.path.append(str(Path(__file__).resolve().parents[1] / "rcf-discord-news"))

import fetch_and_post as fp


def test_make_topic_key_merges_similar_titles():
    title_a = "Jonas Vingegaard wins stage 1 of Tour de France"
    title_b = "Stage 1 at Tour de France won by Jonas Vingegaard"
    key_a = fp.make_topic_key(title_a)
    key_b = fp.make_topic_key(title_b)
    assert key_a == key_b


def test_make_topic_key_filters_noise():
    title = "Latest cycling news podcast: Preview of the Giro"
    key = fp.make_topic_key(title)
    assert "latest" not in key
    assert "podcast" not in key
    assert "cycling" not in key
