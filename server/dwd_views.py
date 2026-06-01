from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import OpenApiResponse, OpenApiTypes, extend_schema, extend_schema_field, inline_serializer

from server.models import (
    DWDDevice,
    DWDDeviceEvent,
    DWDNotification,
    DWDProviderApplication,
    DWDProvisioning,
    DWDSupportMessage,
    SystemEvent,
)
from server.monitoring import record_system_event, utc_iso


PROVIDER_GROUP_NAME = "provider"
MQTT_TOPIC_PREFIX = "darkweather/stations"

FIRMWARE_INSTRUCTION_TEMPLATES = {
    DWDProvisioning.FIRMWARE_SERIAL_BRIDGE: (
        "1. Open Arduino IDE.\n"
        "2. Paste the serial bridge firmware code.\n"
        "3. Select the correct board and serial port.\n"
        "4. Click Upload and wait until flashing finishes.\n"
        "5. Connect the board to the bridge host and verify telemetry in DWv2."
    ),
    DWDProvisioning.FIRMWARE_ESP01_WIFI: (
        "1. Open Arduino IDE.\n"
        "2. Paste the ESP-01 Wi-Fi firmware code.\n"
        "3. Fill Wi-Fi credentials and DWv2 device settings.\n"
        "4. Select the correct ESP-01 board/upload mode.\n"
        "5. Upload the firmware and reboot the module.\n"
        "6. Verify that readings reach DWv2 over the configured network."
    ),
    DWDProvisioning.FIRMWARE_ETHERNET_SHIELD: (
        "1. Open Arduino IDE and paste the Ethernet shield firmware code.\n"
        "2. Check network settings: MAC, IP mode, gateway and DWv2 endpoint.\n"
        "3. Select the correct Arduino board.\n"
        "4. Upload the firmware.\n"
        "5. Connect Ethernet and verify telemetry in DWv2."
    ),
}


ERROR_RESPONSE = inline_serializer(
    name="DWDErrorResponse",
    fields={"detail": serializers.CharField()},
)

USER_SUMMARY_RESPONSE = inline_serializer(
    name="DWDUserSummary",
    fields={
        "id": serializers.IntegerField(),
        "username": serializers.CharField(),
        "email": serializers.EmailField(allow_blank=True),
    },
)


def dwd_responses(success_schema: Any | None = None, *, created_schema: Any | None = None) -> dict[int, Any]:
    responses: dict[int, Any] = {
        400: ERROR_RESPONSE,
        401: OpenApiResponse(description="Authentication credentials were not provided."),
        403: OpenApiResponse(description="Authenticated user is not allowed to perform this action."),
        500: ERROR_RESPONSE,
    }
    if success_schema is not None:
        responses[200] = success_schema
    else:
        responses[200] = OpenApiResponse(description="OK")
    if created_schema is not None:
        responses[201] = created_schema
    return responses


def user_payload(user) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": user.pk,
        "username": user.get_username(),
        "email": getattr(user, "email", ""),
    }


def get_user_role(user) -> str:
    if user.is_staff or user.is_superuser:
        return "admin"
    if user.groups.filter(name=PROVIDER_GROUP_NAME).exists():
        return "provider"
    return "user"


def set_user_role(user, role: str) -> None:
    provider_group, _created = Group.objects.get_or_create(name=PROVIDER_GROUP_NAME)
    user.groups.remove(provider_group)

    if role == "admin":
        user.is_staff = True
    elif role == "provider":
        user.is_staff = False
        user.groups.add(provider_group)
    else:
        user.is_staff = False
    user.save(update_fields=["is_staff"])


def mask_token(token: str) -> str:
    if not token:
        return ""
    if len(token) <= 8:
        return "****"
    return f"{token[:4]}...{token[-4:]}"


def device_online_status(device: DWDDevice) -> str:
    if not device.is_enabled or device.status == DWDDevice.STATUS_BLOCKED:
        return "offline"
    if device.last_seen_at is None:
        return "offline"
    offline_after = int(getattr(settings, "IOT_OFFLINE_AFTER_SECONDS", 3600))
    return "online" if timezone.now() - device.last_seen_at <= timedelta(seconds=offline_after) else "offline"


def record_device_event(
    *,
    device: DWDDevice,
    event_type: str,
    severity: str = DWDDeviceEvent.SEVERITY_INFO,
    message: str = "",
    ip_address: str | None = None,
) -> None:
    DWDDeviceEvent.objects.create(
        device=device,
        event_type=event_type,
        severity=severity,
        message=message,
        ip_address=ip_address,
    )


def notify_user(
    recipient,
    *,
    notification_type: str,
    title: str,
    message: str = "",
    application: DWDProviderApplication | None = None,
    device: DWDDevice | None = None,
    provisioning: DWDProvisioning | None = None,
) -> DWDNotification | None:
    if recipient is None:
        return None
    return DWDNotification.objects.create(
        recipient=recipient,
        notification_type=notification_type,
        title=title,
        message=message,
        application=application,
        device=device,
        provisioning=provisioning,
    )


def notify_admins(
    *,
    notification_type: str,
    title: str,
    message: str = "",
    application: DWDProviderApplication | None = None,
    device: DWDDevice | None = None,
    provisioning: DWDProvisioning | None = None,
    exclude_user_id: int | None = None,
) -> None:
    User = get_user_model()
    admins = User.objects.filter(is_staff=True)
    if exclude_user_id:
        admins = admins.exclude(pk=exclude_user_id)
    for admin_user in admins.distinct():
        notify_user(
            admin_user,
            notification_type=notification_type,
            title=title,
            message=message,
            application=application,
            device=device,
            provisioning=provisioning,
        )


