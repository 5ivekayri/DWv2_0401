from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient


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
