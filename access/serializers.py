from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


User = get_user_model()


class UserRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ("id", "username", "password")
        read_only_fields = ("id",)

    def create(self, validated_data: dict[str, Any]):
        return User.objects.create_user(**validated_data)


class CustomTokenSerializer(TokenObtainPairSerializer):
    pass
