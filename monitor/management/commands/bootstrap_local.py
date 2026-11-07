"""Prepare the local demo; --no-admin supports unattended checks."""
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Миграции, справочники, роли, статика и интерактивное создание первой учётной записи.'

    def add_arguments(self, parser):
        parser.add_argument('--no-admin', action='store_true', help='Не запрашивать создание пользователя (для проверок).')

    def handle(self, *args, **options):
        common = {'stdout': self.stdout, 'stderr': self.stderr}
        call_command('migrate', interactive=False, **common)
        call_command('seed_programs', **common)
        call_command('setup_roles', **common)
        call_command('collectstatic', interactive=False, **common)
        if not options['no_admin']:
            call_command('ensure_local_admin', **common)
        self.stdout.write('Локальный проект подготовлен. Запуск: python manage.py runserver 127.0.0.1:8000')
