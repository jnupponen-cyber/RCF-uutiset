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


def test_ai_make_comment_uses_normalized_terms(monkeypatch, tmp_path):
    csv = tmp_path / "terms.csv"
    csv.write_text("peloton;pääjoukko;1\n", encoding="utf-8")
    monkeypatch.setattr(fp, "TERMS_FILE", csv)
    fp._TERMS_RULES = None

    monkeypatch.setattr(fp, "ENABLE_AI_SUMMARY", True)
    monkeypatch.setattr(fp, "OPENAI_API_KEY", "test-key")

    captured = {}

    class DummyResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {"message": {"content": "Peloton hallitsee etapin. Toiseksi jäi muut."}}
                ]
            }

    def fake_post(url, headers, json, timeout):
        captured["payload"] = json
        return DummyResponse()

    monkeypatch.setattr(fp.requests, "post", fake_post)

    result = fp.ai_make_comment(
        title="Peloton irtautuu",
        source="Test Source",
        url="https://example.com",
        raw_summary="Peloton ottaa vetovuoron",
        maxlen=200,
    )

    prompt = captured["payload"]["messages"][1]["content"]
    assert "pääjoukko" in prompt.lower()
    assert "Otsikko: Pääjoukko irtautuu" in prompt
    assert "Peloton irtautuu" not in prompt
    assert "Pääjoukko ottaa vetovuoron" in prompt
    assert "Pääjoukko hallitsee etapin." in result
