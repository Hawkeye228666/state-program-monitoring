"""Connection failures should explain the recovery without revealing a password."""
from unittest.mock import MagicMock,patch
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError
from django.test import SimpleTestCase


class ReadinessTests(SimpleTestCase):
    @patch('monitor.management.commands.wait_for_db.connections')
    def test_wrong_password_points_to_launcher_without_exposing_exception(self, connections):
        connection=MagicMock()
        connections.__getitem__.return_value=connection
        connection.cursor.side_effect=OperationalError('password authentication failed; private-token-not-for-logs')
        with self.assertRaises(CommandError) as result:
            call_command('wait_for_db',timeout=0)
        self.assertIn('run_windows.bat',str(result.exception))
        self.assertNotIn('private-token-not-for-logs',str(result.exception))
        connection.close.assert_called_once()

    @patch('monitor.management.commands.wait_for_db.connections')
    def test_unreachable_server_reports_connection_settings(self, connections):
        connections.__getitem__.return_value.cursor.side_effect=OperationalError('connection refused')
        with self.assertRaisesMessage(CommandError,'POSTGRES_HOST/PORT'):
            call_command('wait_for_db',timeout=0)
