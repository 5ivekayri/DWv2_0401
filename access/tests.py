from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from access.management.commands.telegram_2fa_bot import Command as Telegram2FABotCommand
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import TelegramTwoFactorChallenge, TelegramTwoFactorSettings
from .telegram_2fa import send_setup_code_for_telegram_user


class AuthApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_signup_and_login_by_username_email_or_identifier(self):
        signup = self.client.post(
            "/api/auth/signup/",
            {
                "username": "frontend_user",
                "email": "frontend@example.com",
                "password": "password123",
            },
            format="json",
        )

        self.assertEqual(signup.status_code, 201)
        self.assertEqual(signup.data["email"], "frontend@example.com")

        by_username = self.client.post(
            "/api/auth/login/",
            {"username": "frontend_user", "password": "password123"},
            format="json",
        )
        by_email = self.client.post(
            "/api/auth/login/",
            {"username": "frontend@example.com", "password": "password123"},
            format="json",
        )
        by_identifier = self.client.post(
            "/api/auth/login/",
            {"identifier": "frontend@example.com", "password": "password123"},
            format="json",
        )

        self.assertEqual(by_username.status_code, 200)
        self.assertEqual(by_email.status_code, 200)
        self.assertEqual(by_identifier.status_code, 200)
        self.assertIn("access", by_username.data)

    def test_signup_rejects_duplicate_email(self):
        payload = {
            "username": "first_user",
            "email": "same@example.com",
            "password": "password123",
        }
        self.client.post("/api/auth/signup/", payload, format="json")

        duplicate = self.client.post(
            "/api/auth/signup/",
            {**payload, "username": "second_user"},
            format="json",
        )

        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("email", duplicate.data)

    def test_register_alias_creates_user(self):
        response = self.client.post(
            "/api/auth/register/",
            {
                "username": "register_alias_user",
                "email": "register-alias@example.com",
                "password": "password123",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["username"], "register_alias_user")

    def test_profile_requires_auth_and_can_update_user_fields(self):
        signup = self.client.post(
            "/api/auth/signup/",
            {
                "username": "profile_user",
                "email": "profile@example.com",
                "password": "password123",
            },
            format="json",
        )
        self.assertEqual(signup.status_code, 201)

        anonymous = self.client.get("/api/auth/profile/")
        self.assertEqual(anonymous.status_code, 401)

        login = self.client.post(
            "/api/auth/login/",
            {"username": "profile_user", "password": "password123"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        profile = self.client.get("/api/auth/profile/")
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.data["email"], "profile@example.com")
        self.assertFalse(profile.data["is_staff"])
        self.assertEqual(profile.data["telegram_2fa"]["telegram_bot_username"], "@darkweather_2fa_bot")
        self.assertFalse(profile.data["telegram_2fa"]["is_enabled"])

        updated = self.client.patch(
            "/api/auth/profile/",
            {"username": "profile_user_next", "email": "profile-next@example.com"},
            format="json",
        )

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.data["username"], "profile_user_next")
        self.assertEqual(updated.data["email"], "profile-next@example.com")

    def test_password_change_requires_current_password(self):
        self.client.post(
            "/api/auth/signup/",
            {
                "username": "password_user",
                "email": "password@example.com",
                "password": "password123",
            },
            format="json",
        )
        login = self.client.post(
            "/api/auth/login/",
            {"username": "password_user", "password": "password123"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        rejected = self.client.post(
            "/api/auth/password/change/",
            {"current_password": "bad-password", "new_password": "newpassword123"},
            format="json",
        )
        self.assertEqual(rejected.status_code, 400)

        changed = self.client.post(
            "/api/auth/password/change/",
            {"current_password": "password123", "new_password": "newpassword123"},
            format="json",
        )
        self.assertEqual(changed.status_code, 200)

        relogin = self.client.post(
            "/api/auth/login/",
            {"username": "password_user", "password": "newpassword123"},
            format="json",
        )
        self.assertEqual(relogin.status_code, 200)

    def test_profile_can_delete_own_account(self):
        self.client.post(
            "/api/auth/signup/",
            {
                "username": "delete_user",
                "email": "delete@example.com",
                "password": "password123",
            },
            format="json",
        )
        login = self.client.post(
            "/api/auth/login/",
            {"username": "delete_user", "password": "password123"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        deleted = self.client.delete("/api/auth/profile/")

        self.assertEqual(deleted.status_code, 204)
        relogin = self.client.post(
            "/api/auth/login/",
            {"username": "delete_user", "password": "password123"},
            format="json",
        )
        self.assertEqual(relogin.status_code, 401)

    def test_telegram_2fa_setup_verify_and_disable(self):
        self.client.post(
            "/api/auth/signup/",
            {
                "username": "telegram_user",
                "email": "telegram@example.com",
                "password": "password123",
            },
            format="json",
        )
        login = self.client.post(
            "/api/auth/login/",
            {"username": "telegram_user", "password": "password123"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        started = self.client.post(
            "/api/auth/telegram/2fa/setup/start/",
            {"telegram_username": "@darkweather_user"},
            format="json",
        )
        self.assertEqual(started.status_code, 200)
        self.assertEqual(started.data["telegram_2fa"]["telegram_username"], "darkweather_user")
        self.assertFalse(started.data["telegram_2fa"]["is_enabled"])

        user = get_user_model().objects.get(username="telegram_user")
        settings_obj = TelegramTwoFactorSettings.objects.get(user=user)
        settings_obj.telegram_chat_id = "123456"
        settings_obj.save(update_fields=["telegram_chat_id"])
        TelegramTwoFactorChallenge.objects.create(
            user=user,
            purpose=TelegramTwoFactorChallenge.PURPOSE_SETUP,
            code_hash=TelegramTwoFactorChallenge.hash_code("123456"),
            telegram_username="darkweather_user",
            telegram_chat_id="123456",
            expires_at=timezone.now() + timedelta(minutes=10),
        )

        verified = self.client.post(
            "/api/auth/telegram/2fa/setup/verify/",
            {"code": "123456"},
            format="json",
        )
        self.assertEqual(verified.status_code, 200)
        self.assertTrue(verified.data["is_enabled"])
        self.assertTrue(verified.data["is_linked"])

        disabled = self.client.patch(
            "/api/auth/telegram/2fa/",
            {"is_enabled": False, "frequency": "month"},
            format="json",
        )
        self.assertEqual(disabled.status_code, 200)
        self.assertFalse(disabled.data["is_enabled"])
        self.assertEqual(disabled.data["frequency"], "month")

    @patch("access.telegram_2fa.send_telegram_message")
    @patch("access.telegram_2fa.generate_code", return_value="111222")
    def test_telegram_bot_message_sends_setup_code(self, _generate_code, send_message):
        self.client.post(
            "/api/auth/signup/",
            {
                "username": "telegram_bot_user",
                "email": "telegram-bot@example.com",
                "password": "password123",
            },
            format="json",
        )
        login = self.client.post(
            "/api/auth/login/",
            {"username": "telegram_bot_user", "password": "password123"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        self.client.post(
            "/api/auth/telegram/2fa/setup/start/",
            {"telegram_username": "@darkweather_user"},
            format="json",
        )

        challenge = send_setup_code_for_telegram_user("@darkweather_user", "777")

        self.assertIsNotNone(challenge)
        self.assertEqual(challenge.telegram_chat_id, "777")
        self.assertIsNotNone(challenge.sent_at)
        settings_obj = TelegramTwoFactorSettings.objects.get(user__username="telegram_bot_user")
        self.assertEqual(settings_obj.telegram_chat_id, "777")
        send_message.assert_called_once()
        self.assertEqual(send_message.call_args.args[0], "777")
        self.assertIn("111222", send_message.call_args.args[1])

        verified = self.client.post(
            "/api/auth/telegram/2fa/setup/verify/",
            {"code": "111222"},
            format="json",
        )
        self.assertEqual(verified.status_code, 200)
        self.assertTrue(verified.data["is_enabled"])

    @patch("access.management.commands.telegram_2fa_bot.send_setup_code_for_telegram_user")
    def test_telegram_bot_command_handles_message_update(self, send_setup_code):
        send_setup_code.return_value = None
        command = Telegram2FABotCommand()
        command._handle_update(
            {
                "update_id": 10,
                "message": {
                    "from": {"username": "darkweather_user"},
                    "chat": {"id": 777},
                    "text": "/start",
                },
            }
        )

        send_setup_code.assert_called_once_with("darkweather_user", "777")

    @patch("access.telegram_2fa.send_telegram_message")
    @patch("access.telegram_2fa.generate_code", return_value="654321")
    def test_login_requires_telegram_2fa_when_due(self, _generate_code, send_message):
        self.client.post(
            "/api/auth/signup/",
            {
                "username": "login_2fa_user",
                "email": "login-2fa@example.com",
                "password": "password123",
            },
            format="json",
        )
        user = get_user_model().objects.get(username="login_2fa_user")
        TelegramTwoFactorSettings.objects.create(
            user=user,
            telegram_username="login_2fa",
            telegram_chat_id="987654",
            is_enabled=True,
            frequency=TelegramTwoFactorSettings.FREQUENCY_ALWAYS,
            verified_at=timezone.now(),
        )

        login = self.client.post(
            "/api/auth/login/",
            {"username": "login_2fa_user", "password": "password123"},
            format="json",
        )
        self.assertEqual(login.status_code, 202)
        self.assertTrue(login.data["two_factor_required"])
        self.assertIn("challenge_id", login.data)
        send_message.assert_called_once()

        verified = self.client.post(
            "/api/auth/telegram/2fa/login/verify/",
            {"challenge_id": login.data["challenge_id"], "code": "654321"},
            format="json",
        )
        self.assertEqual(verified.status_code, 200)
        self.assertIn("access", verified.data)
