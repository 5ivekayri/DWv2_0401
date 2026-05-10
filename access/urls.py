from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    LoginView,
    PasswordChangeView,
    ProfileView,
    RegisterView,
    TelegramTwoFactorLoginVerifyView,
    TelegramTwoFactorSettingsView,
    TelegramTwoFactorSetupStartView,
    TelegramTwoFactorSetupVerifyView,
)


urlpatterns = [
    path("signup/", RegisterView.as_view(), name="register"),
    path("register/", RegisterView.as_view(), name="register_alias"),
    path("login/", LoginView.as_view(), name="login"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("password/change/", PasswordChangeView.as_view(), name="password_change"),
    path("telegram/2fa/", TelegramTwoFactorSettingsView.as_view(), name="telegram_2fa_settings"),
    path("telegram/2fa/setup/start/", TelegramTwoFactorSetupStartView.as_view(), name="telegram_2fa_setup_start"),
    path("telegram/2fa/setup/verify/", TelegramTwoFactorSetupVerifyView.as_view(), name="telegram_2fa_setup_verify"),
    path("telegram/2fa/login/verify/", TelegramTwoFactorLoginVerifyView.as_view(), name="telegram_2fa_login_verify"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
]