def c_string(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")


def mqtt_public_host(request=None) -> str:
    configured = str(getattr(settings, "DWD_MQTT_PUBLIC_HOST", "") or "").strip()
    if configured:
        return configured
    if request is not None:
        host = request.get_host().split(":")[0]
        if host and host not in {"testserver", "localhost", "127.0.0.1", "0.0.0.0"}:
            return host
    return str(getattr(settings, "MQTT_HOST", "127.0.0.1") or "127.0.0.1").strip()


def generate_mqtt_wifi_firmware(
    *,
    device: DWDDevice | None,
    firmware_version: str,
    wifi_ssid: str = "",
    wifi_password: str = "",
    request=None,
) -> str:
    station_id = device.station_id if device else "PUT_STATION_ID_HERE"
    mqtt_topic = f"{MQTT_TOPIC_PREFIX}/{station_id}/readings"
    mqtt_username = str(getattr(settings, "MQTT_USERNAME", "") or "")
    mqtt_password = str(getattr(settings, "MQTT_PASSWORD", "") or "")
    mqtt_host = mqtt_public_host(request)
    mqtt_port = int(getattr(settings, "MQTT_PORT", 1883) or 1883)
    ssid_value = wifi_ssid or "PUT_WIFI_SSID_HERE"
    password_value = wifi_password or "PUT_WIFI_PASSWORD_HERE"

    return f"""// Dark Weather MQTT WiFi firmware
// Firmware version: {c_string(firmware_version or "1.0.0")}
// Station ID: {c_string(station_id)}
// Wi-Fi fields are optional in the admin panel. If placeholders are present, fill them before upload.

#include <WiFiS3.h>
#include <ArduinoMqttClient.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <DHT.h>

#define DHTPIN 2
#define DHTTYPE DHT11

#define READ_INTERVAL_MS 2000UL
#define SEND_INTERVAL_MS 10000UL
#define SCREEN_INTERVAL_MS 5000UL

const char* WIFI_SSID = "{c_string(ssid_value)}";
const char* WIFI_PASSWORD = "{c_string(password_value)}";

const char* MQTT_HOST = "{c_string(mqtt_host)}";
const int MQTT_PORT = {mqtt_port};

const char* STATION_ID = "{c_string(station_id)}";
const char* MQTT_TOPIC = "{c_string(mqtt_topic)}";

const char* MQTT_USERNAME = "{c_string(mqtt_username)}";
const char* MQTT_PASSWORD = "{c_string(mqtt_password)}";

DHT dht(DHTPIN, DHTTYPE);
LiquidCrystal_I2C lcd(0x27, 16, 2);

WiFiClient wifiClient;
MqttClient mqttClient(wifiClient);

float lastTemperature = NAN;
float lastHumidity = NAN;

unsigned long lastReadMs = 0;
unsigned long lastSendMs = 0;
unsigned long lastScreenMs = 0;

bool showInfoScreen = false;

char lastStatus[17] = "Booting";
int lastMqttCode = 0;

void setup() {{
  Serial.begin(9600);
  delay(1500);

  dht.begin();

  lcd.init();
  lcd.backlight();

  lcd.setCursor(0, 0);
  lcd.print("DWD R4 MQTT");
  lcd.setCursor(0, 1);
  lcd.print("Starting...");
  delay(1500);
  lcd.clear();

  connectWiFi();
  connectMqtt();
}}

void loop() {{
  unsigned long now = millis();

  if (WiFi.status() != WL_CONNECTED) {{
    setStatus("WiFi lost");
    connectWiFi();
  }}

  if (!mqttClient.connected()) {{
    setStatus("MQTT lost");
    connectMqtt();
  }}

  mqttClient.poll();

  if (now - lastReadMs >= READ_INTERVAL_MS) {{
    lastReadMs = now;
    readSensor();
  }}

  if (now - lastScreenMs >= SCREEN_INTERVAL_MS) {{
    lastScreenMs = now;
    showInfoScreen = !showInfoScreen;
    updateLCD();
  }}

  if (!isnan(lastTemperature) && !isnan(lastHumidity)) {{
    if (lastSendMs == 0 || now - lastSendMs >= SEND_INTERVAL_MS) {{
      lastSendMs = now;
      publishReading(lastTemperature, (int)lastHumidity);
      updateLCD();
    }}
  }}
}}

void connectWiFi() {{
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("WiFi connect");
  lcd.setCursor(0, 1);
  lcd.print(WIFI_SSID);

  Serial.print("Connecting to WiFi: ");
  Serial.println(WIFI_SSID);

  while (WiFi.begin(WIFI_SSID, WIFI_PASSWORD) != WL_CONNECTED) {{
    Serial.print(".");
    setStatus("WiFi wait");
    delay(2000);
  }}

  Serial.println();
  Serial.println("WiFi connected");
  Serial.print("Arduino IP: ");
  Serial.println(WiFi.localIP());

  setStatus("WiFi OK");

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("WiFi OK");
  lcd.setCursor(0, 1);
  lcd.print(WiFi.localIP());
  delay(2000);
}}

void connectMqtt() {{
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("MQTT connect");
  lcd.setCursor(0, 1);
  lcd.print(MQTT_HOST);

  Serial.print("Connecting to MQTT: ");
  Serial.print(MQTT_HOST);
  Serial.print(":");
  Serial.println(MQTT_PORT);

  if (strlen(MQTT_USERNAME) > 0) {{
    mqttClient.setUsernamePassword(MQTT_USERNAME, MQTT_PASSWORD);
  }}

  while (!mqttClient.connect(MQTT_HOST, MQTT_PORT)) {{
    Serial.print("MQTT failed, error code: ");
    Serial.println(mqttClient.connectError());

    setStatus("MQTT wait");
    lastMqttCode = mqttClient.connectError();
    updateLCD();

    delay(3000);
  }}

  Serial.println("MQTT connected");
  setStatus("MQTT OK");
  lastMqttCode = 0;

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("MQTT OK");
  lcd.setCursor(0, 1);
  lcd.print(MQTT_TOPIC);
  delay(1500);
}}

void readSensor() {{
  float humidity = dht.readHumidity();
  float temperature = dht.readTemperature();

  if (isnan(humidity) || isnan(temperature)) {{
    setStatus("DHT error");
    Serial.println("{{\\"error\\":\\"dht_read_failed\\"}}");
    updateLCD();
    return;
  }}

  lastTemperature = temperature;
  lastHumidity = humidity;

  Serial.print("{{\\"temperature_c\\":");
  Serial.print(temperature, 1);
  Serial.print(",\\"humidity\\":");
  Serial.print(humidity, 0);
  Serial.println(",\\"source\\":\\"mqtt\\"}}");
}}

void publishReading(float temperatureC, int humidity) {{
  char body[160];

  snprintf(
    body,
    sizeof(body),
    "{{\\"station_id\\":\\"%s\\",\\"temperature_c\\":%.1f,\\"humidity\\":%d}}",
    STATION_ID,
    temperatureC,
    humidity
  );

  Serial.println("Publishing MQTT:");
  Serial.println(MQTT_TOPIC);
  Serial.println(body);

  if (!mqttClient.connected()) {{
    connectMqtt();
  }}

  setStatus("Publishing");
  updateLCD();

  mqttClient.beginMessage(MQTT_TOPIC);
  mqttClient.print(body);
  int result = mqttClient.endMessage();

  if (result == 1) {{
    setStatus("MQTT sent");
    lastMqttCode = 0;
  }} else {{
    setStatus("MQTT error");
    lastMqttCode = result;
  }}

  Serial.print("MQTT publish result: ");
  Serial.println(result);
}}

void updateLCD() {{
  lcd.clear();

  if (!showInfoScreen) {{
    if (isnan(lastTemperature) || isnan(lastHumidity)) {{
      lcd.setCursor(0, 0);
      lcd.print("Sensor wait");
      lcd.setCursor(0, 1);
      lcd.print(lastStatus);
      return;
    }}

    lcd.setCursor(0, 0);
    lcd.print("Temp: ");
    lcd.print(lastTemperature, 1);
    lcd.print((char)223);
    lcd.print("C");

    lcd.setCursor(0, 1);
    lcd.print("Hum:  ");
    lcd.print(lastHumidity, 0);
    lcd.print("%");
  }} else {{
    lcd.setCursor(0, 0);
    lcd.print("IP:");
    lcd.print(WiFi.localIP());

    lcd.setCursor(0, 1);

    if (lastMqttCode != 0) {{
      lcd.print("MQ:");
      lcd.print(lastMqttCode);
      lcd.print(" ");
    }}

    lcd.print(lastStatus);
  }}
}}

void setStatus(const char* status) {{
  strncpy(lastStatus, status, sizeof(lastStatus));
  lastStatus[sizeof(lastStatus) - 1] = '\\0';
}}
"""


class DWDUserAdminSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    active_application = serializers.SerializerMethodField()
    device_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = get_user_model()
        fields = ("id", "username", "email", "date_joined", "role", "is_staff", "is_superuser", "active_application", "device_count")

    @extend_schema_field(OpenApiTypes.STR)
    def get_role(self, obj):
        return get_user_role(obj)

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_active_application(self, obj):
        application = obj.dwd_provider_applications.order_by("-created_at", "-id").first()
        if application is None:
            return None
        return {
            "id": application.id,
            "city": application.city,
            "email": application.email,
            "status": application.status,
        }


class DWDUserRoleUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["user", "provider", "admin"])


