"""Restore to a NEW database, then compare every row and imported file checksum."""
import argparse
import json
from pathlib import Path
from docker_ops import compose, fingerprint, safe_name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True, type=Path)
    parser.add_argument('--database', required=True)
    args = parser.parse_args()
    target = safe_name(args.database)
    backup = args.backup.resolve(strict=True)
    metadata = json.loads((backup / 'backup.json').read_text(encoding='utf-8'))
    if metadata['status'] != 'complete':
        raise ValueError('Backup was not completed.')
    expected = json.loads((backup / 'fingerprint.json').read_text(encoding='utf-8'))
    # A fresh database is mandatory. CREATE DATABASE fails if the name already exists.
    compose('exec', '-T', 'db', 'sh', '-ec',
        '[ "$1" != "$POSTGRES_DB" ] || { echo "Refusing to overwrite active database" >&2; exit 1; }; PGPASSWORD="$POSTGRES_PASSWORD" createdb -h 127.0.0.1 -U "$POSTGRES_USER" -O "$POSTGRES_APP_USER" "$1"', 'sh', target)
    dump = 'restore-' + target + '.dump'
    compose('cp', backup / 'database.dump', 'db:/backups/' + dump)
    compose('exec', '-T', 'db', 'sh', '-ec',
        'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore -h 127.0.0.1 -U "$POSTGRES_USER" --role="$POSTGRES_APP_USER" --no-owner --no-privileges --exit-on-error -d "$1" "/backups/$2"', 'sh', target, dump)
    actual = fingerprint(target, backup / 'media')
    if expected != actual:
        raise RuntimeError('Restored database or source-file fingerprint differs from backup; do not switch the application.')
    (backup / ('restore-' + target + '.json')).write_text(json.dumps({'status': 'success', 'database': target, 'fingerprint_equal': True}, indent=2), encoding='utf-8')
    print('Restore verified in isolated database:', target)
    print('The active database and its source-file volume were not changed.')

if __name__ == '__main__':
    main()
