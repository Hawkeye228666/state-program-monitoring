"""Configure local Compose secrets; preserve every nonempty existing value."""
import os
import re
from pathlib import Path
import secrets


def main():
    root = Path(__file__).resolve().parent.parent
    target = root / '.env'
    exists = target.exists()
    template = (target if exists else root / '.env.example').read_text(encoding='utf-8-sig')
    changed = False
    for key in ('DJANGO_SECRET_KEY', 'POSTGRES_ADMIN_PASSWORD', 'POSTGRES_APP_PASSWORD'):
        token = secrets.token_urlsafe(48)
        pattern = r'^' + key + r'=([^\n]*)$'
        match = re.search(pattern, template, re.M)
        if match and match[1].strip() not in ('', '""', "''"):
            continue
        if match:
            template = re.sub(pattern, key + '=' + token, template, flags=re.M)
        else:
            template = template.rstrip('\n') + '\n' + key + '=' + token + '\n'
        changed = True
    if not changed:
        print('.env уже настроен. Существующие секреты сохранены.')
        return
    flags = os.O_WRONLY | (os.O_TRUNC if exists else os.O_CREAT | os.O_EXCL)
    descriptor = os.open(target, flags, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as output:
        output.write(template)
    print('.env настроен. Непустые секреты сохранены; недостающие сгенерированы. Значения не выводятся.')


if __name__ == '__main__':
    main()