class DWDDeviceSerializer(serializers.ModelSerializer):
    owner = serializers.SerializerMethodField()
    application_id = serializers.IntegerField(source="application.id", allow_null=True, read_only=True)
    owner_email = serializers.EmailField(source="owner.email", read_only=True)
    online_status = serializers.SerializerMethodField()
    provisioning_status = serializers.SerializerMethodField()
    instruction_text = serializers.SerializerMethodField()
    firmware_code = serializers.SerializerMethodField()
    instruction_sent = serializers.SerializerMethodField()
    instruction_sent_at = serializers.SerializerMethodField()
    instruction_sent_by = serializers.SerializerMethodField()
    token_masked = serializers.SerializerMethodField()

    class Meta:
        model = DWDDevice
        fields = (
            "id",
            "device_code",
            "station_id",
            "owner",
            "owner_email",
            "application_id",
            "city",
            "country",
            "region",
            "address_comment",
            "firmware_type",
            "firmware_version",
            "ip_address",
            "last_seen_at",
            "last_request_at",
            "last_data_at",
            "status",
            "is_enabled",
            "online_status",
            "token_masked",
            "notes",
            "last_error",
            "last_error_at",
            "provisioning_status",
            "instruction_text",
            "firmware_code",
            "instruction_sent",
            "instruction_sent_at",
            "instruction_sent_by",
            "created_at",
            "updated_at",
        )

    @extend_schema_field(USER_SUMMARY_RESPONSE)
    def get_owner(self, obj):
        return user_payload(obj.owner)

    def _latest_provisioning(self, obj):
        return obj.provisioning_records.order_by("-created_at", "-id").first()

    @extend_schema_field(OpenApiTypes.STR)
    def get_online_status(self, obj):
        return device_online_status(obj)

    @extend_schema_field(OpenApiTypes.STR)
    def get_provisioning_status(self, obj):
        provisioning = self._latest_provisioning(obj)
        return provisioning.delivery_status if provisioning else None

    @extend_schema_field(OpenApiTypes.STR)
    def get_instruction_text(self, obj):
        provisioning = self._latest_provisioning(obj)
        return provisioning.instruction_text if provisioning else ""

    @extend_schema_field(OpenApiTypes.STR)
    def get_firmware_code(self, obj):
        provisioning = self._latest_provisioning(obj)
        return provisioning.firmware_code if provisioning else ""

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_instruction_sent(self, obj):
        provisioning = self._latest_provisioning(obj)
        return provisioning.delivery_status in {
            DWDProvisioning.DELIVERY_SENT,
            DWDProvisioning.DELIVERY_ACKNOWLEDGED,
        } if provisioning else False

    @extend_schema_field(OpenApiTypes.DATETIME)
    def get_instruction_sent_at(self, obj):
        provisioning = self._latest_provisioning(obj)
        return utc_iso(provisioning.sent_at) if provisioning else None

    @extend_schema_field(USER_SUMMARY_RESPONSE)
    def get_instruction_sent_by(self, obj):
        provisioning = self._latest_provisioning(obj)
        return user_payload(provisioning.sent_by) if provisioning else None

    @extend_schema_field(OpenApiTypes.STR)
    def get_token_masked(self, obj):
        return mask_token(obj.token)


class DWDDeviceUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = DWDDevice
        fields = (
            "device_code",
            "station_id",
            "city",
            "firmware_type",
            "firmware_version",
            "ip_address",
            "last_seen_at",
            "last_request_at",
            "last_data_at",
            "status",
            "is_enabled",
            "notes",
            "last_error",
            "last_error_at",
        )
        extra_kwargs = {
            "device_code": {"required": False},
            "station_id": {"required": False},
        }


