import time
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, OperationalError

class Command(BaseCommand):
    help = 'Wait for a real authenticated SELECT 1, not just an open TCP port.'
    def add_arguments(self, parser):
        parser.add_argument('--timeout', type=float, default=60)
    def handle(self, *args, **options):
        deadline = time.monotonic() + options['timeout']
        while True:
            try:
                with connections['default'].cursor() as cursor:
                    cursor.execute('SELECT 1')
                    if cursor.fetchone()[0] != 1:
                        raise OperationalError('Unexpected readiness result')
                self.stdout.write('Database ready (authenticated SELECT 1).')
                return
            except OperationalError as error:
                connections['default'].close()
                if time.monotonic() >= deadline:
                    detail = str(error).lower()
                    if 'password authentication failed' in detail:
                        raise CommandError('PostgreSQL rejected the application password. Run run_windows.bat to synchronize the app role with .env; keep the existing database volume.') from None
                    raise CommandError('Database not ready before timeout; check database logs and POSTGRES_HOST/PORT. Run the launcher for credential setup.') from None
                time.sleep(1)
