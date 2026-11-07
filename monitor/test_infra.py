"""Storage and real SQLite-to-PostgreSQL integration tests."""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
from unittest import skipUnless
from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, IntegrityError, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from monitor.models import Program, Indicator, Territory, Period, Observation, SourceFile, ImportRun
from monitor.fields import ExactNumericTextField
from monitor.transfer import transfer_sqlite

class ExactStorageTests(TestCase):
    def test_exact_number_roundtrip_and_missing_value(self):
        program = Program.objects.create(slug='storage-test', name='test', summary='', schedule='')
        indicator = Indicator.objects.create(program=program, file_id='storage-test', metadata_id='test', name='test')
        territory = Territory.objects.create(code='00001', name='test', kind='subject')
        period = Period.objects.create(code='2020', label='2020', year=2020, order='2020-00')
        source = SourceFile.objects.create(sha256='0'*64, filename='test.sdmx', original_path='test.sdmx', size=0, header_id='test', dataset_id='test')
        run = ImportRun.objects.create(status='success')
        text = '12345678901234567890.123456789012345678901234567890'
        row = Observation.objects.create(indicator=indicator, territory=territory, period=period, source=source, last_import=run, dimension_key=hashlib.sha256(b'{}').hexdigest(), numeric_text=text, raw_value=text)
        row.refresh_from_db()
        self.assertEqual(row.numeric_text, text)
        self.assertEqual(row.number, Decimal(text))
        self.assertEqual(row.territory.code, '00001')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Observation.objects.create(indicator=indicator, territory=territory, period=period, source=source, last_import=run, dimension_key=row.dimension_key, numeric_text=None)
        if connection.vendor == 'postgresql':
            with connection.cursor() as c:
                c.execute("SELECT data_type FROM information_schema.columns WHERE table_name='monitor_observation' AND column_name='numeric_text'")
                self.assertEqual(c.fetchone()[0], 'numeric')
            with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as c:
                c.execute("UPDATE monitor_observation SET numeric_text='NaN'::numeric WHERE id=%s", [row.pk])

    def test_nonfinite_numbers_rejected(self):
        field = ExactNumericTextField()
        for value in ['NaN', 'Infinity', '-Infinity', 'not a number']:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                field.get_prep_value(value)

@skipUnless(connection.vendor == 'postgresql', 'A real PostgreSQL server is required for the lossless migration test.')
class PostgreSQLTransferTests(TransactionTestCase):
    reset_sequences = True
    def test_transfer_preserves_actual_data_users_edits_history_and_sequences(self):
        with tempfile.TemporaryDirectory(dir=settings.BASE_DIR.parent) as temp:
            temp = Path(temp)
            source = temp / 'legacy.sqlite3'
            original = sqlite3.connect((settings.BASE_DIR/'db.sqlite3').as_uri()+'?mode=ro', uri=True)
            target = sqlite3.connect(source)
            original.backup(target)
            original.close();target.close()
            env = os.environ.copy()
            env['PYTHONPATH'] = os.pathsep.join(p for p in sys.path if p)
            env.update(DB_ENGINE='sqlite', MONITOR_DB=str(source), MONITOR_MEDIA_ROOT=str(temp/'legacy-media'))
            subprocess.run([sys.executable, 'manage.py', 'migrate', '--noinput'], cwd=settings.BASE_DIR, env=env, check=True, capture_output=True, timeout=60)
            code = "from django.contrib.auth.models import User,Group,Permission; from monitor.models import Program,ImportRun; u=User.objects.create_user('legacy-transfer-user',password='test-only-password'); g=Group.objects.create(name='legacy-custom-group'); g.permissions.add(Permission.objects.get(codename='view_observation')); u.groups.add(g); Program.objects.filter(slug='housing').update(summary='Legacy user-edited metadata'); ImportRun.objects.create(actor=u,status='error',message='Historical failure preserved')"
            subprocess.run([sys.executable, 'manage.py', 'shell', '-c', code], cwd=settings.BASE_DIR, env=env, check=True, capture_output=True, timeout=60)
            with sqlite3.connect(source) as raw:
                original_joined = datetime.fromisoformat(raw.execute("SELECT date_joined FROM auth_user WHERE username='legacy-transfer-user'").fetchone()[0]).replace(tzinfo=timezone.utc)
            with override_settings(MEDIA_ROOT=temp/'new-media'):
                report = transfer_sqlite(source, temp/'backups', settings.BASE_DIR/'data')
                self.assertEqual(Observation.objects.count(), 6792)
                self.assertEqual(Program.objects.get(slug='housing').summary, 'Legacy user-edited metadata')
                user = User.objects.get(username='legacy-transfer-user')
                self.assertTrue(user.check_password('test-only-password'))
                self.assertEqual(user.date_joined, original_joined)
                self.assertTrue(user.has_perm('monitor.view_observation'))
                self.assertEqual(ImportRun.objects.get(message='Historical failure preserved').actor_id, user.pk)
                self.assertGreater(User.objects.create_user('next-user').pk, user.pk)
                self.assertEqual(report['media_files'], 6)
                self.assertEqual(report['foreign_keys'], 'checked')
                self.assertTrue(Path(report['snapshot']).is_file())
                with self.assertRaises(CommandError):
                    transfer_sqlite(source, temp/'backups', settings.BASE_DIR/'data')