class DWDProviderApplicationCreateSerializer(serializers.ModelSerializer):
    city = serializers.CharField(max_length=128, allow_blank=False, trim_whitespace=True)
    email = serializers.EmailField(allow_blank=False)
    comment = serializers.CharField(allow_blank=False, trim_whitespace=True)

    class Meta:
        model = DWDProviderApplication
        fields = ("city", "email", "country", "region", "address_comment", "comment")
        extra_kwargs = {
            "country": {"required": False, "allow_blank": True},
            "region": {"required": False, "allow_blank": True},
            "address_comment": {"required": False, "allow_blank": True},
        }

    def validate_email(self, value: str) -> str:
        return value.strip().lower()

    def validate(self, attrs):
        user = self.context["request"].user
        if DWDProviderApplication.objects.filter(user=user, status=DWDProviderApplication.STATUS_PENDING).exists():
            raise serializers.ValidationError({"detail": "User already has a pending DWD provider application."})
        return attrs

    def create(self, validated_data):
        user = self.context["request"].user
        application = DWDProviderApplication.objects.create(user=user, **validated_data)
        notify_admins(
            notification_type=DWDNotification.TYPE_APPLICATION_SUBMITTED,
            title="Новая заявка DWD",
            message=f"{user.get_username()} хочет подключить устройство в городе {application.city}.",
            application=application,
        )
        record_system_event(
            event="dwd_provider_application_created",
            source="dwd",
            message=f"User {user.pk} submitted DWD provider application",
            payload={"application_id": application.pk, "user_id": user.pk, "city": application.city},
        )
        return application


class DWDProviderApplicationSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    reviewed_by = serializers.SerializerMethodField()
    reviewed_at = serializers.SerializerMethodField()
    device = serializers.SerializerMethodField()
    latest_provisioning = serializers.SerializerMethodField()

    class Meta:
        model = DWDProviderApplication
        fields = (
            "id",
            "user",
            "city",
            "email",
            "country",
            "region",
            "address_comment",
            "comment",
            "admin_note",
            "status",
            "reviewed_by",
            "reviewed_at",
            "device",
            "latest_provisioning",
            "created_at",
            "updated_at",
        )

    @extend_schema_field(USER_SUMMARY_RESPONSE)
    def get_user(self, obj):
        return user_payload(obj.user)

    @extend_schema_field(USER_SUMMARY_RESPONSE)
    def get_reviewed_by(self, obj):
        return user_payload(obj.reviewed_by)

    @extend_schema_field(OpenApiTypes.DATETIME)
    def get_reviewed_at(self, obj):
        return utc_iso(obj.reviewed_at)

    @extend_schema_field(DWDDeviceSerializer)
    def get_device(self, obj):
        device = getattr(obj, "device", None)
        if device is None:
            return None
        return DWDDeviceSerializer(device).data

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_latest_provisioning(self, obj):
        provisioning = obj.provisioning_records.order_by("-created_at", "-id").first()
        if provisioning is None:
            return None
        return {
            "id": provisioning.id,
            "firmware_type": provisioning.firmware_type,
            "firmware_version": provisioning.firmware_version,
            "delivery_status": provisioning.delivery_status,
            "sent_at": utc_iso(provisioning.sent_at),
            "sent_by": user_payload(provisioning.sent_by),
        }


class DWDApplicationAdminUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = DWDProviderApplication
        fields = ("admin_note", "status")


class DWDProvisioningCreateSerializer(serializers.Serializer):
    application_id = serializers.IntegerField()
    user_id = serializers.IntegerField(required=False)
    device_id = serializers.IntegerField(required=False, allow_null=True)
    firmware_type = serializers.ChoiceField(choices=[choice[0] for choice in DWDProvisioning.FIRMWARE_CHOICES])
    firmware_version = serializers.CharField(max_length=64, required=False, allow_blank=True)
    instruction_text = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    wifi_ssid = serializers.CharField(max_length=128, required=False, allow_blank=True, trim_whitespace=True)
    wifi_password = serializers.CharField(max_length=128, required=False, allow_blank=True, trim_whitespace=False, write_only=True)
    delivery_channel = serializers.ChoiceField(
        choices=[choice[0] for choice in DWDProvisioning.DELIVERY_CHANNEL_CHOICES],
        default=DWDProvisioning.CHANNEL_MANUAL,
    )
    notes = serializers.CharField(required=False, allow_blank=True)
    internal_note = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        application = get_object_or_404(DWDProviderApplication, pk=attrs["application_id"])
        if application.status != DWDProviderApplication.STATUS_APPROVED:
            raise serializers.ValidationError({"application_id": "Application must be approved before provisioning."})

        user_id = attrs.get("user_id", application.user_id)
        if user_id != application.user_id:
            raise serializers.ValidationError({"user_id": "Provisioning user must match application user."})

        User = get_user_model()
        user = get_object_or_404(User, pk=user_id)

        device = None
        device_id = attrs.get("device_id")
        if device_id:
            device = get_object_or_404(DWDDevice, pk=device_id)
            if device.owner_id != user.pk:
                raise serializers.ValidationError({"device_id": "Device owner must match provisioning user."})
        else:
            device = getattr(application, "device", None)

        firmware_type = attrs["firmware_type"]
        instruction_text = attrs.get("instruction_text", "").strip()
        if not instruction_text:
            instruction_text = FIRMWARE_INSTRUCTION_TEMPLATES[firmware_type]

        attrs["application"] = application
        attrs["user"] = user
        attrs["device"] = device
        attrs["instruction_text"] = instruction_text
        return attrs

    def create(self, validated_data):
        for key in ("application_id", "user_id", "device_id"):
            validated_data.pop(key, None)
        validated_data["code_generated_at"] = timezone.now()
        validated_data["firmware_code"] = generate_mqtt_wifi_firmware(
            device=validated_data.get("device"),
            firmware_version=validated_data.get("firmware_version", ""),
            wifi_ssid=validated_data.get("wifi_ssid", ""),
            wifi_password=validated_data.get("wifi_password", ""),
            request=self.context.get("request"),
        )
        validated_data["delivery_status"] = (
            DWDProvisioning.DELIVERY_INSTRUCTION_READY
            if validated_data.get("instruction_text") or validated_data.get("firmware_code")
            else DWDProvisioning.DELIVERY_FIRMWARE_ASSIGNED
        )
        provisioning = DWDProvisioning.objects.create(**validated_data)
        if provisioning.device:
            provisioning.device.firmware_type = provisioning.firmware_type
            provisioning.device.firmware_version = provisioning.firmware_version
            provisioning.device.save(update_fields=["firmware_type", "firmware_version", "updated_at"])
            record_device_event(
                device=provisioning.device,
                event_type=DWDDeviceEvent.EVENT_SETTINGS_CHANGED,
                message=f"Firmware assigned: {provisioning.firmware_type} {provisioning.firmware_version}".strip(),
            )
        record_system_event(
            event="dwd_provisioning_created",
            source="dwd",
            message=f"Firmware {provisioning.firmware_type} assigned to user {provisioning.user_id}",
            payload={
                "provisioning_id": provisioning.pk,
                "application_id": provisioning.application_id,
                "device_id": provisioning.device_id,
                "user_id": provisioning.user_id,
                "firmware_type": provisioning.firmware_type,
            },
        )
        notify_user(
            provisioning.user,
            notification_type=DWDNotification.TYPE_PROVISIONING_READY,
            title="Прошивка готова",
            message="Администратор подготовил код прошивки для вашего DWD-устройства.",
            application=provisioning.application,
            device=provisioning.device,
            provisioning=provisioning,
        )
        return provisioning


