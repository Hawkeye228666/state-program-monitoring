# Проверки PostgreSQL-only

PostgreSQL17.11, Python3.12.14, Django5.2.19. Все54теста успешно,29.501с, без пропусков. Протокол: postgres-only-tests.log.

Проверены: миграции пустой БД; обновление существующей PostgreSQL6792строк с полной сверкой; импорт шести SDMX и повтор без дубликатов; Decimal NUMERIC(80,30), отклонение NaN/Infinity и превышения точности; ОКФС/кварталы; выборки/CSV/API/графики; права и CSRF. pg_dump/pg_restore в отдельную БД дал равные fingerprints; перезапуск PostgreSQL сохранил все строки/файлы. JSON-протокол рядом.

Docker локально не установлен. Обновлённый Compose/force-recreate/backup/restore выполняются в GitHub Actions; наличие YAML не считается прохождением. Финальный результат смотреть в проверках PR2. UI canvas/PNG в браузере отдельно не проверялся.

Из актуального дерева удалены базы, fallback, transfer_sqlite, bootstrap_local, локальный сервер на другой СУБД, прежние протоколы и презентации. Класс старого поля оставлен только для исторической0002, runtime его не использует.

## GitHub Actions

[42399019574](https://github.com/Hawkeye228666/state-program-monitoring/actions/runs/42399019574) — оба задания success: PostgreSQL и Compose. Проверены чистая сборка, явный импортSDMX и повтор,6792строки, backup/restore, готовность, UID10001, статика и force-recreate.
