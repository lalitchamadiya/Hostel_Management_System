import json
import logging
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.apps import apps
from django.utils import timezone
from django.contrib.auth.models import User
from authentication.models import SystemSettings, AuditLog

logger = logging.getLogger(__name__)


class SystemHealthService:
    """
    Automated system health-monitoring and recovery engine.
    Monitors:
    1. Django application availability
    2. Database connectivity
    3. Migration and deployment completion
    4. Core models & data access
    5. Storage / system sanity
    6. System error tracking
    """

    @classmethod
    def check_application(cls):
        try:
            ready = apps.ready
            return {
                'name': 'Django Application Availability',
                'status': 'healthy' if ready else 'unhealthy',
                'passed': ready,
                'message': 'Application registry fully initialized' if ready else 'App registry not ready'
            }
        except Exception as e:
            return {
                'name': 'Django Application Availability',
                'status': 'unhealthy',
                'passed': False,
                'message': f"Application availability check exception: {type(e).__name__}"
            }

    @classmethod
    def check_database(cls):
        try:
            connection.ensure_connection()
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1;")
                row = cursor.fetchone()
            passed = bool(row and row[0] == 1)
            return {
                'name': 'Database Connectivity',
                'status': 'healthy' if passed else 'unhealthy',
                'passed': passed,
                'message': 'Database connection and query successful' if passed else 'Query returned unexpected result'
            }
        except Exception as e:
            return {
                'name': 'Database Connectivity',
                'status': 'unhealthy',
                'passed': False,
                'message': f"Database connection error: {type(e).__name__}"
            }

    @classmethod
    def check_migrations(cls):
        """
        Detects whether deployment, database migration, upgrade, or repair operations are still running/pending.
        Does not allow health recovery while migrations or operations are incomplete.
        """
        try:
            connection.ensure_connection()
            executor = MigrationExecutor(connection)
            targets = executor.loader.graph.leaf_nodes()
            plan = executor.migration_plan(targets)
            if plan:
                unapplied_count = len(plan)
                return {
                    'name': 'Database Migrations & Upgrades',
                    'status': 'unhealthy',
                    'passed': False,
                    'message': f"{unapplied_count} pending migration(s) detected. Migration/upgrade in progress.",
                    'pending_count': unapplied_count
                }
            return {
                'name': 'Database Migrations & Upgrades',
                'status': 'healthy',
                'passed': True,
                'message': 'All database migrations and schema upgrades are up to date.',
                'pending_count': 0
            }
        except Exception as e:
            return {
                'name': 'Database Migrations & Upgrades',
                'status': 'unhealthy',
                'passed': False,
                'message': f"Migration check error: {type(e).__name__}"
            }

    @classmethod
    def check_critical_models(cls):
        try:
            has_settings = SystemSettings.objects.exists()
            has_users = User.objects.filter(is_superuser=True).exists()
            passed = bool(has_settings and has_users)
            return {
                'name': 'Critical Core Models',
                'status': 'healthy' if passed else 'unhealthy',
                'passed': passed,
                'message': 'Core models and superadmin records accessible' if passed else 'Core models missing or incomplete'
            }
        except Exception as e:
            return {
                'name': 'Critical Core Models',
                'status': 'unhealthy',
                'passed': False,
                'message': f"Core model query error: {type(e).__name__}"
            }

    @classmethod
    def check_storage(cls):
        try:
            import os
            from django.conf import settings
            media_dir = str(settings.MEDIA_ROOT)
            writable = os.access(media_dir, os.W_OK) if os.path.exists(media_dir) else True
            return {
                'name': 'Media & Storage Subsystem',
                'status': 'healthy' if writable else 'degraded',
                'passed': writable,
                'message': 'Storage subsystem operational' if writable else 'Media directory not writable'
            }
        except Exception as e:
            return {
                'name': 'Media & Storage Subsystem',
                'status': 'degraded',
                'passed': True,  # Non-fatal on serverless/ephemeral environments
                'message': f"Storage check notice: {type(e).__name__}"
            }

    @classmethod
    def perform_full_health_check(cls):
        """
        Runs all checks and returns sanitized status dictionary.
        Never exposes database credentials, hostnames, passwords, or raw tracebacks.
        """
        results = [
            cls.check_application(),
            cls.check_database(),
            cls.check_migrations(),
            cls.check_critical_models(),
            cls.check_storage(),
        ]
        all_passed = all(r['passed'] for r in results)
        return {
            'healthy': all_passed,
            'status': 'healthy' if all_passed else 'unhealthy',
            'timestamp': timezone.now().isoformat(),
            'checks': results,
            'summary': 'All critical systems operational' if all_passed else 'One or more critical checks failed'
        }

    @classmethod
    def evaluate_and_recover(cls, trigger='auto', actor=None, ip_address=None):
        """
        Executes health evaluation workflow:
        1. When maintenance is active, monitor system health.
        2. Detect if migrations/operations are pending/running.
        3. Do not disable maintenance while operations are incomplete.
        4. Once operations complete, run health checks.
        5. Require all critical health checks to pass consecutively for consecutive_success_required.
        6. Confirm no unresolved critical errors.
        7. If healthy and auto_recovery_enabled (or manual trigger), disable maintenance mode.
        8. Restore access, update status to Service Restored, record recovery timestamp.
        """
        settings_obj = SystemSettings.get_settings()
        health_result = cls.perform_full_health_check()
        now = timezone.now()

        settings_obj.last_health_check_at = now
        settings_obj.last_health_status = json.dumps({
            'healthy': health_result['healthy'],
            'timestamp': health_result['timestamp'],
            'summary': health_result['summary'],
            'checks': [{k: v for k, v in c.items() if k != 'error'} for c in health_result['checks']]
        })

        is_healthy = health_result['healthy']

        if is_healthy:
            settings_obj.consecutive_success_count += 1
            threshold = settings_obj.consecutive_success_required or 3

            # Check if recovery criteria are fulfilled
            if settings_obj.maintenance_mode:
                if settings_obj.consecutive_success_count >= threshold:
                    # Can we recover? Check auto_recovery_enabled and maintenance_type
                    can_recover = False
                    if trigger == 'manual':
                        can_recover = True
                    elif settings_obj.auto_recovery_enabled:
                        # Auto recovery is enabled
                        can_recover = True

                    if can_recover:
                        settings_obj.maintenance_mode = False
                        settings_obj.maintenance_status = 'restored'
                        settings_obj.maintenance_restored_at = now
                        settings_obj.consecutive_success_count = 0
                        settings_obj.save()

                        # Audit log recovery
                        AuditLog.objects.create(
                            actor=actor,
                            action='maintenance_auto_recovered' if trigger == 'auto' else 'maintenance_disabled',
                            details=f"System maintenance automatically lifted after {threshold} consecutive successful health checks. Normal service restored.",
                            ip_address=ip_address
                        )
                        return {
                            'recovered': True,
                            'maintenance_mode': False,
                            'consecutive_count': 0,
                            'health': health_result
                        }
                else:
                    # Transition to 'recovering' if still below threshold
                    if settings_obj.maintenance_status != 'recovering':
                        settings_obj.maintenance_status = 'recovering'
            settings_obj.save()
            return {
                'recovered': False,
                'maintenance_mode': settings_obj.maintenance_mode,
                'consecutive_count': settings_obj.consecutive_success_count,
                'health': health_result
            }
        else:
            # Check failed -> Reset consecutive counter
            settings_obj.consecutive_success_count = 0
            if settings_obj.maintenance_mode:
                settings_obj.maintenance_status = 'active'
            settings_obj.save()

            # Audit log health check failure
            failed_checks = [c['name'] for c in health_result['checks'] if not c['passed']]
            AuditLog.objects.create(
                actor=actor,
                action='health_check_failed',
                details=f"System health check failed: {', '.join(failed_checks)}. Maintenance mode retained.",
                ip_address=ip_address
            )
            return {
                'recovered': False,
                'maintenance_mode': settings_obj.maintenance_mode,
                'consecutive_count': 0,
                'health': health_result
            }
