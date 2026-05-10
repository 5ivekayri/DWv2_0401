from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone


class TelegramTwoFactorSettings(models.Model):
    FREQUENCY_ALWAYS = "always"
    FREQUENCY_WEEK = "week"
    FREQUENCY_MONTH = "month"
    FREQUENCY_YEAR = "year"
    FREQUENCY_CHOICES = (
        (FREQUENCY_ALWAYS, "Always"),
        (FREQUENCY_WEEK, "Once a week"),
        (FREQUENCY_MONTH, "Once a month"),
        (FREQUENCY_YEAR, "Once a year"),
    )

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="telegram_2fa")
    telegram_username = models.CharField(max_length=64, blank=True, db_index=True)
    telegram_chat_id = models.CharField(max_length=64, blank=True)
    is_enabled = models.BooleanField(default=False)
    frequency = models.CharField(max_length=16, choices=FREQUENCY_CHOICES, default=FREQUENCY_WEEK)
    setup_requested_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Telegram 2FA settings"
        verbose_name_plural = "Telegram 2FA settings"

    def __str__(self) -> str:
        return f"{self.user_id}:{self.telegram_username or 'telegram-not-linked'}"


class TelegramTwoFactorChallenge(models.Model):
    PURPOSE_SETUP = "setup"
    PURPOSE_LOGIN = "login"
    PURPOSE_CHOICES = (
        (PURPOSE_SETUP, "Setup"),
        (PURPOSE_LOGIN, "Login"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="telegram_2fa_challenges")
    purpose = models.CharField(max_length=16, choices=PURPOSE_CHOICES)
    code_hash = models.CharField(max_length=256)
    telegram_username = models.CharField(max_length=64, blank=True)
    telegram_chat_id = models.CharField(max_length=64, blank=True)
    expires_at = models.DateTimeField()
    sent_at = models.DateTimeField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "purpose", "created_at"]),
            models.Index(fields=["telegram_username", "purpose", "created_at"]),
        ]
        ordering = ("-created_at",)

    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    def is_active(self) -> bool:
        return self.consumed_at is None and not self.is_expired()

    def verify_code(self, code: str) -> bool:
        return check_password(str(code).strip(), self.code_hash)

    @classmethod
    def hash_code(cls, code: str) -> str:
        return make_password(str(code).strip())
