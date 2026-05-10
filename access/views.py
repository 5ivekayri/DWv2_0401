import logging

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
from rest_framework_simplejwt.views import TokenObtainPairView

from .serializers import (
    CustomTokenSerializer,
    PasswordChangeSerializer,
    TelegramTwoFactorLoginVerifySerializer,
    TelegramTwoFactorSettingsSerializer,
    TelegramTwoFactorSettingsUpdateSerializer,
    TelegramTwoFactorSetupStartResponseSerializer,
    TelegramTwoFactorSetupStartSerializer,
    TelegramTwoFactorSetupVerifySerializer,
    UserProfileSerializer,
    UserRegisterSerializer,
)
from .telegram_2fa import bot_url, bot_username, get_user_settings, serialize_settings

log = logging.getLogger("access.api")


class RegisterView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=UserRegisterSerializer, responses={201: UserRegisterSerializer})
    def post(self, request):
        serializer = UserRegisterSerializer(data=request.data)
        if not serializer.is_valid():
            log.warning(
                "signup_failed username=%s email=%s errors=%s",
                str(request.data.get("username", "")).strip(),
                str(request.data.get("email", "")).strip().lower(),
                serializer.errors,
            )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = serializer.save()
        log.info("signup_succeeded user_id=%s username=%s", user.pk, user.username)
        return Response({"id": user.pk, "username": user.username, "email": user.email}, status=status.HTTP_201_CREATED)


@extend_schema(request=CustomTokenSerializer)
class LoginView(TokenObtainPairView):
    permission_classes = [AllowAny]
    serializer_class = CustomTokenSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        identifier = str(request.data.get("identifier") or request.data.get("username") or "").strip()
        if isinstance(response.data, dict) and response.data.get("two_factor_required"):
            response.status_code = status.HTTP_202_ACCEPTED
        log.info("login_attempt_finished identifier=%s status=%s", identifier, response.status_code)
        return response


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: UserProfileSerializer})
    def get(self, request):
        return Response(UserProfileSerializer(request.user).data, status=status.HTTP_200_OK)

    @extend_schema(request=UserProfileSerializer, responses={200: UserProfileSerializer})
    def patch(self, request):
        serializer = UserProfileSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        log.info("profile_updated user_id=%s", user.pk)
        return Response(UserProfileSerializer(user).data, status=status.HTTP_200_OK)

    @extend_schema(responses={204: None})
    def delete(self, request):
        user_id = request.user.pk
        request.user.delete()
        log.info("profile_deleted user_id=%s", user_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=PasswordChangeSerializer, responses={200: None})
    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        log.info("password_changed user_id=%s", request.user.pk)
        return Response({"detail": "Password changed."}, status=status.HTTP_200_OK)


class TelegramTwoFactorSettingsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: TelegramTwoFactorSettingsSerializer})
    def get(self, request):
        return Response(serialize_settings(get_user_settings(request.user)), status=status.HTTP_200_OK)

    @extend_schema(request=TelegramTwoFactorSettingsUpdateSerializer, responses={200: TelegramTwoFactorSettingsSerializer})
    def patch(self, request):
        serializer = TelegramTwoFactorSettingsUpdateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        settings_obj = serializer.update_settings()
        log.info("telegram_2fa_settings_updated user_id=%s enabled=%s frequency=%s", request.user.pk, settings_obj.is_enabled, settings_obj.frequency)
        return Response(serialize_settings(settings_obj), status=status.HTTP_200_OK)


class TelegramTwoFactorSetupStartView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=TelegramTwoFactorSetupStartSerializer,
        responses={200: TelegramTwoFactorSetupStartResponseSerializer},
    )
    def post(self, request):
        serializer = TelegramTwoFactorSetupStartSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        settings_obj = serializer.save()
        log.info("telegram_2fa_setup_started user_id=%s telegram_username=%s", request.user.pk, settings_obj.telegram_username)
        return Response(
            {
                "detail": "Open the Telegram bot and send any message to receive a verification code.",
                "telegram_bot_username": f"@{bot_username()}",
                "telegram_bot_url": bot_url(),
                "telegram_2fa": serialize_settings(settings_obj),
            },
            status=status.HTTP_200_OK,
        )


class TelegramTwoFactorSetupVerifyView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=TelegramTwoFactorSetupVerifySerializer, responses={200: TelegramTwoFactorSettingsSerializer})
    def post(self, request):
        serializer = TelegramTwoFactorSetupVerifySerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        settings_obj = serializer.save()
        log.info("telegram_2fa_setup_verified user_id=%s", request.user.pk)
        return Response(serialize_settings(settings_obj), status=status.HTTP_200_OK)


class TelegramTwoFactorLoginVerifyView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=TelegramTwoFactorLoginVerifySerializer, responses={200: None})
    def post(self, request):
        serializer = TelegramTwoFactorLoginVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tokens = serializer.create_tokens()
        log.info("telegram_2fa_login_verified user_id=%s", serializer.user.pk)
        return Response(tokens, status=status.HTTP_200_OK)
