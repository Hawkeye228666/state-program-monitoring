import json
from django.core.management.base import BaseCommand, CommandError
from monitor.transfer import transfer_sqlite

class Command(BaseCommand):
    help = 'Back up SQLite, transfer all persisted rows/files to an empty PostgreSQL database, verify full-row digests and reset sequences.'
    def add_arguments(self, parser):
        parser.add_argument('--source', required=True)
        parser.add_argument('--backup-dir', required=True)
        parser.add_argument('--media-source')
    def handle(self, *args, **options):
        try:
            report = transfer_sqlite(options['source'], options['backup_dir'], options['media_source'])
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
