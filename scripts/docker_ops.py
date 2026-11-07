"""Docker CLI orchestration. No shell interpolation or binary stdout redirection."""
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def compose(*args, capture=False):
    return subprocess.run(['docker', 'compose', *map(str, args)], cwd=ROOT, check=True, text=True, capture_output=capture)

def safe_name(value):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,62}', value):
        raise ValueError('Database name must be a simple PostgreSQL identifier (up to 63 characters).')
    return value

def fingerprint(database=None, media=None):
    args = ['run', '--rm', '--no-deps']
    if database:
        args += ['-e', 'POSTGRES_DB=' + safe_name(database)]
    if media:
        args += ['-e', 'MONITOR_MEDIA_ROOT=/restore-media', '-v', str(Path(media).resolve()) + ':/restore-media:ro']
    result = compose(*args, 'app', 'python', 'manage.py', 'db_fingerprint', '--check-files', capture=True)
    return json.loads(result.stdout)
