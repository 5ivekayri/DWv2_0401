from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


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
        return super().validate(attrs)
