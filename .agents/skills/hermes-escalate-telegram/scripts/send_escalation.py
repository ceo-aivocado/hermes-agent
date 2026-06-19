#!/usr/bin/env python3
"""Send a Hermes escalation message through Telegram Bot API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


VALID_TRIGGERS = {
    "Contradiction",
    "Architectural",
    "Irreversible",
    "Stuck-after-retry",
    "Ambiguity",
}

DEFAULT_OWNER_TELEGRAM_ID = "10954083"


def main() -> int:
    args = parse_args()
    token = os.environ.get("AIVOCADO_BOT_TOKEN", "").strip()
    if args.token_stdin:
        token = sys.stdin.readline().strip()
    chat_id = (args.chat_id or os.environ.get("OWNER_TELEGRAM_ID") or DEFAULT_OWNER_TELEGRAM_ID).strip()

    if args.trigger not in VALID_TRIGGERS:
        print(
            f"Invalid trigger {args.trigger!r}. Allowed: {', '.join(sorted(VALID_TRIGGERS))}",
            file=sys.stderr,
        )
        return 2

    text = compose_message(args)
    if args.dry_run:
        print(json.dumps({"chat_id": chat_id, "text": text}, ensure_ascii=False, indent=2))
        return 0

    if not token:
        print("AIVOCADO_BOT_TOKEN is required.", file=sys.stderr)
        return 2
    if not chat_id:
        print("OWNER_TELEGRAM_ID is required.", file=sys.stderr)
        return 2

    response = send_message(token=token, chat_id=chat_id, text=text)
    message_id = response.get("result", {}).get("message_id")
    print(f"Telegram escalation sent to {chat_id}; message_id={message_id}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True)
    parser.add_argument("--trigger", required=True, choices=sorted(VALID_TRIGGERS))
    parser.add_argument("--context", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--blocked-by", required=True)
    parser.add_argument("--link", default="")
    parser.add_argument("--chat-id", default="")
    parser.add_argument("--token-stdin", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def compose_message(args: argparse.Namespace) -> str:
    link = args.link.strip() or "not available"
    return "\n".join(
        [
            f"🔔 Hermes Bot | {args.role.strip()} | {args.trigger}",
            f"Контекст: {args.context.strip()}",
            f"Нужно решение: {args.question.strip()}",
            f"Что встало: {args.blocked_by.strip()}",
            f"Ссылка: {link}",
        ]
    )


def send_message(token: str, chat_id: str, text: str) -> dict:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Telegram API failed: HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Telegram API failed: {exc}") from exc

    data = json.loads(body)
    if not data.get("ok"):
        raise SystemExit(f"Telegram API returned ok=false: {body}")
    return data


if __name__ == "__main__":
    raise SystemExit(main())
