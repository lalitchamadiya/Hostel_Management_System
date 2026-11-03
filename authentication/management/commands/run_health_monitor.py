import time
from django.core.management.base import BaseCommand
from authentication.health import SystemHealthService
from authentication.models import SystemSettings


class Command(BaseCommand):
    help = "Runs system health checks and automatic maintenance mode recovery evaluation."

    def add_arguments(self, parser):
        parser.add_argument(
            '--continuous',
            action='store_true',
            help='Run continuously in a loop using configured health check interval',
        )
        parser.add_argument(
            '--interval',
            type=int,
            default=None,
            help='Override interval in seconds for continuous mode',
        )

    def handle(self, *args, **options):
        continuous = options.get('continuous', False)
        override_interval = options.get('interval')

        if not continuous:
            self.stdout.write(self.style.NOTICE("Running one-shot system health check..."))
            result = SystemHealthService.evaluate_and_recover(trigger='auto')
            status_text = "HEALTHY" if result['health']['healthy'] else "UNHEALTHY"
            color = self.style.SUCCESS if result['health']['healthy'] else self.style.ERROR
            self.stdout.write(color(f"Health Status: {status_text}"))
            if result.get('recovered'):
                self.stdout.write(self.style.SUCCESS("[RECOVERED] System maintenance mode automatically lifted!"))
            return

        self.stdout.write(self.style.SUCCESS("Starting background continuous system health monitor..."))
        while True:
            try:
                settings_obj = SystemSettings.get_settings()
                interval = override_interval or settings_obj.health_check_interval or 30

                result = SystemHealthService.evaluate_and_recover(trigger='auto')
                healthy = result['health']['healthy']
                m_mode = result.get('maintenance_mode', False)

                tag = "[HEALTHY]" if healthy else "[UNHEALTHY]"
                self.stdout.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {tag} Maintenance Mode={m_mode}, Consecutive={result.get('consecutive_count')}")

                if result.get('recovered'):
                    self.stdout.write(self.style.SUCCESS("[RECOVERED] Maintenance Mode lifted. Service Restored."))

                time.sleep(interval)
            except KeyboardInterrupt:
                self.stdout.write(self.style.NOTICE("Health monitor stopped by user."))
                break
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Health monitor loop error: {e}"))
                time.sleep(10)
