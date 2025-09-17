#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Postaa viestin (ja valinnaisen kuvan) Discord-kanavalle botilla.

Ominaisuudet:
- Teksti joko suorana (--message) tai tiedostosta (--message-file)
- Kuva paikallisesta tiedostosta (--image-file) TAI URL:sta liitteenä (--attach-url)
- Kuva upotettuna embediin (--embed-url)
- Tokenin siivous (poistaa vahingossa mukana olevat "Bot " / "Bearer " -prefiksit, whitespace)
- Pitkien viestien automaattinen pilkkominen 2000 merkkiin
- Selkeät virheilmoitukset (401/403 jne.)
"""

from __future__ import annotations
import argparse, os, sys, json, mimetypes, requests, pathlib, textwrap, tempfile

API_BASE = "https://discord.com/api/v10"
MAX_LEN = 2000


def clean_token(raw: str | None) -> str:
    tok = (raw or "").strip()
    for pref in ("Bot ", "Bearer "):
        if tok.startswith(pref):
            tok = tok[len(pref):]
    return tok


def http_json(method: str, url: str, token: str, json_payload: dict | None = None, timeout=30) -> dict:
    headers = {"Authorization": f"Bot {token}"}
    r = requests.request(method.upper(), url, headers=headers, json=json_payload, timeout=timeout)
    if r.status_code >= 300:
        raise SystemExit(f"Discord API error {r.status_code}: {r.text}")
    return r.json()


def post_text(token: str, channel_id: str, content: str, embed_image_url: str | None = None) -> dict:
    url = f"{API_BASE}/channels/{channel_id}/messages"
    payload: dict = {"content": content}
    if embed_image_url:
        payload["embeds"] = [{"image": {"url": embed_image_url}}]
    return http_json("POST", url, token, payload)


def post_with_file(token: str, channel_id: str, content: str, file_path: pathlib.Path) -> dict:
    url = f"{API_BASE}/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {token}"}

    filename = file_path.name
    mime, _ = mimetypes.guess_type(filename)
    if not mime:
        mime = "application/octet-stream"

    payload_json = {
        "content": content,
        "attachments": [{"id": "0", "filename": filename}],
    }

    with open(file_path, "rb") as f:
        files = [
            ("payload_json", (None, json.dumps(payload_json), "application/json")),
            ("files[0]", (filename, f, mime)),
        ]
        r = requests.post(url, headers=headers, files=files, timeout=60)
    if r.status_code >= 300:
        raise SystemExit(f"Discord API error {r.status_code}: {r.text}")
    return r.json()


def chunk_message(content: str, limit: int = MAX_LEN) -> list[str]:
    if len(content) <= limit:
        return [content]
    # Pilko rivinvaihdoista ja pidä palat lyhyinä
    lines = content.splitlines(keepends=False)
    out, buf = [], ""
    for ln in lines:
        # +1 rivinvaihto jos bufferissa jo dataa
        candidate = (buf + ("\n" if buf else "") + ln)
        if len(candidate) <= limit:
            buf = candidate
        else:
            if buf:
                out.append(buf)
            # jos yksittäinen rivi on valtava, pakota leikkaus
            while len(ln) > limit:
                out.append(ln[:limit])
                ln = ln[limit:]
            buf = ln
    if buf:
        out.append(buf)
    return out


def main():
    p = argparse.ArgumentParser(description="Publish a message to a Discord channel (with optional image).")
    p.add_argument("--channel-id", required=True, help="Discord channel ID")
    # Teksti
    p.add_argument("--message", default="", help="Message text (use \\n for newlines)")
    p.add_argument("--message-file", default="", help="Path to message file in repo")
    # Kuva: kolme vaihtoehtoa (anna vain yksi)
    p.add_argument("--image-file", default="", help="Attach local image file from repo")
    p.add_argument("--attach-url", default="", help="Download image from URL and attach as file")
    p.add_argument("--embed-url", default="", help="Use image URL in an embed (must be a direct image URL)")
    # Token-testi (vapaaehtoinen diagnostiikka)
    p.add_argument("--verify-token", action="store_true", help="Verify token via /users/@me before posting")
    args = p.parse_args()

    token = clean_token(os.environ.get("DISCORD_BOT_TOKEN"))
    if not token:
        raise SystemExit("Missing or empty DISCORD_BOT_TOKEN (GitHub Secret).")

    # Vapaaehtoinen tokenin verifiointi
    if args.verify_token:
        me = http_json("GET", f"{API_BASE}/users/@me", token)
        print(f"Token OK. Bot user: {me.get('username')}#{me.get('discriminator')} (id={me.get('id')})")

    # Lue viesti
    content = args.message or ""
    if args.message_file:
        path = pathlib.Path(args.message_file)
        if not path.exists():
            raise SystemExit(f"message-file not found: {path}")
        content = path.read_text(encoding="utf-8")

    if not content.strip() and not (args.image_file or args.attach_url or args.embed_url):
        raise SystemExit("Nothing to send: provide --message/--message-file or an image option.")

    # Varmista ettei samaan aikaan anneta useita kuvaoptioita
    image_opts = [bool(args.image_file), bool(args.attach_url), bool(args.embed_url)]
    if sum(image_opts) > 1:
        raise SystemExit("Choose only one image option: --image-file OR --attach-url OR --embed-url")

    # Jos teksti ylittää 2000, pilko useaksi viestiksi
    chunks = chunk_message(content or "")

    # Jos mukana on LIITEkuva (paikallinen tiedosto TAI URL liitteeksi), liitä kuva ensimmäiseen viestiin
    channel_id = args.channel_id

    if args.image_file:
        file_path = pathlib.Path(args.image_file)
        if not file_path.exists():
            raise SystemExit(f"image-file not found: {file_path}")
        # Ensimmäinen pala kuvan kanssa
        first = chunks[0] if chunks else ""
        resp = post_with_file(token, channel_id, first, file_path)
        print("Posted (with local attachment):", resp.get("id"))
        # Lähetä loput palat ilman kuvaa
        for part in chunks[1:]:
            resp = post_text(token, channel_id, part)
            print("Posted:", resp.get("id"))
        return

    if args.attach_url:
        # Lataa URL ja liitä tiedostona
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td) / "image"
            r = requests.get(args.attach_url, timeout=60)
            if r.status_code >= 300:
                raise SystemExit(f"Failed to download attach-url: HTTP {r.status_code}")
            ctype = r.headers.get("Content-Type", "")
            ext = ".jpg" if "jpeg" in ctype or "jpg" in ctype else ".png" if "png" in ctype else ".gif" if "gif" in ctype else ".bin"
            tmp = tmp.with_suffix(ext)
            tmp.write_bytes(r.content)
            first = chunks[0] if chunks else ""
            resp = post_with_file(token, channel_id, first, tmp)
            print("Posted (with url attachment):", resp.get("id"))
        for part in chunks[1:]:
            resp = post_text(token, channel_id, part)
            print("Posted:", resp.get("id"))
        return

    # EMBED-kuva (suora .jpg/.png/.gif -linkki)
    embed_url = args.embed_url or None
    if embed_url and not any(embed_url.lower().endswith(suf) for suf in (".jpg", ".jpeg", ".png", ".gif", ".webp")):
        print("Warning: --embed-url does not look like a direct image URL; Discord may not render it.", file=sys.stderr)

    if chunks:
        # Jos useampi pala, laita embed vain ensimmäiseen (ettei toistu)
        first = chunks[0]
        resp = post_text(token, channel_id, first, embed_image_url=embed_url)
        print("Posted:", resp.get("id"))
        for part in chunks[1:]:
            resp = post_text(token, channel_id, part)
            print("Posted:", resp.get("id"))
    else:
        resp = post_text(token, channel_id, "", embed_image_url=embed_url)
        print("Posted:", resp.get("id"))


if __name__ == "__main__":
    main()