class DWDProvisioningSerializer(serializers.ModelSerializer):
    application_id = serializers.IntegerField(read_only=True)
    user = serializers.SerializerMethodField()
    device = serializers.SerializerMethodField()
    sent_by = serializers.SerializerMethodField()
    sent_at = serializers.SerializerMethodField()
    sent_status = serializers.CharField(source="delivery_status", read_only=True)
    wifi_configured = serializers.SerializerMethodField()

    class Meta:
        model = DWDProvisioning
        fields = (
            "id",
            "application_id",
            "user",
            "device",
            "firmware_type",
            "firmware_version",
            "instruction_text",
            "firmware_code",
            "code_generated_at",
            "wifi_ssid",
            "wifi_configured",
            "delivery_status",
            "sent_status",
            "delivery_channel",
            "sent_at",
            "sent_by",
            "notes",
            "internal_note",
            "created_at",
            "updated_at",
        )

    @extend_schema_field(USER_SUMMARY_RESPONSE)
    def get_user(self, obj):
        return user_payload(obj.user)

    @extend_schema_field(DWDDeviceSerializer)
    def get_device(self, obj):
        return DWDDeviceSerializer(obj.device).data if obj.device else None

    @extend_schema_field(USER_SUMMARY_RESPONSE)
    def get_sent_by(self, obj):
        return user_payload(obj.sent_by)

    @extend_schema_field(OpenApiTypes.DATETIME)
    def get_sent_at(self, obj):
        return utc_iso(obj.sent_at)

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_wifi_configured(self, obj):
        return bool(obj.wifi_ssid and obj.wifi_password)


class DWDDeviceEventSerializer(serializers.ModelSerializer):
    device_code = serializers.CharField(source="device.device_code", read_only=True)
    station_id = serializers.CharField(source="device.station_id", read_only=True)

    class Meta:
        model = DWDDeviceEvent
        fields = ("id", "device", "device_code", "station_id", "event_type", "severity", "message", "ip_address", "created_at")


class ProviderDashboardSerializer(serializers.Serializer):
    applications = DWDProviderApplicationSerializer(many=True)
    devices = DWDDeviceSerializer(many=True)
    provisioning = DWDProvisioningSerializer(many=True)


class DWDNotificationSerializer(serializers.ModelSerializer):
    application_id = serializers.IntegerField(read_only=True)
    device_id = serializers.IntegerField(read_only=True)
    provisioning_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = DWDNotification
        fields = (
            "id",
            "notification_type",
            "title",
            "message",
            "application_id",
            "device_id",
            "provisioning_id",
            "is_read",
            "created_at",
        )


class DWDSupportMessageSerializer(serializers.ModelSerializer):
    sender = serializers.SerializerMethodField()

    class Meta:
        model = DWDSupportMessage
        fields = ("id", "application", "sender", "message", "is_system", "created_at")

    @extend_schema_field(USER_SUMMARY_RESPONSE)
    def get_sender(self, obj):
        return user_payload(obj.sender)


class DWDSupportMessageCreateSerializer(serializers.Serializer):
    message = serializers.CharField(allow_blank=False, trim_whitespace=True)


class DWDProviderApplicationListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description="Create a DWD provider application or list the current user's applications.",
        responses=dwd_responses(DWDProviderApplicationSerializer(many=True), created_schema=DWDProviderApplicationSerializer),
    )
    def get(self, request):
        applications = DWDProviderApplication.objects.filter(user=request.user).select_related(
            "user", "reviewed_by", "device", "device__owner"
        )
        return Response(DWDProviderApplicationSerializer(applications, many=True).data, status=status.HTTP_200_OK)

    @extend_schema(
        description="Submit a DWD provider application. City and comment are required.",
        request=DWDProviderApplicationCreateSerializer,
        responses=dwd_responses(created_schema=DWDProviderApplicationSerializer),
    )
    def post(self, request):
        serializer = DWDProviderApplicationCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        application = serializer.save()
        return Response(DWDProviderApplicationSerializer(application).data, status=status.HTTP_201_CREATED)


class DWDProviderApplicationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description="Get a DWD provider application. Regular users can only read their own applications.",
        responses=dwd_responses(DWDProviderApplicationSerializer),
    )
    def get(self, request, pk: int):
        queryset = DWDProviderApplication.objects.select_related("user", "reviewed_by")
        if not request.user.is_staff:
            queryset = queryset.filter(user=request.user)
        application = get_object_or_404(queryset, pk=pk)
        return Response(DWDProviderApplicationSerializer(application).data, status=status.HTTP_200_OK)


