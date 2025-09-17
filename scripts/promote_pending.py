#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Promote pending Discord review posts to the main channel."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FETCH_AND_POST_PATH = PROJECT_ROOT / "rcf-discord-news" / "fetch_and_post.py"


def _load_fetch_module():
    spec = importlib.util.spec_from_file_location("rcf_fetch_and_post", FETCH_AND_POST_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit(f"fetch_and_post.py ei löytynyt polusta {FETCH_AND_POST_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


FETCH_MODULE = _load_fetch_module()
post_to_discord = FETCH_MODULE.post_to_discord
load_pending_posts = FETCH_MODULE.load_pending_posts
save_pending_posts = FETCH_MODULE.save_pending_posts
PENDING_POSTS_FILE = FETCH_MODULE.PENDING_POSTS_FILE


def promote(uid: str) -> None:
    uid = uid.strip()
    if not uid:
        raise SystemExit("UID ei voi olla tyhjä.")

    pending = load_pending_posts(PENDING_POSTS_FILE)
    if uid not in pending:
        raise SystemExit(f"UID:tä {uid} ei löytynyt tiedostosta {PENDING_POSTS_FILE}.")

    entry = pending[uid]
    title = entry.get("title")
    url = entry.get("url")
    source = entry.get("source")
    raw_summary = entry.get("raw_summary")
    image_url = entry.get("image_url")
    ai_comment = entry.get("ai_comment")

    missing = [name for name, value in (
        ("title", title),
        ("url", url),
        ("source", source),
    ) if not value]
    if missing:
        raise SystemExit(
            f"Tiedossa {PENDING_POSTS_FILE} oleva merkintä {uid} puuttuu kentät: {', '.join(missing)}"
        )

    post_to_discord(
        title=title,
        url=url,
        source=source,
        raw_summary=raw_summary,
        image_url=image_url,
        ai_comment=ai_comment,
        seen_uid=uid,
        use_review_channel=False,
    )

    del pending[uid]
    save_pending_posts(pending, PENDING_POSTS_FILE)
    print(f"Promoted UID {uid} pääkanavaan.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Promote a pending Discord post.")
    parser.add_argument("uid", help="Tarkistuskanavan viestin UID")
    args = parser.parse_args(argv)
    promote(args.uid)


if __name__ == "__main__":
    main()
