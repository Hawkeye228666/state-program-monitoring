"""Create a local Compose .env exclusively; never print or overwrite secrets."""
import os
from pathlib import Path
import secrets


def main():
    root = Path(__file__).resolve().parent.parent
    target = root / '.env'
    template = (root / '.env.example').read_text(encoding='utf-8-sig')
    for key in ('DJANGO_SECRET_KEY', 'POSTGRES_ADMIN_PASSWORD', 'POSTGRES_APP_PASSWORD'):
        token = secrets.token_urlsafe(48)
        marker = key + '=\n'
        if marker not in template:
            raise SystemExit('В .env.example отсутствует пустое поле ' + key)
        template = template.replace(marker, key + '=' + token + '\n', 1)
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SystemExit('.env уже существует. Файл и его секреты сохранены; повторная генерация не выполнена.')
    with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as output:
        output.write(template)
    print('Создан .env с тремя независимыми секретами. Значения не выводятся; не добавляйте файл в Git.')


if __name__ == '__main__':
    main()