class ProviderDashboardView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description="Provider personal cabinet: own DWD applications, devices and firmware instructions.",
        responses=dwd_responses(ProviderDashboardSerializer),
    )
    def get(self, request):
        applications = DWDProviderApplication.objects.filter(user=request.user).select_related("user", "reviewed_by")
        devices = DWDDevice.objects.filter(owner=request.user).select_related("owner", "application")
        provisioning = DWDProvisioning.objects.filter(user=request.user).select_related("application", "device", "sent_by")
        return Response(
            {
                "applications": DWDProviderApplicationSerializer(applications, many=True).data,
                "devices": DWDDeviceSerializer(devices, many=True).data,
                "provisioning": DWDProvisioningSerializer(provisioning, many=True).data,
            },
            status=status.HTTP_200_OK,
        )


def accessible_application_queryset(user):
    queryset = DWDProviderApplication.objects.select_related("user", "reviewed_by")
    if user.is_staff:
        return queryset
    return queryset.filter(user=user)


class DWDNotificationsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description="Current user's DWD notifications.",
        responses=dwd_responses(DWDNotificationSerializer(many=True)),
    )
    def get(self, request):
        notifications = DWDNotification.objects.filter(recipient=request.user)
        unread_only = str(request.query_params.get("unread", "")).lower() in {"1", "true", "yes"}
        if unread_only:
            notifications = notifications.filter(is_read=False)
        try:
            limit = min(max(int(request.query_params.get("limit", 50)), 1), 200)
        except ValueError:
            return Response({"detail": "limit must be an integer"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(DWDNotificationSerializer(notifications[:limit], many=True).data, status=status.HTTP_200_OK)


class DWDNotificationReadView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description="Mark a DWD notification as read.",
        request=None,
        responses=dwd_responses(DWDNotificationSerializer),
    )
    def post(self, request, pk: int):
        notification = get_object_or_404(DWDNotification, pk=pk, recipient=request.user)
        notification.is_read = True
        notification.save(update_fields=["is_read"])
        return Response(DWDNotificationSerializer(notification).data, status=status.HTTP_200_OK)


class DWDApplicationMessagesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description="Support chat messages for a DWD provider application. Admins can read any application; users can read their own.",
        responses=dwd_responses(DWDSupportMessageSerializer(many=True)),
    )
    def get(self, request, pk: int):
        application = get_object_or_404(accessible_application_queryset(request.user), pk=pk)
        messages = application.support_messages.select_related("sender")
        return Response(DWDSupportMessageSerializer(messages, many=True).data, status=status.HTTP_200_OK)

    @extend_schema(
        description="Send a support chat message for a DWD provider application.",
        request=DWDSupportMessageCreateSerializer,
        responses=dwd_responses(created_schema=DWDSupportMessageSerializer),
    )
    def post(self, request, pk: int):
        application = get_object_or_404(accessible_application_queryset(request.user), pk=pk)
        serializer = DWDSupportMessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = DWDSupportMessage.objects.create(
            application=application,
            sender=request.user,
            message=serializer.validated_data["message"],
        )
        if request.user.is_staff:
            notify_user(
                application.user,
                notification_type=DWDNotification.TYPE_CHAT_MESSAGE,
                title="Новое сообщение от администратора",
                message=message.message[:240],
                application=application,
            )
        else:
            notify_admins(
                notification_type=DWDNotification.TYPE_CHAT_MESSAGE,
                title="Новое сообщение от provider",
                message=f"{request.user.get_username()}: {message.message[:200]}",
                application=application,
                exclude_user_id=request.user.pk,
            )
        return Response(DWDSupportMessageSerializer(message).data, status=status.HTTP_201_CREATED)


class AdminDWDUsersView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        description="Admin-only users and roles list for DWD management.",
        responses=dwd_responses(DWDUserAdminSerializer(many=True)),
    )
    def get(self, _request):
        User = get_user_model()
        users = User.objects.prefetch_related("groups", "dwd_provider_applications").annotate(
            device_count=Count("dwd_devices")
        ).order_by("id")
        return Response(DWDUserAdminSerializer(users, many=True).data, status=status.HTTP_200_OK)


class AdminDWDUserRoleView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        description="Admin-only user role change: user, provider or admin.",
        request=DWDUserRoleUpdateSerializer,
        responses=dwd_responses(DWDUserAdminSerializer),
    )
    def patch(self, request, pk: int):
        User = get_user_model()
        user = get_object_or_404(User, pk=pk)
        serializer = DWDUserRoleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role = serializer.validated_data["role"]
        set_user_role(user, role)
        record_system_event(
            event="dwd_user_role_changed",
            source="admin",
            message=f"User {user.pk} role changed to {role}",
            payload={"user_id": user.pk, "role": role, "admin_id": request.user.pk},
        )
        user.device_count = user.dwd_devices.count()
        return Response(DWDUserAdminSerializer(user).data, status=status.HTTP_200_OK)


class AdminDWDUserDetailView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        description="Admin-only user account deletion. The current admin cannot delete their own account here.",
        responses={204: None, **dwd_responses()},
    )
    def delete(self, request, pk: int):
        if request.user.pk == pk:
            return Response({"detail": "Cannot delete your own admin account from this screen."}, status=status.HTTP_400_BAD_REQUEST)
        User = get_user_model()
        user = get_object_or_404(User, pk=pk)
        username = user.get_username()
        user.delete()
        record_system_event(
            event="dwd_user_deleted",
            source="admin",
            message=f"User {pk} deleted by admin {request.user.pk}",
            payload={"user_id": pk, "username": username, "admin_id": request.user.pk},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminDWDApplicationsView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        description="Admin-only list of DWD provider applications including city and review metadata.",
        responses=dwd_responses(DWDProviderApplicationSerializer(many=True)),
    )
    def get(self, _request):
        applications = DWDProviderApplication.objects.select_related("user", "reviewed_by").prefetch_related(
            "provisioning_records"
        )
        return Response(DWDProviderApplicationSerializer(applications, many=True).data, status=status.HTTP_200_OK)


