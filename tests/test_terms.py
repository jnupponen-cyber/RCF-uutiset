import sys
from pathlib import Path

# Ensure the rcf-discord-news directory is on sys.path
sys.path.append(str(Path(__file__).resolve().parents[1] / "rcf-discord-news"))

import fetch_and_post as fp


def test_normalize_terms_case_and_boundaries(tmp_path):
    csv = tmp_path / "terms.csv"
    csv.write_text("foo;bar;0\ntest;ok;1\n", encoding="utf-8")
    rules = fp.load_terms_csv(csv)
    fp._TERMS_RULES = rules
    text = "foo Foo FOO test contest test"
    assert fp.normalize_terms(text) == "bar Bar BAR ok contest ok"


def test_normalize_terms_fallback(tmp_path, monkeypatch):
    missing = tmp_path / "missing.csv"
    rules = fp.load_terms_csv(missing)
    assert rules == []
    fp._TERMS_RULES = None
    monkeypatch.setattr(fp, "TERMS_FILE", missing)
    assert fp.normalize_terms("foo") == "foo"
