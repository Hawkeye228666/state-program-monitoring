"""Consistent PostgreSQL + imported-file backup. Run from the repository root."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from docker_ops import compose, fingerprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = (args.output or Path('backups') / stamp).resolve()
    target.mkdir(parents=True, exist_ok=False)
    running = compose('ps', '--status', 'running', '--services', capture=True).stdout.splitlines()
    was_running = 'app' in running
    if was_running:
        compose('stop', 'app')
    name = 'monitor-' + stamp + '.dump'
    try:
        before = fingerprint()
        compose('exec', '-T', 'db', 'sh', '-ec',
            'pg_dump -h /var/run/postgresql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-privileges -f "/backups/$1"', 'sh', name)
        compose('cp', 'db:/backups/' + name, target / 'database.dump')
        compose('cp', 'app:/app/data', target / 'media')
        (target / 'fingerprint.json').write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding='utf-8')
        (target / 'backup.json').write_text(json.dumps({'created': stamp, 'status': 'complete', 'database': 'database.dump', 'media': 'media', 'format': 'pg_dump custom, no owner/ACL'}, indent=2), encoding='utf-8')
        print('Backup complete:', target)
    finally:
        if was_running:
            compose('start', 'app')

if __name__ == '__main__':
    main()
