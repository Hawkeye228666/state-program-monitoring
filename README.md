# Мониторинг государственных программ — PostgreSQL

Единственная СУБД во всех окружениях — PostgreSQL17. Приложение Django5.2/Gunicorn/WhiteNoise. В Git нет рабочей БД, пользователей, дампов или секретов. Исходники:6неизменённых SDMX и оригинальные материалы. Все программы, фильтры, ОКФС/кварталы, графики, CSV/API и роли сохранены.

## Получение текущей версии

Пока PR2 не объединён, клонируйте рабочую ветку явно:

```text
git clone --branch feature/postgres-okfs-analytics https://github.com/Hawkeye228666/state-program-monitoring.git
cd state-program-monitoring
```

Либо скачайте ZIP именно этой ветки. В основную ветку автоматического слияния нет.

## Первый запуск Windows и Linux

Нужны Docker Engine/Desktop с Linux-контейнерами, Compose v2 и Python3.12+ для генератора окружения. Выполняйте из корня скачанного проекта:

```text
python scripts/create_env.py
docker compose config --quiet
docker compose up --build -d --wait app
docker compose exec app python manage.py bootstrap_postgres --load-data
docker compose exec app python manage.py createsuperuser
```

Откройте http://127.0.0.1:8000/ и войдите под созданной учётной записью. Администратор назначает группы через /admin/. Паролей по умолчанию нет. run_windows.bat — только обёртка Docker Compose; первоначальная загрузка и создание пользователя выполняются командами выше. Для первого запуска с py launcher можно заменить python на py -3.14.

bootstrap_postgres ждёт подключения, применяет миграции и настраивает группы. Флаг --load-data явно импортирует6исходных файлов:6792наблюдения. Повторный явный импорт не дублирует строки и сохраняет пользовательские метаданные. При обычном up данные не загружаются заново. Новой установке никакая прежняя БД не нужна.

## Разработка

Используйте тот же Compose PostgreSQL. Для собственного Python-окружения установите requirements.txt и передайте POSTGRES_DB, POSTGRES_APP_USER, POSTGRES_APP_PASSWORD, POSTGRES_HOST, POSTGRES_PORT и DJANGO_SECRET_KEY. compose читает .env; самостоятельный Python автоматически .env не читает. При неполной конфигурации — понятная ошибка, другая БД не создаётся. DATABASE_URL не поддерживается. wait_for_db проверяет аутентифицированное соединение, healthz проверяет доступность БД. Рабочая роль не имеет SUPERUSER/CREATEDB/CREATEROLE.

## Тесты только в отдельном PostgreSQL

GitHub Actions создаёт отдельный PostgreSQL и роль monitor_ci с CREATEDB только для тестов. Локальный изолированный проект использует собственные тома и роль monitor_test:

```text
docker compose -p monitor-tests -f compose.yaml -f compose.test.yaml up -d --wait db
docker compose -p monitor-tests -f compose.yaml -f compose.test.yaml exec db psql -U postgres -d monitor_testdb -c "ALTER ROLE monitor_test CREATEDB;"
docker compose -p monitor-tests -f compose.yaml -f compose.test.yaml run --build --rm --no-deps app python manage.py test monitor --noinput
docker compose -p monitor-tests -f compose.yaml -f compose.test.yaml stop
```

Django создаёт test_monitor_testdb; рабочая monitor не очищается. Не выполняйте grant CREATEDB для рабочей роли. Проверяются чистые миграции и обновление прежней PostgreSQL, точные числа, ОКФС199/200, кварталы, повторный импорт, CSV/API/графики и права. Числа: DecimalField NUMERIC(80,30),50целых/30дробных знаков; импорт отклоняет превышение, миграция проверяет точность до изменения схемы. raw_value сохраняется.

## Обновление, копирование и остановка

```text
python scripts/backup.py --output backups/before-update-01
docker compose stop app
docker compose build
docker compose run --rm migrate
docker compose up -d --wait app
docker compose logs --tail 100 app db migrate
python scripts/restore.py --backup backups/before-update-01 --database monitor_restore_check
docker compose stop
```

Имя каталога копии и тестовой БД должно быть новым. backup.py останавливает приложение для согласованного pg_dump и XML, затем возвращает его. restore.py создаёт отдельную БД и сверяет все строки/файлы, рабочую БД не перезаписывает. Том PostgreSQL17 — /var/lib/postgresql/data; исходники/загрузки — отдельный sources. stop/down сохраняют тома. Не используйте удаление томов при обновлении. Откат: восстановить согласованную БД и XML в отдельные БД/том, проверить, переключить конфигурацию вместе с совместимой версией кода. Копии с пользователями хранить вне Git.

Предыдущие данные однократно сохранены до удаления прежнего режима: docs/data-preservation.md. Это выполненная операция, а не поддерживаемый путь установки. Старый класс поля оставлен только для миграции0002, действующая модель использует штатный DecimalField;0003проверяет и переводит существующую PostgreSQL без округления.

Материалы защиты: deliverables/. Аудит ОКФС, описание графиков, API и предложение пилота Мосстата: docs/. Корпоративное внедрение/SSO не заявлены. Итог проверок: docs/postgres-only-verification.md.
