#!/usr/bin/env python3
"""Send a pre-written message (and optional image) to a Discord channel.

The script is intended for manual runs either from a developer machine or via
GitHub Actions.  It uses the raw Discord HTTP API which keeps the
dependencies minimal (only :mod:`requests`).

Examples
--------
.. code-block:: bash

   export DISCORD_BOT_TOKEN="..."
   python scripts/manual_post.py \
       --channel 123456789012345678 \
       --message "Tässä päivän tiedote" \
       --image kuva.png

The message can also be read from a file with ``--message-file`` or piped via
stdin.  To embed an image that already lives online, supply ``--embed-url``; to
download an image from a URL and attach it as a file, use ``--image-url``.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import pathlib
import shutil
import sys
import tempfile
from typing import Iterable

import requests


API_BASE = "https://discord.com/api/v10"
MAX_CONTENT_LENGTH = 2000


def clean_token(raw: str | None) -> str:
    """Remove optional ``Bot``/``Bearer`` prefixes and whitespace."""

    token = (raw or "").strip()
    for prefix in ("Bot ", "Bearer "):
        if token.startswith(prefix):
            token = token[len(prefix) :]
    return token


def chunk_message(content: str, limit: int = MAX_CONTENT_LENGTH) -> list[str]:
    """Split ``content`` into pieces Discord will accept."""

    if len(content) <= limit:
        return [content]

    lines = content.splitlines()
    chunks: list[str] = []
    buffer = ""
    for line in lines:
        candidate = buffer + ("\n" if buffer else "") + line
        if len(candidate) <= limit:
            buffer = candidate
            continue

        if buffer:
            chunks.append(buffer)
            buffer = ""

        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        buffer = line

    if buffer:
        chunks.append(buffer)

    return chunks


def http_json(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    """Send a JSON request to the Discord API and return the decoded body."""

    headers = {"Authorization": f"Bot {token}"}
    response = requests.request(method.upper(), url, headers=headers, json=payload, timeout=30)
    if response.status_code >= 300:
        raise SystemExit(f"Discord API error {response.status_code}: {response.text}")
    return response.json()


def post_text(
    token: str,
    channel_id: str,
    content: str,
    *,
    embed_image_url: str | None = None,
    reply_to: str | None = None,
) -> dict:
    payload: dict = {"content": content}
    if embed_image_url:
        payload["embeds"] = [{"image": {"url": embed_image_url}}]
    if reply_to:
        payload["message_reference"] = {"message_id": reply_to, "channel_id": channel_id}
    url = f"{API_BASE}/channels/{channel_id}/messages"
    return http_json("POST", url, token, payload)


def post_with_file(
    token: str,
    channel_id: str,
    content: str,
    file_path: pathlib.Path,
    *,
    reply_to: str | None = None,
) -> dict:
    url = f"{API_BASE}/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {token}"}

    filename = file_path.name
    mime, _ = mimetypes.guess_type(filename)
    if not mime:
        mime = "application/octet-stream"

    payload_json: dict = {
        "content": content,
        "attachments": [{"id": "0", "filename": filename}],
    }
    if reply_to:
        payload_json["message_reference"] = {"message_id": reply_to, "channel_id": channel_id}

    with file_path.open("rb") as fh:
        files = [
            ("payload_json", (None, json.dumps(payload_json), "application/json")),
            ("files[0]", (filename, fh, mime)),
        ]
        response = requests.post(url, headers=headers, files=files, timeout=60)

    if response.status_code >= 300:
        raise SystemExit(f"Discord API error {response.status_code}: {response.text}")

    return response.json()


def read_message_argument(args: argparse.Namespace) -> str:
    if args.message_file:
        path = pathlib.Path(args.message_file)
        if not path.exists():
            raise SystemExit(f"message-file not found: {path}")
        return path.read_text(encoding="utf-8")

    if args.message:
        return args.message

    if not sys.stdin.isatty():
        return sys.stdin.read()

    return ""


def download_url_to_temp(url: str) -> pathlib.Path:
    response = requests.get(url, timeout=60)
    if response.status_code >= 300:
        raise SystemExit(f"Failed to download image-url: HTTP {response.status_code}")

    suffix = pathlib.Path(url).suffix
    if not suffix:
        content_type = response.headers.get("Content-Type", "")
        if "png" in content_type:
            suffix = ".png"
        elif "gif" in content_type:
            suffix = ".gif"
        elif "jpeg" in content_type or "jpg" in content_type:
            suffix = ".jpg"
        else:
            suffix = ".bin"

    tmpdir = pathlib.Path(tempfile.mkdtemp())
    path = tmpdir / f"download{suffix}"
    path.write_bytes(response.content)
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", required=True, help="Discord channel ID")
    parser.add_argument("--message", default="", help="Message content. Use \\n for newlines.")
    parser.add_argument("--message-file", default="", help="Path to a UTF-8 text file containing the message")
    parser.add_argument("--image", default="", help="Attach a local image file")
    parser.add_argument("--image-url", default="", help="Download an image from URL and attach it as a file")
    parser.add_argument(
        "--embed-url",
        default="",
        help="Use an online image URL inside an embed instead of uploading a file",
    )
    parser.add_argument(
        "--reply-to",
        default="",
        help="Reply to a specific message ID in the target channel",
    )
    parser.add_argument(
        "--verify-token",
        action="store_true",
        help="Verify DISCORD_BOT_TOKEN with /users/@me before posting",
    )
    return parser


def ensure_single_option(options: Iterable[str]) -> None:
    provided = [opt for opt in options if opt]
    if len(provided) > 1:
        raise SystemExit("Choose only one image option: --image, --image-url or --embed-url")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    token = clean_token(os.environ.get("DISCORD_BOT_TOKEN"))
    if not token:
        raise SystemExit("Missing or empty DISCORD_BOT_TOKEN environment variable.")

    if args.verify_token:
        me = http_json("GET", f"{API_BASE}/users/@me", token)
        username = me.get("username")
        discriminator = me.get("discriminator")
        print(f"Token OK. Bot user: {username}#{discriminator} (id={me.get('id')})")

    message = read_message_argument(args)
    if not message.strip() and not (args.image or args.image_url or args.embed_url):
        raise SystemExit("Nothing to send: provide a message, message-file, stdin or an image option.")

    ensure_single_option((args.image, args.image_url, args.embed_url))

    chunks = chunk_message(message or "")

    channel_id = args.channel
    reply_to = args.reply_to or None

    temp_file: pathlib.Path | None = None
    try:
        if args.image_url:
            temp_file = download_url_to_temp(args.image_url)
            response = post_with_file(
                token,
                channel_id,
                chunks[0] if chunks else "",
                temp_file,
                reply_to=reply_to,
            )
            print("Posted (with downloaded attachment):", response.get("id"))
            for chunk in chunks[1:]:
                response = post_text(token, channel_id, chunk)
                print("Posted:", response.get("id"))
            return

        if args.image:
            path = pathlib.Path(args.image)
            if not path.exists():
                raise SystemExit(f"image not found: {path}")
            response = post_with_file(
                token,
                channel_id,
                chunks[0] if chunks else "",
                path,
                reply_to=reply_to,
            )
            print("Posted (with attachment):", response.get("id"))
            for chunk in chunks[1:]:
                response = post_text(token, channel_id, chunk)
                print("Posted:", response.get("id"))
            return

        embed_url = args.embed_url or None
        if embed_url and not any(embed_url.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp")):
            print("Warning: --embed-url may not be a direct image URL; Discord might not render it.", file=sys.stderr)

        if chunks:
            response = post_text(
                token,
                channel_id,
                chunks[0],
                embed_image_url=embed_url,
                reply_to=reply_to,
            )
            print("Posted:", response.get("id"))
            for chunk in chunks[1:]:
                response = post_text(token, channel_id, chunk)
                print("Posted:", response.get("id"))
        else:
            response = post_text(
                token,
                channel_id,
                "",
                embed_image_url=embed_url,
                reply_to=reply_to,
            )
            print("Posted:", response.get("id"))
    finally:
        if temp_file:
            shutil.rmtree(temp_file.parent, ignore_errors=True)


if __name__ == "__main__":
    main()
