from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from server.iot.config import get_iot_config
from server.iot.serial_bridge import SerialArduinoReader
from server.monitoring import record_system_event


class Command(BaseCommand):
    help = "Read Arduino telemetry from a USB serial port and store it as station readings."

    def add_arguments(self, parser):
        parser.add_argument(
            "--line",
            help="Parse and save one serial line without opening a serial port. Useful for local smoke checks.",
        )

    def handle(self, *args, **options):
        config = get_iot_config()
        reader = SerialArduinoReader(config=config)

        if options.get("line"):
            reading = reader.save_line(options["line"])
            if reading is None:
                self.stdout.write(self.style.WARNING("Skipped serial line"))
            else:
                self.stdout.write(self.style.SUCCESS(f"Saved serial reading #{reading.pk}"))
            return

        if not config.serial_enabled:
            raise CommandError("Serial Bridge is disabled. Enable it via /api/admin/iot/config/ first.")

        record_system_event(
            event="serial_bridge_config_loaded",
            source="serial_bridge",
            message="Serial Bridge command loaded configuration",
            payload={
                "connection_mode": config.connection_mode,
                "enabled": config.serial_enabled,
                "port": config.serial_port,
                "baud_rate": config.baud_rate,
                "linked_device_id": config.linked_device_id,
            },
        )
        self.stdout.write(
            (
                f"Starting Serial Bridge on {config.serial_port} @ {config.baud_rate} "
                f"(linked_device_id={config.linked_device_id or 'none'}). Press Ctrl+C to stop."
            )
        )
        reader.run_forever()
