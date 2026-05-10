from __future__ import annotations

import json
import logging
import secrets
import urllib.parse
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import TelegramTwoFactorChallenge, TelegramTwoFactorSettings

log = logging.getLogger("access.telegram_2fa")


class Telegram2FAError(Exception):
    pass


class TelegramBotNotConfigured(Telegram2FAError):
    pass


class TelegramDeliveryError(Telegram2FAError):
    pass


def bot_username() -> str:
    return getattr(settings, "TELEGRAM_2FA_BOT_USERNAME", "darkweather_2fa_bot").lstrip("@")


def bot_url() -> str:
    return f"https://t.me/{bot_username()}"


def normalize_telegram_username(value: str) -> str:
    return str(value or "").strip().lstrip("@").lower()


def generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def get_user_settings(user) -> TelegramTwoFactorSettings:
    settings_obj, _created = TelegramTwoFactorSettings.objects.get_or_create(user=user)
    return settings_obj


def serialize_settings(settings_obj: TelegramTwoFactorSettings) -> dict:
    return {
        "telegram_username": settings_obj.telegram_username,
        "telegram_bot_username": f"@{bot_username()}",
        "telegram_bot_url": bot_url(),
        "is_enabled": settings_obj.is_enabled,
        "is_linked": bool(settings_obj.telegram_chat_id and settings_obj.verified_at),
        "frequency": settings_obj.frequency,
        "verified_at": settings_obj.verified_at,
        "last_verified_at": settings_obj.last_verified_at,
    }


def create_challenge(
    *,
    user,
    purpose: str,
    telegram_username: str = "",
    telegram_chat_id: str = "",
    ttl_minutes: int = 10,
) -> tuple[TelegramTwoFactorChallenge, str]:
    code = generate_code()
    challenge = TelegramTwoFactorChallenge.objects.create(
        user=user,
        purpose=purpose,
        code_hash=TelegramTwoFactorChallenge.hash_code(code),
        telegram_username=normalize_telegram_username(telegram_username),
        telegram_chat_id=str(telegram_chat_id or ""),
        expires_at=timezone.now() + timedelta(minutes=ttl_minutes),
    )
    return challenge, code


def send_telegram_message(chat_id: str, text: str) -> None:
    token = str(getattr(settings, "TELEGRAM_2FA_BOT_TOKEN", "") or "").strip()
    if not token:
        log.error("telegram_message_send_failed reason=bot_token_missing chat_id=%s", chat_id)
        raise TelegramBotNotConfigured("TELEGRAM_2FA_BOT_TOKEN is not configured.")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    request = urllib.request.Request(url, data=payload, method="POST")
    log.info("telegram_message_send_started chat_id=%s", chat_id)
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            body = response.read().decode("utf-8")
    except Exception as exc:  # pragma: no cover - network failures are environment-specific
        log.exception("telegram_message_send_failed reason=network chat_id=%s", chat_id)
        raise TelegramDeliveryError(str(exc)) from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:  # pragma: no cover
        log.exception("telegram_message_send_failed reason=invalid_json chat_id=%s", chat_id)
        raise TelegramDeliveryError("Telegram returned invalid JSON.") from exc

    if not parsed.get("ok"):
        log.error("telegram_message_send_failed reason=telegram_error chat_id=%s description=%s", chat_id, parsed.get("description"))
        raise TelegramDeliveryError(str(parsed.get("description") or "Telegram sendMessage failed."))
    log.info("telegram_message_send_succeeded chat_id=%s", chat_id)


def start_setup(user, telegram_username: str) -> TelegramTwoFactorSettings:
    username = normalize_telegram_username(telegram_username)
    if not username:
        raise ValueError("telegram_username is required")

    settings_obj = get_user_settings(user)
    username_changed = settings_obj.telegram_username != username
    settings_obj.telegram_username = username
    settings_obj.setup_requested_at = timezone.now()
    settings_obj.is_enabled = False
    if username_changed:
        settings_obj.telegram_chat_id = ""
        settings_obj.verified_at = None
        settings_obj.last_verified_at = None
    settings_obj.save(
        update_fields=[
            "telegram_username",
            "setup_requested_at",
            "is_enabled",
            "telegram_chat_id",
            "verified_at",
            "last_verified_at",
            "updated_at",
        ]
    )
    return settings_obj