class AdminDWDApplicationDetailView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        description="Admin-only DWD application detail card with notes, device and provisioning metadata.",
        responses=dwd_responses(DWDProviderApplicationSerializer),
    )
    def get(self, _request, pk: int):
        application = get_object_or_404(
            DWDProviderApplication.objects.select_related("user", "reviewed_by").prefetch_related("provisioning_records"),
            pk=pk,
        )
        return Response(DWDProviderApplicationSerializer(application).data, status=status.HTTP_200_OK)

    @extend_schema(
        description="Admin-only update for DWD application status or internal note.",
        request=DWDApplicationAdminUpdateSerializer,
        responses=dwd_responses(DWDProviderApplicationSerializer),
    )
    def patch(self, request, pk: int):
        application = get_object_or_404(DWDProviderApplication, pk=pk)
        serializer = DWDApplicationAdminUpdateSerializer(application, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        application = serializer.save()
        record_system_event(
            event="dwd_application_note_updated",
            source="admin",
            message=f"Application {application.pk} admin data updated",
            payload={"application_id": application.pk, "admin_id": request.user.pk},
        )
        return Response(DWDProviderApplicationSerializer(application).data, status=status.HTTP_200_OK)


def ensure_dwd_device(application: DWDProviderApplication) -> DWDDevice:
    device_code = f"dwd-{application.pk}"
    device, created = DWDDevice.objects.get_or_create(
        application=application,
        defaults={
            "owner": application.user,
            "device_code": device_code,
            "station_id": device_code,
            "city": application.city,
            "country": application.country,
            "region": application.region,
            "address_comment": application.address_comment,
            "status": DWDDevice.STATUS_INACTIVE,
            "token": secrets.token_urlsafe(32),
        },
    )
    if not created:
        device.owner = application.user
        if not device.device_code:
            device.device_code = device.station_id or device_code
        if not device.token:
            device.token = secrets.token_urlsafe(32)
        device.city = application.city
        device.country = application.country
        device.region = application.region
        device.address_comment = application.address_comment
        device.save(update_fields=["owner", "device_code", "token", "city", "country", "region", "address_comment", "updated_at"])
    if created:
        record_device_event(
            device=device,
            event_type=DWDDeviceEvent.EVENT_REGISTERED,
            message=f"Device card created for application {application.pk}",
        )
    return device


class AdminDWDApplicationApproveView(APIView):
    permission_classes = [IsAdminUser]
    serializer_class = DWDProviderApplicationSerializer

    @extend_schema(
        description="Approve a DWD provider application, grant provider group and create a linked device card.",
        request=None,
        responses=dwd_responses(DWDProviderApplicationSerializer),
    )
    @transaction.atomic
    def post(self, request, pk: int):
        application = get_object_or_404(DWDProviderApplication.objects.select_for_update(), pk=pk)
        provider_group, _created = Group.objects.get_or_create(name=PROVIDER_GROUP_NAME)
        application.user.groups.add(provider_group)

        application.status = DWDProviderApplication.STATUS_APPROVED
        application.reviewed_by = request.user
        application.reviewed_at = timezone.now()
        application.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])

        device = ensure_dwd_device(application)
        record_device_event(
            device=device,
            event_type=DWDDeviceEvent.EVENT_ACTIVATED,
            message=f"Application {application.pk} approved by admin {request.user.pk}",
        )
        record_system_event(
            event="dwd_provider_application_approved",
            source="admin",
            message=f"Application {application.pk} approved by admin {request.user.pk}",
            payload={
                "application_id": application.pk,
                "user_id": application.user_id,
                "device_id": device.pk,
                "city": application.city,
                "admin_id": request.user.pk,
            },
        )
        DWDSupportMessage.objects.create(
            application=application,
            sender=request.user,
            is_system=True,
            message="Заявка одобрена. Администратор подготовит код прошивки и инструкцию.",
        )
        notify_user(
            application.user,
            notification_type=DWDNotification.TYPE_STATUS_CHANGED,
            title="Заявка DWD одобрена",
            message="Теперь администратор может подготовить прошивку для вашего устройства.",
            application=application,
            device=device,
        )
        return Response(DWDProviderApplicationSerializer(application).data, status=status.HTTP_200_OK)


class AdminDWDApplicationRejectView(APIView):
    permission_classes = [IsAdminUser]
    serializer_class = DWDProviderApplicationSerializer

    @extend_schema(
        description="Reject a DWD provider application.",
        request=None,
        responses=dwd_responses(DWDProviderApplicationSerializer),
    )
    @transaction.atomic
    def post(self, request, pk: int):
        application = get_object_or_404(DWDProviderApplication.objects.select_for_update(), pk=pk)
        application.status = DWDProviderApplication.STATUS_REJECTED
        application.reviewed_by = request.user
        application.reviewed_at = timezone.now()
        application.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])
        record_system_event(
            event="dwd_provider_application_rejected",
            source="admin",
            message=f"Application {application.pk} rejected by admin {request.user.pk}",
            payload={"application_id": application.pk, "user_id": application.user_id, "admin_id": request.user.pk},
        )
        DWDSupportMessage.objects.create(
            application=application,
            sender=request.user,
            is_system=True,
            message="Заявка отклонена. Если нужны детали, напишите администратору в чате поддержки.",
        )
        notify_user(
            application.user,
            notification_type=DWDNotification.TYPE_STATUS_CHANGED,
            title="Заявка DWD отклонена",
            message="Администратор отклонил заявку. Детали можно уточнить в чате поддержки.",
            application=application,
        )
        return Response(DWDProviderApplicationSerializer(application).data, status=status.HTTP_200_OK)


class AdminDWDDevicesView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        description="Admin-only list of DWD devices with owner, city and latest provisioning metadata.",
        responses=dwd_responses(DWDDeviceSerializer(many=True)),
    )
    def get(self, request):
        devices = DWDDevice.objects.select_related("owner", "application").prefetch_related(
            "provisioning_records", "provisioning_records__sent_by"
        )
        owner = request.query_params.get("owner")
        city = request.query_params.get("city")
        firmware_type = request.query_params.get("firmware_type")
        status_filter = request.query_params.get("status")
        online_status = request.query_params.get("online_status")
        if owner:
            devices = devices.filter(owner__username__icontains=owner)
        if city:
            devices = devices.filter(city__icontains=city)
        if firmware_type:
            devices = devices.filter(firmware_type=firmware_type)
        if status_filter:
            devices = devices.filter(status=status_filter)
        payload = DWDDeviceSerializer(devices, many=True).data
        if online_status in {"online", "offline"}:
            payload = [item for item in payload if item["online_status"] == online_status]
        return Response(payload, status=status.HTTP_200_OK)


