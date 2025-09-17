#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, os, sys, json, mimetypes, requests, pathlib

API_BASE = "https://discord.com/api/v10"

def post_text(token: str, channel_id: str, content: str, embed_image_url: str | None = None):
    url = f"{API_BASE}/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {token}"}
    payload = {"content": content}
    if embed_image_url:
        payload["embeds"] = [{"image": {"url": embed_image_url}}]
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    if r.status_code >= 300:
        raise SystemExit(f"Discord API error {r.status_code}: {r.text}")
    return r.json()

def post_with_attachment(token: str, channel_id: str, content: str, file_path: str):
    url = f"{API_BASE}/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {token}"}

    filename = pathlib.Path(file_path).name
    # attachments metadata
    payload_json = {
        "content": content,
        "attachments": [{"id": "0", "filename": filename}]
    }

    mime, _ = mimetypes.guess_type(filename)
    if not mime:
        mime = "application/octet-stream"

    with open(file_path, "rb") as f:
        files = [
            ("payload_json", (None, json.dumps(payload_json), "application/json")),
            ("files[0]", (filename, f, mime)),
        ]
        r = requests.post(url, headers=headers, files=files, timeout=60)
    if r.status_code >= 300:
        raise SystemExit(f"Discord API error {r.status_code}: {r.text}")
    return r.json()

def main():
    p = argparse.ArgumentParser(description="Post message (and optional image) to a Discord channel.")
    p.add_argument("--channel-id", required=True)
    p.add_argument("--message", default="")
    p.add_argument("--message-file", default="")
    p.add_argument("--image-url", default="")     # 1) linkitetty kuva (Discord upottaa tai embed-image)
    p.add_argument("--attach-image", action="store_true", help="Download image-url and upload as attachment")
    p.add_argument("--embed-image", action="store_true", help="Use image-url as embed image")
    args = p.parse_args()

    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise SystemExit("Missing DISCORD_BOT_TOKEN")

    # Viestisisältö: file > direct
    content = args.message
    if args.message_file:
        path = pathlib.Path(args.message_file)
        if not path.exists():
            raise SystemExit(f"message-file not found: {path}")
        content = path.read_text(encoding="utf-8")

    # Discordin raja: 2000 merkkiä / viesti (yksinkertaisesti tarkistetaan)
    if len(content) > 2000:
        raise SystemExit(f"Message too long ({len(content)} chars). Please shorten to <= 2000.")

    # Kuva-asetukset:
    if args.attach_image and args.image_url:
        # Lataa kuva väliaikaisesti ja liitä tiedostona
        tmp_path = pathlib.Path("downloaded_image")
        data = requests.get(args.image_url, timeout=60)
        data.raise_for_status()
        # Arvaa tiedostopääte content-typestä
        ext = ".bin"
        ctype = data.headers.get("Content-Type", "")
        if "png" in ctype: ext = ".png"
        elif "jpeg" in ctype or "jpg" in ctype: ext = ".jpg"
        elif "gif" in ctype: ext = ".gif"
        tmp_file = tmp_path.with_suffix(ext)
        tmp_file.write_bytes(data.content)
        try:
            resp = post_with_attachment(token, args.channel_id, content, str(tmp_file))
            print("Posted with attachment:", resp.get("id"))
        finally:
            try:
                tmp_file.unlink()
            except Exception:
                pass
        return

    # Ei liitetiedostoa → peruspostaus (optionaalinen embed-kuva)
    embed_url = args.image_url if args.embed_image and args.image_url else None
    resp = post_text(token, args.channel_id, content, embed_image_url=embed_url)
    print("Posted:", resp.get("id"))

if __name__ == "__main__":
    main()
