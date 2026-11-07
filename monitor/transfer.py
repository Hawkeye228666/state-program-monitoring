"""Offline, transactional copy of an existing SQLite database, not XML reimport."""
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from django.apps import apps
from django.conf import settings
from django.contrib.auth.management import create_permissions
from django.contrib.contenttypes.management import create_contenttypes
from django.core.management.base import CommandError
from django.core.management.color import no_style
from django.db import connection, transaction
from django.db.models import JSONField, BooleanField, DateTimeField


def quote_sqlite(name):
    return '"' + name.replace('"', '""') + '"'


def canonical(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items()}
    return value


def source_value(field, value):
    if value is None:
        return None
    if isinstance(field, JSONField):
        return json.loads(value) if isinstance(value, str) else value
    if isinstance(field, BooleanField):
        return bool(value)
    value = field.to_python(value)
    # Django's SQLite adapter stores USE_TZ timestamps as naive UTC strings.
    if isinstance(field, DateTimeField) and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def digest(rows):
    payload = json.dumps(canonical(rows), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def transfer_sqlite(source, backup_dir, media_source=None):
    if connection.vendor != 'postgresql':
        raise CommandError('Destination must be PostgreSQL (DB_ENGINE=postgresql).')
    source = Path(source).resolve(strict=True)
    backup_dir = Path(backup_dir).resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    snapshot = backup_dir / ('sqlite-before-transfer-' + stamp + '.sqlite3')
    original = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
    backup = sqlite3.connect(snapshot)
    try:
        original.backup(backup)
    finally:
        backup.close()
        original.close()
    legacy = sqlite3.connect(snapshot.as_uri() + '?mode=ro', uri=True)
    legacy.row_factory = sqlite3.Row
    report = {'snapshot': str(snapshot), 'snapshot_sha256': hashlib.sha256(snapshot.read_bytes()).hexdigest(), 'tables': {}, 'media_files': 0}
    models = {m._meta.db_table: m for m in apps.get_models(include_auto_created=True)}
    try:
        if legacy.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or legacy.execute('PRAGMA foreign_key_check').fetchall():
            raise CommandError('SQLite snapshot failed integrity or foreign-key checks.')
        tables = [r[0] for r in legacy.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'django_migrations' ORDER BY name")]
        unknown = set(tables) - set(models)
        if unknown:
            raise CommandError('Unmapped source tables; refusing partial transfer: ' + ', '.join(sorted(unknown)))
        for name, model in models.items():
            if name not in ('django_content_type', 'auth_permission') and model._base_manager.exists():
                raise CommandError('Destination contains data in ' + name + '; use a fresh database, never overwrite an active database.')
        media_source = Path(media_source or source.parent / 'data').resolve()
        if 'monitor_sourcefile' in tables:
            for row in legacy.execute('SELECT original_path, sha256 FROM monitor_sourcefile'):
                relative = Path(row['original_path'])
                if relative.is_absolute() or '..' in relative.parts or ':' in str(relative):
                    raise CommandError('Unsafe source-file path in SQLite.')
                input_file = (media_source / relative).resolve()
                output_file = (Path(settings.MEDIA_ROOT) / relative).resolve()
                if not input_file.is_relative_to(media_source) or not output_file.is_relative_to(Path(settings.MEDIA_ROOT).resolve()):
                    raise CommandError('Source file escapes its storage directory.')
                if not input_file.is_file() or hashlib.sha256(input_file.read_bytes()).hexdigest() != row['sha256']:
                    raise CommandError('Missing or changed original source file: ' + str(relative))
                output_file.parent.mkdir(parents=True, exist_ok=True)
                if output_file.exists() and hashlib.sha256(output_file.read_bytes()).hexdigest() != row['sha256']:
                    raise CommandError('Conflicting destination source file: ' + str(relative))
                if input_file != output_file:
                    shutil.copy2(input_file, output_file)
                report['media_files'] += 1
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('SET CONSTRAINTS ALL DEFERRED')
                # Only generated content types/permissions may pre-exist. Preserve their source IDs.
                for name in reversed(list(models)):
                    cursor.execute('DELETE FROM ' + connection.ops.quote_name(name))
                for name in tables:
                    model = models[name]
                    fields = {f.column: f for f in model._meta.local_fields}
                    columns = [r[1] for r in legacy.execute('PRAGMA table_info(' + quote_sqlite(name) + ')')]
                    if set(columns) - set(fields):
                        raise CommandError('Unmapped columns in ' + name)
                    rows = legacy.execute('SELECT ' + ','.join(quote_sqlite(c) for c in columns) + ' FROM ' + quote_sqlite(name) + ' ORDER BY ' + quote_sqlite(model._meta.pk.column)).fetchall()
                    logical = [[source_value(fields[c], r[c]) for c in columns] for r in rows]
                    parameters = [[fields[c].get_db_prep_save(v, connection) for c, v in zip(columns, row)] for row in logical]
                    sql = 'INSERT INTO ' + connection.ops.quote_name(name) + ' (' + ','.join(connection.ops.quote_name(c) for c in columns) + ') VALUES (' + ','.join(['%s'] * len(columns)) + ')'
                    if parameters:
                        cursor.executemany(sql, parameters)
                    cursor.execute('SELECT ' + ','.join(connection.ops.quote_name(c) for c in columns) + ' FROM ' + connection.ops.quote_name(name) + ' ORDER BY ' + connection.ops.quote_name(model._meta.pk.column))
                    actual = cursor.fetchall()
                    # Raw DB cursors return JSON strings; normalize identically to the SQLite snapshot.
                    actual = [[source_value(fields[c], v) for c, v in zip(columns, row)] for row in actual]
                    if len(logical) != len(actual) or digest(logical) != digest(actual):
                        raise CommandError('Count or full-row fingerprint mismatch in ' + name)
                    report['tables'][name] = {'source': len(logical), 'target': len(actual), 'sha256': digest(actual)}
                for sql in connection.ops.sequence_reset_sql(no_style(), list(models.values())):
                    cursor.execute(sql)
            connection.check_constraints()
            # New auth/admin models can introduce additional content types/permissions.
            for app_config in apps.get_app_configs():
                create_contenttypes(app_config, verbosity=0)
                create_permissions(app_config, verbosity=0)
        report['status'] = 'success'
        report['foreign_keys'] = 'checked'
        report['sequences'] = 'reset to max(pk)'
        path = backup_dir / ('transfer-report-' + stamp + '.json')
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        report['report'] = str(path)
        return report
    finally:
        legacy.close()
