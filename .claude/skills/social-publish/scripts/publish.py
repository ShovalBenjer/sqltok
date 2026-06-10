#!/usr/bin/env python3
"""Publish a post to a social platform, using only the standard library.

Only platforms whose credentials are present in the environment can be used.
Defaults to a dry run: it prints exactly what would be sent and exits without
sending. Pass --confirm to actually publish. The house-style linter runs first
and blocks sending on any violation unless --skip-lint is given.

Examples:
    python publish.py --file drafts/bluesky.txt --platform bluesky
    python publish.py --file drafts/bluesky.txt --platform bluesky --confirm
    python publish.py --file post.md --platform devto --title "..." \\
        --canonical https://yoursite/post --confirm
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lint_post import lint  # noqa: E402


def http_json(url: str, payload: dict, headers: dict, *, dry_run: bool) -> tuple[bool, str]:
    body = json.dumps(payload).encode("utf-8")
    redacted = {k: ("***" if k.lower() in {"authorization", "api-key", "x-api-key"} else v)
                for k, v in headers.items()}
    if dry_run:
        return True, f"DRY RUN POST {url}\nheaders={redacted}\nbody={json.dumps(payload, indent=2)}"
    req = urllib.request.Request(url, data=body, headers={**headers, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return True, f"OK {resp.status} {resp.read(200).decode('utf-8', 'replace')}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}"
    except urllib.error.URLError as exc:
        return False, f"network error: {exc.reason}"


def post_bluesky(text: str, dry_run: bool) -> tuple[bool, str]:
    handle = os.environ.get("BLUESKY_HANDLE")
    password = os.environ.get("BLUESKY_APP_PASSWORD")
    if not handle or not password:
        return False, "missing BLUESKY_HANDLE or BLUESKY_APP_PASSWORD"
    pds = os.environ.get("BLUESKY_PDS", "https://bsky.social")
    if dry_run:
        return http_json(f"{pds}/xrpc/com.atproto.repo.createRecord",
                         {"repo": handle, "collection": "app.bsky.feed.post",
                          "record": {"$type": "app.bsky.feed.post", "text": text}},
                         {"Authorization": "Bearer ***"}, dry_run=True)
    ok, msg = http_json(f"{pds}/xrpc/com.atproto.server.createSession",
                        {"identifier": handle, "password": password}, {}, dry_run=False)
    if not ok:
        return False, f"login failed: {msg}"
    try:
        session = json.loads(msg.split(" ", 2)[2])
    except Exception:
        return False, f"could not parse session: {msg}"
    record = {"$type": "app.bsky.feed.post", "text": text,
              "createdAt": datetime.now(timezone.utc).isoformat()}
    return http_json(f"{pds}/xrpc/com.atproto.repo.createRecord",
                     {"repo": session["did"], "collection": "app.bsky.feed.post", "record": record},
                     {"Authorization": f"Bearer {session['accessJwt']}"}, dry_run=False)


def post_mastodon(text: str, dry_run: bool) -> tuple[bool, str]:
    base = os.environ.get("MASTODON_BASE_URL")
    token = os.environ.get("MASTODON_TOKEN")
    if not base or not token:
        return False, "missing MASTODON_BASE_URL or MASTODON_TOKEN"
    return http_json(f"{base.rstrip('/')}/api/v1/statuses", {"status": text},
                     {"Authorization": f"Bearer {token}"}, dry_run=dry_run)


def post_devto(text: str, dry_run: bool, title: str | None, canonical: str | None, tags: str | None) -> tuple[bool, str]:
    key = os.environ.get("DEVTO_API_KEY")
    if not key:
        return False, "missing DEVTO_API_KEY"
    if not title:
        return False, "dev.to needs --title"
    article = {"title": title, "body_markdown": text, "published": True}
    if canonical:
        article["canonical_url"] = canonical
    if tags:
        article["tags"] = [t.strip() for t in tags.split(",") if t.strip()][:4]
    return http_json("https://dev.to/api/articles", {"article": article},
                     {"api-key": key}, dry_run=dry_run)


def post_typefully(text: str, dry_run: bool) -> tuple[bool, str]:
    key = os.environ.get("TYPEFULLY_API_KEY")
    if not key:
        return False, "missing TYPEFULLY_API_KEY"
    # Typefully splits a thread on 4 consecutive newlines.
    return http_json("https://api.typefully.com/v1/drafts/",
                     {"content": text, "threadify": True},
                     {"X-API-KEY": key}, dry_run=dry_run)


def main() -> int:
    p = argparse.ArgumentParser(description="Publish a post to a social platform.")
    p.add_argument("--file", help="path to the post text (otherwise read stdin)")
    p.add_argument("--platform", required=True,
                   choices=["bluesky", "mastodon", "devto", "typefully"])
    p.add_argument("--confirm", action="store_true", help="actually send (default is dry run)")
    p.add_argument("--skip-lint", action="store_true", help="bypass the style linter (discouraged)")
    p.add_argument("--title", help="dev.to article title")
    p.add_argument("--canonical", help="dev.to canonical_url")
    p.add_argument("--tags", help="dev.to comma-separated tags")
    args = p.parse_args()

    text = open(args.file, encoding="utf-8").read() if args.file else sys.stdin.read()
    text = text.strip()

    if not args.skip_lint:
        issues = lint(text)
        if issues:
            print("Style linter failed. Fix these before publishing:")
            for issue in issues:
                print(f"  - {issue}")
            return 1

    dry = not args.confirm
    if args.platform == "bluesky":
        ok, msg = post_bluesky(text, dry)
    elif args.platform == "mastodon":
        ok, msg = post_mastodon(text, dry)
    elif args.platform == "devto":
        ok, msg = post_devto(text, dry, args.title, args.canonical, args.tags)
    else:
        ok, msg = post_typefully(text, dry)

    print(msg)
    if dry:
        print("\n(dry run. add --confirm to publish.)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
