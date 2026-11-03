import os
import sys
from pathlib import Path

# Add project root directory to path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hostel_Management_System.settings')

from django.core.wsgi import get_wsgi_application
from django.core.management import call_command

# Initialize Django WSGI application
app = get_wsgi_application()

# Auto-migrate database & seed modules on deployment startup only when pending migrations exist
if os.getenv('AUTO_MIGRATE', 'True').lower() in ('true', '1') and not os.getenv('SKIP_STARTUP_MIGRATIONS'):
    try:
        from django.db.migrations.executor import MigrationExecutor
        from django.db import connections, DEFAULT_DB_ALIAS
        connection = connections[DEFAULT_DB_ALIAS]
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if plan:
            call_command('migrate', interactive=False, verbosity=0)
            call_command('seed_modules')
            call_command('seed_super_admin')
    except Exception as e:
        print(f"Auto-migrate info: {e}")
