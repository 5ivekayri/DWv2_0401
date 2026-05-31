from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from server.iot.config import get_iot_config
from server.iot.mqtt_bridge import MqttArduinoListener
from server.monitoring import record_system_event


class Command(BaseCommand):
    help = "Subscribe to MQTT station telemetry and store it as station readings."

    def add_arguments(self, parser):
        parser.add_argument(
            "--topic",
            default="darkweather/stations/dwd-3/readings",
            help="Topic for one-message smoke check.",
        )
        parser.add_argument(
            "--message",
            help="Parse and save one MQTT payload without connecting to a broker.",
        )

    def handle(self, *args, **options):
        config = get_iot_config()
        listener = MqttArduinoListener(config=config)

        if options.get("message"):
            reading = listener.save_message(options["topic"], options["message"])
            if reading is None:
                self.stdout.write(self.style.WARNING("Skipped MQTT message"))
            else:
                self.stdout.write(self.style.SUCCESS(f"Saved MQTT reading #{reading.pk}"))
            return

        if not config.mqtt_enabled:
            raise CommandError("MQTT listener is disabled. Enable it via /api/admin/iot/config/ first.")

        record_system_event(
            event="mqtt_config_loaded",
            source="mqtt",
            message="MQTT listener command loaded configuration",
            payload={
                "connection_mode": config.connection_mode,
                "enabled": config.mqtt_enabled,
                "host": config.mqtt_host,
                "port": config.mqtt_port,
                "topic": config.mqtt_topic,
            },
        )
        self.stdout.write(
            (
                f"Starting MQTT listener on {config.mqtt_host}:{config.mqtt_port} "
                f"topic={config.mqtt_topic}. Press Ctrl+C to stop."
            )
        )
        listener.run_forever()
