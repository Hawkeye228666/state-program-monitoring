"""Prevent working databases/secrets and retired backend code in the submitted tree."""
import subprocess
from pathlib import Path
files=subprocess.check_output(['git','ls-files','-z']).decode().split('\0')
for name in filter(None,files):
    lower=name.lower()
    assert not lower.endswith(('.sqlite','.sqlite3','.db','.dump','.bak')), 'Working database tracked: '+name
    assert not (name=='.env' or name.startswith('backups/')), 'Private runtime artifact tracked: '+name
    if name.endswith('.py') and Path(name).is_file():
        text=Path(name).read_text(encoding='utf-8')
        assert 'django.db.backends.'+'sqlite3' not in text, 'Retired backend: '+name
print('PostgreSQL-only repository guard passed')
