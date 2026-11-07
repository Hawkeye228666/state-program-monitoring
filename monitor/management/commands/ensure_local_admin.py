"""Interactive first account creation, without a default or generated password."""
import sys
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


def has_local_reader():
    # An existing disabled account, unusable password or account without access
    # must not leave a first-time user facing an unusable login screen.
    return any(bool(user.password) and user.has_usable_password() and user.has_perm('monitor.view_observation')
               for user in get_user_model().objects.filter(is_active=True).iterator())


class Command(BaseCommand):
    help = 'При отсутствии доступного локального читателя интерактивно создать первого администратора.'

    def handle(self, *args, **options):
        if has_local_reader():
            self.stdout.write('Учётная запись для входа уже существует. Используйте свой логин и пароль.')
            return
        self.stdout.write('Создайте первую учётную запись администратора. Пароль задаёте вы; при вводе он не отображается.')
        if not sys.stdin.isatty():
            raise CommandError('Откройте интерактивный терминал и выполните python manage.py createsuperuser. Готового пароля в проекте нет.')
        call_command('createsuperuser', interactive=True, stdout=self.stdout, stderr=self.stderr)
        if not has_local_reader():
            raise CommandError('Рабочая учётная запись не создана. Повторите python manage.py createsuperuser.')
