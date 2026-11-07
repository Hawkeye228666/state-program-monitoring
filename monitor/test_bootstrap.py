"""A first run must not be blocked by inactive/unauthorised accounts."""
import io
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from .management.commands.ensure_local_admin import has_local_reader


class LocalBootstrapAccountTests(TestCase):
    def test_existing_reader_is_kept_without_password_prompt(self):
        user = get_user_model().objects.create_user('reader', password='only-for-this-test')
        user.user_permissions.add(Permission.objects.get(codename='view_observation', content_type__app_label='monitor'))
        with patch('monitor.management.commands.ensure_local_admin.call_command') as create:
            call_command('ensure_local_admin', stdout=io.StringIO())
        create.assert_not_called()
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_disabled_no_password_and_unauthorised_users_do_not_block_first_account(self):
        User = get_user_model()
        User.objects.create_superuser('inactive', password='only-for-this-test', is_active=False)
        User.objects.create_superuser('no-password', password=None)
        User.objects.create_user('without-permission', password='only-for-this-test')
        self.assertFalse(has_local_reader())
        with patch('sys.stdin.isatty', return_value=False), self.assertRaisesMessage(CommandError, 'интерактивный терминал'):
            call_command('ensure_local_admin', stdout=io.StringIO())
        self.assertEqual(User.objects.count(), 3)

    def test_first_admin_uses_interactive_django_creation(self):
        def interactive_create(name, **kwargs):
            self.assertEqual(name, 'createsuperuser')
            self.assertTrue(kwargs['interactive'])
            self.assertNotIn('password', kwargs)
            get_user_model().objects.create_superuser('entered-by-user', password='only-for-this-test')
        with patch('sys.stdin.isatty', return_value=True), patch('monitor.management.commands.ensure_local_admin.call_command', side_effect=interactive_create) as create:
            call_command('ensure_local_admin', stdout=io.StringIO())
        create.assert_called_once()
        self.assertTrue(has_local_reader())

    def test_cancelled_creation_never_claims_that_account_exists(self):
        with patch('sys.stdin.isatty', return_value=True), patch('monitor.management.commands.ensure_local_admin.call_command'), self.assertRaisesMessage(CommandError, 'не создана'):
            call_command('ensure_local_admin', stdout=io.StringIO())
        self.assertFalse(get_user_model().objects.exists())