def send_setup_code_for_telegram_user(telegram_username: str, chat_id: str) -> TelegramTwoFactorChallenge | None:
    username = normalize_telegram_username(telegram_username)
    log.info("telegram_setup_message_received telegram_username=%s chat_id=%s", username or "<empty>", chat_id)
    settings_obj = (
        TelegramTwoFactorSettings.objects.select_related("user")
        .filter(telegram_username=username, setup_requested_at__isnull=False)
        .order_by("-setup_requested_at")
        .first()
    )
    if not settings_obj:
        log.warning("telegram_setup_code_skipped reason=no_pending_setup telegram_username=%s chat_id=%s", username or "<empty>", chat_id)
        return None

    settings_obj.telegram_chat_id = str(chat_id)
    settings_obj.save(update_fields=["telegram_chat_id", "updated_at"])
    challenge, code = create_challenge(
        user=settings_obj.user,
        purpose=TelegramTwoFactorChallenge.PURPOSE_SETUP,
        telegram_username=username,
        telegram_chat_id=str(chat_id),
    )
    send_telegram_message(
        str(chat_id),
        f"Код привязки DW Погода: {code}. Он действует 10 минут.",
    )
    challenge.sent_at = timezone.now()
    challenge.save(update_fields=["sent_at"])
    log.info("telegram_setup_code_sent user_id=%s telegram_username=%s", settings_obj.user_id, username)
    return challenge


def _active_challenge(user, purpose: str) -> TelegramTwoFactorChallenge | None:
    return (
        TelegramTwoFactorChallenge.objects.filter(user=user, purpose=purpose, consumed_at__isnull=True)
        .order_by("-created_at")
        .first()
    )


def verify_challenge_code(challenge: TelegramTwoFactorChallenge | None, code: str) -> TelegramTwoFactorChallenge:
    if not challenge or challenge.is_expired():
        raise Telegram2FAError("Код истёк или не найден.")
    if challenge.attempts >= 5:
        raise Telegram2FAError("Слишком много попыток. Запросите новый код.")

    challenge.attempts += 1
    if not challenge.verify_code(code):
        challenge.save(update_fields=["attempts"])
        raise Telegram2FAError("Неверный код.")

    challenge.consumed_at = timezone.now()
    challenge.save(update_fields=["attempts", "consumed_at"])
    return challenge


def verify_challenge(user, purpose: str, code: str) -> TelegramTwoFactorChallenge:
    return verify_challenge_code(_active_challenge(user, purpose), code)


def verify_setup(user, code: str) -> TelegramTwoFactorSettings:
    verify_challenge(user, TelegramTwoFactorChallenge.PURPOSE_SETUP, code)
    settings_obj = get_user_settings(user)
    now = timezone.now()
    settings_obj.is_enabled = True
    settings_obj.verified_at = now
    settings_obj.last_verified_at = now
    settings_obj.save(update_fields=["is_enabled", "verified_at", "last_verified_at", "updated_at"])
    return settings_obj


def due_for_login_challenge(settings_obj: TelegramTwoFactorSettings) -> bool:
    if not settings_obj.is_enabled or not settings_obj.telegram_chat_id:
        return False
    if settings_obj.frequency == TelegramTwoFactorSettings.FREQUENCY_ALWAYS:
        return True
    if not settings_obj.last_verified_at:
        return True

    days = {
        TelegramTwoFactorSettings.FREQUENCY_WEEK: 7,
        TelegramTwoFactorSettings.FREQUENCY_MONTH: 30,
        TelegramTwoFactorSettings.FREQUENCY_YEAR: 365,
    }.get(settings_obj.frequency, 7)
    return timezone.now() - settings_obj.last_verified_at >= timedelta(days=days)


def issue_login_challenge(user) -> dict:
    settings_obj = get_user_settings(user)
    challenge, code = create_challenge(
        user=user,
        purpose=TelegramTwoFactorChallenge.PURPOSE_LOGIN,
        telegram_username=settings_obj.telegram_username,
        telegram_chat_id=settings_obj.telegram_chat_id,
    )
    send_telegram_message(
        settings_obj.telegram_chat_id,
        f"Код входа DW Погода: {code}. Он действует 10 минут.",
    )
    challenge.sent_at = timezone.now()
    challenge.save(update_fields=["sent_at"])
    log.info("telegram_login_code_sent user_id=%s challenge_id=%s", user.pk, challenge.pk)
    return {
        "two_factor_required": True,
        "challenge_id": str(challenge.pk),
        "telegram_username": settings_obj.telegram_username,
        "telegram_bot_username": f"@{bot_username()}",
        "telegram_bot_url": bot_url(),
        "expires_at": challenge.expires_at,
    }


def complete_login_challenge(challenge_id: str, code: str):
    challenge = TelegramTwoFactorChallenge.objects.select_related("user").filter(
        pk=challenge_id,
        purpose=TelegramTwoFactorChallenge.PURPOSE_LOGIN,
        consumed_at__isnull=True,
    ).first()
    if not challenge or challenge.is_expired():
        raise Telegram2FAError("Код входа истёк или не найден.")
    user = challenge.user
    verify_challenge_code(challenge, code)
    settings_obj = get_user_settings(user)
    settings_obj.last_verified_at = timezone.now()
    settings_obj.save(update_fields=["last_verified_at", "updated_at"])
    return user


def user_from_telegram_username(telegram_username: str):
    username = normalize_telegram_username(telegram_username)
    User = get_user_model()
    settings_obj = TelegramTwoFactorSettings.objects.filter(telegram_username=username).first()
    return User.objects.filter(pk=settings_obj.user_id).first() if settings_obj else None
