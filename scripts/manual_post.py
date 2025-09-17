"""Send a manual message as Arvi to a Discord channel.

This helper script makes it easy to post a pre-written message – and an optional
image – to any Discord channel where the Arvi bot has permission to send
messages. The script is designed for manual, ad-hoc use from the command line.

Usage example::

    python scripts/manual_post.py --channel 123456789012345678 \
        --message "Tässä päivän tiedote" --image /path/to/picture.png

The Discord bot token is read from the ``DISCORD_BOT_TOKEN`` environment
variable, which should already be configured for the other Arvi automation
scripts.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
from pathlib import Path
from typing import Optional

import requests


DISCORD_API = "https://discord.com/api/v10"


def read_message(args: argparse.Namespace) -> str:
    """Resolve the message body from CLI arguments or stdin."""

    if args.message is not None and args.message_file is not None:
        raise SystemExit("Valitse joko --message tai --message-file, ei molempia.")

    if args.message is not None:
        return args.message

    if args.message_file is not None:
        path = Path(args.message_file)
        if not path.is_file():
            raise SystemExit(f"Tekstitiedostoa ei löydy: {path}")
        return path.read_text(encoding="utf-8").strip()

    # Fallback: read from stdin if available
    try:
        import sys

        if not sys.stdin.isatty():
            data = sys.stdin.read()
            if data.strip():
                return data.strip()
    except Exception:  # pragma: no cover - defensive
        pass

    raise SystemExit("Anna viesti --message, --message-file tai stdin-kautta.")


def build_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bot {token}"}


def send_message(
    *,
    token: str,
    channel_id: str,
    content: str,
    image_path: Optional[str] = None,
) -> None:
    """Send a message to Discord, optionally including one image attachment."""

    url = f"{DISCORD_API}/channels/{channel_id}/messages"
    headers = build_headers(token)

    if image_path:
        path = Path(image_path)
        if not path.is_file():
            raise SystemExit(f"Kuvatiedostoa ei löydy: {path}")

        mime_type, _ = mimetypes.guess_type(path.name)
        mime_type = mime_type or "application/octet-stream"

        payload = {
            "content": content,
            "attachments": [
                {
                    "id": 0,
                    "filename": path.name,
                }
            ],
        }

        with path.open("rb") as file_obj:
            files = {"files[0]": (path.name, file_obj, mime_type)}
            response = requests.post(
                url,
                headers=headers,
                data={"payload_json": json.dumps(payload, ensure_ascii=False)},
                files=files,
                timeout=30,
            )
    else:
        payload = {"content": content}
        response = requests.post(
            url,
            headers={**headers, "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )

    if response.status_code >= 300:
        raise SystemExit(
            f"Discord vastasi virheellä ({response.status_code}): {response.text[:200]}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--channel",
        required=True,
        help="Discord-kanavan ID, jonne viesti lähetetään.",
    )
    parser.add_argument(
        "--message",
        help="Lähetettävä viesti merkkijonona.",
    )
    parser.add_argument(
        "--message-file",
        help="Polku tiedostoon, jonka sisältö lähetetään viestinä.",
    )
    parser.add_argument(
        "--image",
        help="Valinnainen kuvatiedoston polku. Lähetetään viestin liitteenä.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN ei ole asetettu ympäristömuuttujaksi.")

    content = read_message(args)
    if not content:
        raise SystemExit("Viesti on tyhjä.")
    if len(content) > 2000:
        raise SystemExit("Discordin viestiraja on 2000 merkkiä – lyhennä tekstiä.")

    send_message(
        token=token,
        channel_id=args.channel,
        content=content,
        image_path=args.image,
    )

    print("✅ Viesti lähetetty onnistuneesti.")


if __name__ == "__main__":
    main()
