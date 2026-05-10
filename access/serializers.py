from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from drf_spectacular.utils import extend_schema_field

from .models import TelegramTwoFactorSettings
from .telegram_2fa import (
    Telegram2FAError,
    TelegramBotNotConfigured,
    bot_url,
    complete_login_challenge,
    due_for_login_challenge,
    get_user_settings,
    issue_login_challenge,
    serialize_settings,
    start_setup,
    verify_setup,
)


User = get_user_model()


class UserRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    email = serializers.EmailField(required=True)

    class Meta:
        model = User
        fields = ("id", "username", "email", "password")
        read_only_fields = ("id",)

    def create(self, validated_data: dict[str, Any]):
        return User.objects.create_user(**validated_data)

    def validate_email(self, value: str) -> str:
        email = value.strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return email


class UserProfileSerializer(serializers.ModelSerializer):
    groups = serializers.SerializerMethodField()
    telegram_2fa = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "username", "email", "is_staff", "is_superuser", "groups", "telegram_2fa")
        read_only_fields = ("id", "is_staff", "is_superuser", "groups", "telegram_2fa")

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_groups(self, obj):
        return list(obj.groups.values_list("name", flat=True))

    @extend_schema_field(serializers.DictField())
    def get_telegram_2fa(self, obj):
        return serialize_settings(get_user_settings(obj))

    def validate_email(self, value: str) -> str:
        email = value.strip().lower()
        queryset = User.objects.filter(email__iexact=email)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return email

    def validate_username(self, value: str) -> str:
        username = value.strip()
        queryset = User.objects.filter(username__iexact=username)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("A user with this username already exists.")
        return username


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate_current_password(self, value: str) -> str:
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user


class CustomTokenSerializer(TokenObtainPairSerializer):
    username = serializers.CharField(required=False)
    identifier = serializers.CharField(required=False, write_only=True)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields[self.username_field].required = False

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        identifier = str(attrs.pop("identifier", "")).strip()
        if identifier and not attrs.get(self.username_field):
            attrs[self.username_field] = identifier

        if not attrs.get(self.username_field):
            raise serializers.ValidationError({self.username_field: "This field is required."})

        username = str(attrs.get(self.username_field, "")).strip()
        if "@" in username:
            user = User.objects.filter(email__iexact=username).only("username").first()
            if user:
                attrs[self.username_field] = user.username
        data = super().validate(attrs)
        two_factor_settings = get_user_settings(self.user)
        if due_for_login_challenge(two_factor_settings):
            try:
                return issue_login_challenge(self.user)
            except TelegramBotNotConfigured as exc:
                raise serializers.ValidationError(
                    {"telegram_2fa": "Telegram bot token is not configured on the server."}
                ) from exc
            except Telegram2FAError as exc:
                raise serializers.ValidationError({"telegram_2fa": str(exc)}) from exc
        return data


class TelegramTwoFactorSettingsSerializer(serializers.Serializer):
    telegram_username = serializers.CharField(required=False, allow_blank=True)
    telegram_bot_username = serializers.CharField(read_only=True)
    telegram_bot_url = serializers.URLField(read_only=True)
    is_enabled = serializers.BooleanField(required=False)
    is_linked = serializers.BooleanField(read_only=True)
    frequency = serializers.ChoiceField(
        choices=[choice[0] for choice in TelegramTwoFactorSettings.FREQUENCY_CHOICES],
        required=False,
    )
    verified_at = serializers.DateTimeField(read_only=True, allow_null=True)
    last_verified_at = serializers.DateTimeField(read_only=True, allow_null=True)


class TelegramTwoFactorSetupStartSerializer(serializers.Serializer):
    telegram_username = serializers.CharField(max_length=64)

    def validate_telegram_username(self, value: str) -> str:
        username = value.strip().lstrip("@")
        if not username:
            raise serializers.ValidationError("Telegram username is required.")
        return username

    def save(self, **kwargs):
        return start_setup(self.context["request"].user, self.validated_data["telegram_username"])


class TelegramTwoFactorSetupVerifySerializer(serializers.Serializer):
    code = serializers.CharField(min_length=4, max_length=12)

    def save(self, **kwargs):
        try:
            return verify_setup(self.context["request"].user, self.validated_data["code"])
        except Telegram2FAError as exc:
            raise serializers.ValidationError({"code": str(exc)}) from exc


class TelegramTwoFactorSettingsUpdateSerializer(serializers.Serializer):
    is_enabled = serializers.BooleanField(required=False)
    frequency = serializers.ChoiceField(
        choices=[choice[0] for choice in TelegramTwoFactorSettings.FREQUENCY_CHOICES],
        required=False,
    )

    def update_settings(self):
        settings_obj = get_user_settings(self.context["request"].user)
        if "frequency" in self.validated_data:
            settings_obj.frequency = self.validated_data["frequency"]
        if "is_enabled" in self.validated_data:
            next_enabled = self.validated_data["is_enabled"]
            if next_enabled and not (settings_obj.telegram_chat_id and settings_obj.verified_at):
                raise serializers.ValidationError({"is_enabled": "Telegram must be linked before enabling 2FA."})
            settings_obj.is_enabled = next_enabled
        settings_obj.save(update_fields=["frequency", "is_enabled", "updated_at"])
        return settings_obj


class TelegramTwoFactorLoginVerifySerializer(serializers.Serializer):
    challenge_id = serializers.UUIDField()
    code = serializers.CharField(min_length=4, max_length=12)

    def validate(self, attrs):
        try:
            self.user = complete_login_challenge(str(attrs["challenge_id"]), attrs["code"])
        except Telegram2FAError as exc:
            raise serializers.ValidationError({"code": str(exc)}) from exc
        return attrs

    def create_tokens(self) -> dict[str, str]:
        refresh = RefreshToken.for_user(self.user)
        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        }


class TelegramTwoFactorSetupStartResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()
    telegram_bot_username = serializers.CharField()
    telegram_bot_url = serializers.URLField()
    telegram_2fa = TelegramTwoFactorSettingsSerializer()


class TelegramTwoFactorLoginChallengeSerializer(serializers.Serializer):
    two_factor_required = serializers.BooleanField()
    challenge_id = serializers.UUIDField()
    telegram_username = serializers.CharField()
    telegram_bot_username = serializers.CharField()
    telegram_bot_url = serializers.URLField(default=bot_url)
    expires_at = serializers.DateTimeField()
