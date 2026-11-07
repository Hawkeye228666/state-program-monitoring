"""First start must load sources once and preserve existing accounts/data."""
from unittest.mock import patch
from django.core.management import call_command
from django.test import SimpleTestCase


class FirstStartTests(SimpleTestCase):
    @patch('monitor.management.commands.bootstrap_postgres.call_command')
    @patch('monitor.management.commands.bootstrap_postgres.get_user_model')
    @patch('monitor.management.commands.bootstrap_postgres.Observation')
    def test_empty_database_loads_original_sources_and_creates_admin(self, observations, users, command):
        observations.objects.exists.return_value=False
        users.return_value.objects.filter.return_value.exists.side_effect=[False,True]
        call_command('bootstrap_postgres',load_if_empty=True,create_admin=True)
        names=[item.args[0] for item in command.call_args_list]
        self.assertEqual(names,['wait_for_db','migrate','setup_roles','import_sdmx','createsuperuser'])
        self.assertEqual(len(command.call_args_list[3].args[1:]),6)

    @patch('monitor.management.commands.bootstrap_postgres.call_command')
    @patch('monitor.management.commands.bootstrap_postgres.get_user_model')
    @patch('monitor.management.commands.bootstrap_postgres.Observation')
    def test_repeat_start_preserves_data_and_admin(self, observations, users, command):
        observations.objects.exists.return_value=True
        users.return_value.objects.filter.return_value.exists.return_value=True
        call_command('bootstrap_postgres',load_if_empty=True,create_admin=True)
        self.assertEqual([item.args[0] for item in command.call_args_list],['wait_for_db','migrate','setup_roles'])

    @patch('monitor.management.commands.bootstrap_postgres.call_command')
    @patch('monitor.management.commands.bootstrap_postgres.Observation')
    def test_explicit_reload_still_supported(self, observations, command):
        observations.objects.exists.return_value=True
        call_command('bootstrap_postgres',load_data=True)
        self.assertIn('import_sdmx',[item.args[0] for item in command.call_args_list])