class AdminDWDDeviceDetailView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        description="Admin-only DWD device detail card with monitoring, token mask, notes and provisioning status.",
        responses=dwd_responses(DWDDeviceSerializer),
    )
    def get(self, _request, pk: int):
        device = get_object_or_404(
            DWDDevice.objects.select_related("owner", "application").prefetch_related("provisioning_records"),
            pk=pk,
        )
        return Response(DWDDeviceSerializer(device).data, status=status.HTTP_200_OK)

    @extend_schema(
        description="Admin-only update of DWD device metadata and monitoring fields.",
        request=DWDDeviceUpdateSerializer,
        responses=dwd_responses(DWDDeviceSerializer),
    )
    def patch(self, request, pk: int):
        device = get_object_or_404(DWDDevice, pk=pk)
        serializer = DWDDeviceUpdateSerializer(device, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        device = serializer.save()
        record_device_event(
            device=device,
            event_type=DWDDeviceEvent.EVENT_SETTINGS_CHANGED,
            message=f"Device metadata updated by admin {request.user.pk}",
            ip_address=device.ip_address,
        )
        return Response(DWDDeviceSerializer(device).data, status=status.HTTP_200_OK)


class AdminDWDDeviceActionView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        description="Admin-only DWD device action: enable, disable or block.",
        request=inline_serializer(
            name="DWDDeviceActionRequest",
            fields={"action": serializers.ChoiceField(choices=["enable", "disable", "block"])},
        ),
        responses=dwd_responses(DWDDeviceSerializer),
    )
    def post(self, request, pk: int):
        device = get_object_or_404(DWDDevice, pk=pk)
        action = str(request.data.get("action", "")).strip()
        if action == "enable":
            device.is_enabled = True
            if device.status == DWDDevice.STATUS_INACTIVE:
                device.status = DWDDevice.STATUS_ACTIVE
            event_type = DWDDeviceEvent.EVENT_ACTIVATED
            message = "Device enabled"
        elif action == "disable":
            device.is_enabled = False
            device.status = DWDDevice.STATUS_INACTIVE
            event_type = DWDDeviceEvent.EVENT_SETTINGS_CHANGED
            message = "Device disabled"
        elif action == "block":
            device.is_enabled = False
            device.status = DWDDevice.STATUS_BLOCKED
            event_type = DWDDeviceEvent.EVENT_BLOCKED
            message = "Device blocked"
        else:
            return Response({"detail": "invalid action"}, status=status.HTTP_400_BAD_REQUEST)

        device.save(update_fields=["is_enabled", "status", "updated_at"])
        record_device_event(device=device, event_type=event_type, message=f"{message} by admin {request.user.pk}")
        return Response(DWDDeviceSerializer(device).data, status=status.HTTP_200_OK)


class AdminDWDDeviceEventsView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        description="Admin-only DWD device event journal.",
        responses=dwd_responses(DWDDeviceEventSerializer(many=True)),
    )
    def get(self, request):
        events = DWDDeviceEvent.objects.select_related("device").all()
        device_id = request.query_params.get("device_id")
        event_type = request.query_params.get("event_type")
        severity = request.query_params.get("severity")
        if device_id:
            events = events.filter(device_id=device_id)
        if event_type:
            events = events.filter(event_type=event_type)
        if severity:
            events = events.filter(severity=severity)
        try:
            limit = min(max(int(request.query_params.get("limit", 100)), 1), 500)
        except ValueError:
            return Response({"detail": "limit must be an integer"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(DWDDeviceEventSerializer(events[:limit], many=True).data, status=status.HTTP_200_OK)


class AdminDWDProvisioningView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        description="Admin-only list of DWD firmware provisioning records.",
        responses=dwd_responses(DWDProvisioningSerializer(many=True)),
    )
    def get(self, request):
        records = DWDProvisioning.objects.select_related("application", "user", "device", "sent_by")
        firmware_type = request.query_params.get("firmware_type")
        delivery_status = request.query_params.get("delivery_status") or request.query_params.get("status")
        if firmware_type:
            records = records.filter(firmware_type=firmware_type)
        if delivery_status:
            records = records.filter(delivery_status=delivery_status)
        return Response(DWDProvisioningSerializer(records, many=True).data, status=status.HTTP_200_OK)

    @extend_schema(
        description="Assign firmware and installation instruction to an approved DWD provider application.",
        request=DWDProvisioningCreateSerializer,
        responses=dwd_responses(created_schema=DWDProvisioningSerializer),
    )
    def post(self, request):
        serializer = DWDProvisioningCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        provisioning = serializer.save()
        return Response(DWDProvisioningSerializer(provisioning).data, status=status.HTTP_201_CREATED)


class AdminDWDProvisioningMarkSentView(APIView):
    permission_classes = [IsAdminUser]
    serializer_class = DWDProvisioningSerializer

    @extend_schema(
        description="Mark a DWD firmware instruction as manually sent to the provider.",
        request=None,
        responses=dwd_responses(DWDProvisioningSerializer),
    )
    def post(self, request, pk: int):
        provisioning = get_object_or_404(DWDProvisioning, pk=pk)
        provisioning.delivery_status = DWDProvisioning.DELIVERY_SENT
        provisioning.sent_at = timezone.now()
        provisioning.sent_by = request.user
        provisioning.save(update_fields=["delivery_status", "sent_at", "sent_by", "updated_at"])
        if provisioning.device:
            record_device_event(
                device=provisioning.device,
                event_type=DWDDeviceEvent.EVENT_SETTINGS_CHANGED,
                message=f"Instruction marked as sent manually by admin {request.user.pk}",
            )
        record_system_event(
            event="dwd_provisioning_instruction_sent",
            source="admin",
            level=SystemEvent.LEVEL_INFO,
            message=f"Provisioning {provisioning.pk} instruction marked as sent",
            payload={
                "provisioning_id": provisioning.pk,
                "application_id": provisioning.application_id,
                "user_id": provisioning.user_id,
                "sent_by": request.user.pk,
                "delivery_channel": provisioning.delivery_channel,
            },
        )
        notify_user(
            provisioning.user,
            notification_type=DWDNotification.TYPE_PROVISIONING_READY,
            title="Инструкция отмечена как отправленная",
            message="Администратор отметил, что инструкция отправлена вручную.",
            application=provisioning.application,
            device=provisioning.device,
            provisioning=provisioning,
        )
        return Response(DWDProvisioningSerializer(provisioning).data, status=status.HTTP_200_OK)
