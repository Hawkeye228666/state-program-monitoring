"""Native PostgreSQL exact decimal storage tests."""
from contextlib import closing
import hashlib
import json
import os

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
from django.core.validators import DecimalValidator


class ExactStorageTests(TestCase):
    def test_exact_number_roundtrip_and_missing_value(self):
        program = Program.objects.create(slug='storage-test', name='test', summary='', schedule='')
        indicator = Indicator.objects.create(program=program, file_id='storage-test', metadata_id='test', name='test')
        territory = Territory.objects.create(code='00001', name='test', kind='subject')
        period = Period.objects.create(code='2020', label='2020', year=2020, order='2020-00')
        source = SourceFile.objects.create(sha256='0'*64, filename='test.sdmx', original_path='test.sdmx', size=0, header_id='test', dataset_id='test')
        run = ImportRun.objects.create(status='success')
        text = '12345678901234567890.123456789012345678901234567890'
        row = Observation.objects.create(indicator=indicator, territory=territory, period=period, source=source, last_import=run, dimension_key=hashlib.sha256(b'{}').hexdigest(), numeric_value=Decimal(text), raw_value=text)
        row.refresh_from_db()
        self.assertEqual(row.numeric_value, Decimal(text))
        self.assertEqual(row.number, Decimal(text))
        self.assertEqual(row.territory.code, '00001')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Observation.objects.create(indicator=indicator, territory=territory, period=period, source=source, last_import=run, dimension_key=row.dimension_key, numeric_value=None)
        if connection.vendor == 'postgresql':
            with connection.cursor() as c:
                c.execute("SELECT data_type FROM information_schema.columns WHERE table_name='monitor_observation' AND column_name='numeric_value'")
                self.assertEqual(c.fetchone()[0], 'numeric')
            with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as c:
                c.execute("UPDATE monitor_observation SET numeric_value='NaN'::numeric WHERE id=%s", [row.pk])

    def test_nonfinite_and_excess_precision_rejected(self):
        field=Observation._meta.get_field('numeric_value')
        for value in ['NaN','Infinity','-Infinity','not a number','0.'+'1'*31]:
            with self.subTest(value=value),self.assertRaises(ValidationError):field.clean(value,None)
