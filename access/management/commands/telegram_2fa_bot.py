from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from access.telegram_2fa import send_setup_code_for_telegram_user

log = logging.getLogger("access.telegram_2fa.bot")


class Command(BaseCommand):
    help = "Poll Telegram updates for the DW Telegram 2FA bot and send setup codes."

    def add_arguments(self, parser):
        parser.add_argument("--poll-interval", type=float, default=2.0)
        parser.add_argument("--timeout", type=int, default=25)
        parser.add_argument("--once", action="store_true", help="Poll Telegram once and exit.")

    def handle(self, *args, **options):
        token = str(getattr(settings, "TELEGRAM_2FA_BOT_TOKEN", "") or "").strip()
        if not token:
            raise CommandError("TELEGRAM_2FA_BOT_TOKEN is not configured.")

        offset = None
        self.stdout.write(self.style.SUCCESS("Telegram 2FA bot polling started."))
        while True:
            updates = self._get_updates(token, offset, options["timeout"])
            log.info("telegram_bot_updates_received count=%s offset=%s", len(updates), offset)
            for update in updates:
                offset = update["update_id"] + 1
                try:
                    self._handle_update(update)
                except Exception:
                    log.exception("telegram_bot_update_failed update_id=%s", update.get("update_id"))
                    self.stderr.write(f"Failed to process Telegram update {update.get('update_id')}. Check logs.")
            if options["once"]:
                return
            time.sleep(options["poll_interval"])

    def _get_updates(self, token: str, offset: int | None, timeout: int) -> list[dict]:
        params = {"timeout": timeout, "allowed_updates": json.dumps(["message"])}
        if offset is not None:
            params["offset"] = offset
        url = f"https://api.telegram.org/bot{token}/getUpdates?{urllib.parse.urlencode(params)}"
        with urllib.request.urlopen(url, timeout=timeout + 5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("ok"):
            raise CommandError(payload.get("description") or "Telegram getUpdates failed.")
        return payload.get("result", [])

    def _handle_update(self, update: dict):
        message = update.get("message") or {}
        sender = message.get("from") or {}
        chat = message.get("chat") or {}
        username = sender.get("username")
        chat_id = chat.get("id")
        if not username or not chat_id:
            log.warning("telegram_bot_message_skipped reason=missing_username_or_chat_id username=%s chat_id=%s", username, chat_id)
            return
        log.info("telegram_bot_message_received telegram_username=%s chat_id=%s", username, chat_id)
        challenge = send_setup_code_for_telegram_user(username, str(chat_id))
        if challenge:
            self.stdout.write(f"Sent setup code for @{username} to chat {chat_id}.")
        else:
            self.stdout.write(f"No pending 2FA setup for @{username}.")
