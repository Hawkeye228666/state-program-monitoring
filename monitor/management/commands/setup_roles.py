from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission


class Command(BaseCommand):
    help = 'Создать/обновить роли пилотного модуля без создания пользователей и паролей.'

    def handle(self, *args, **options):
        read = Permission.objects.filter(content_type__app_label='monitor', codename__startswith='view_')
        role_permissions = {
            'Аналитик': list(read),
            'Оператор загрузки': list(read) + list(Permission.objects.filter(content_type__app_label='monitor', codename='add_importrun')),
            'Администратор': list(Permission.objects.filter(content_type__app_label__in=['monitor', 'auth'])),
        }
        for name, permissions in role_permissions.items():
            group, _ = Group.objects.get_or_create(name=name)
            group.permissions.set(permissions)
            self.stdout.write(f'{name}: {len(permissions)} прав')
        self.stdout.write('Назначьте группы пользователям через createsuperuser и /admin/. Для входа в /admin/ нужен is_staff.')
