#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Promote pending Discord review posts to the main channel."""

from __future__ import annotations

import argparse
import importlib.util
import re
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


MAX_UIDS = 10
MIN_UIDS = 1


def _parse_uids(values: list[str]) -> list[str]:
    parsed: list[str] = []
    for value in values:
        parts = re.split(r"[,\s]+", value.strip()) if value.strip() else []
        for part in parts:
            part = part.strip()
            if part:
                parsed.append(part)

    if not parsed:
        raise SystemExit("UID ei voi olla tyhjä.")
    if len(parsed) < MIN_UIDS or len(parsed) > MAX_UIDS:
        raise SystemExit(f"UID:ien määrän pitää olla välillä {MIN_UIDS}-{MAX_UIDS}.")
    return parsed


def promote_many(uids: list[str]) -> None:
    uids = _parse_uids(uids)

    pending = load_pending_posts(PENDING_POSTS_FILE)
    missing = [uid for uid in uids if uid not in pending]
    if missing:
        raise SystemExit(f"UID:tä {missing[0]} ei löytynyt tiedostosta {PENDING_POSTS_FILE}.")

    for uid in uids:
        entry = pending[uid]
        title = entry.get("title")
        url = entry.get("url")
        source = entry.get("source")
        raw_summary = entry.get("raw_summary")
        image_url = entry.get("image_url")
        ai_comment = entry.get("ai_comment")

        missing_fields = [name for name, value in (
            ("title", title),
            ("url", url),
            ("source", source),
        ) if not value]
        if missing_fields:
            raise SystemExit(
                "Tiedossa {file} oleva merkintä {uid} puuttuu kentät: {fields}".format(
                    file=PENDING_POSTS_FILE,
                    uid=uid,
                    fields=", ".join(missing_fields),
                )
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
        print(f"Promoted UID {uid} pääkanavaan.")

    save_pending_posts(pending, PENDING_POSTS_FILE)


def promote(uid: str) -> None:
    promote_many([uid])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Promote pending Discord posts.")
    parser.add_argument(
        "uid",
        nargs="+",
        help="Yksi tai useampi tarkistuskanavan UID (välilyönnein tai pilkuin eroteltuna)",
    )
    args = parser.parse_args(argv)
    promote_many(args.uid)


if __name__ == "__main__":
    main()
