from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TelegramTwoFactorSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("telegram_username", models.CharField(blank=True, db_index=True, max_length=64)),
                ("telegram_chat_id", models.CharField(blank=True, max_length=64)),
                ("is_enabled", models.BooleanField(default=False)),
                (
                    "frequency",
                    models.CharField(
                        choices=[
                            ("always", "Always"),
                            ("week", "Once a week"),
                            ("month", "Once a month"),
                            ("year", "Once a year"),
                        ],
                        default="week",
                        max_length=16,
                    ),
                ),
                ("setup_requested_at", models.DateTimeField(blank=True, null=True)),
                ("verified_at", models.DateTimeField(blank=True, null=True)),
                ("last_verified_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="telegram_2fa",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Telegram 2FA settings",
                "verbose_name_plural": "Telegram 2FA settings",
            },
        ),
        migrations.CreateModel(
            name="TelegramTwoFactorChallenge",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("purpose", models.CharField(choices=[("setup", "Setup"), ("login", "Login")], max_length=16)),
                ("code_hash", models.CharField(max_length=256)),
                ("telegram_username", models.CharField(blank=True, max_length=64)),
                ("telegram_chat_id", models.CharField(blank=True, max_length=64)),
                ("expires_at", models.DateTimeField()),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="telegram_2fa_challenges",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="telegramtwofactorchallenge",
            index=models.Index(fields=["user", "purpose", "created_at"], name="access_tele_user_id_e2906e_idx"),
        ),
        migrations.AddIndex(
            model_name="telegramtwofactorchallenge",
            index=models.Index(fields=["telegram_username", "purpose", "created_at"], name="access_tele_telegra_50f309_idx"),
        ),
    ]
