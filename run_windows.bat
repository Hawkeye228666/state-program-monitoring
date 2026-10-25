@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHON_CMD="
call :try_python py -3.14
call :try_python py -3.13
call :try_python py -3.12
for %%V in (314 313 312) do call :try_python "%LocalAppData%\Programs\Python\Python%%V\python.exe"
for %%V in (314 313 312) do call :try_python "%USERPROFILE%\AppData\Local\Programs\Python\Python%%V\python.exe"
for %%V in (314 313 312) do call :try_python "%ProgramFiles%\Python%%V\python.exe"
for /d %%P in ("%LocalAppData%\Python\pythoncore-3.14*" "%LocalAppData%\Python\pythoncore-3.13*" "%LocalAppData%\Python\pythoncore-3.12*") do call :try_python "%%~fP\python.exe"
if not defined PYTHON_CMD call :try_python python
if not defined PYTHON_CMD goto no_python
echo Найден Python: %PYTHON_CMD%
%PYTHON_CMD% --version
if /I "%~1"=="--detect" exit /b 0
if not exist manage.py (
  echo Файл запуска должен находиться рядом с manage.py в папке deliverables.
  goto error
)
if exist .venv\Scripts\python.exe goto environment_ready
echo Создание окружения проекта...
%PYTHON_CMD% -m venv .venv
if errorlevel 1 goto error
:environment_ready
.venv\Scripts\python.exe -c "import sys; raise SystemExit(0 if sys.version_info[:2] in ((3,12),(3,13),(3,14)) else 1)"
if errorlevel 1 (
  echo Существующее окружение .venv повреждено или использует другую версию Python.
  echo Переименуйте папку .venv в .venv_old и повторите запуск.
  goto error
)
echo Установка зависимостей...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto error
.venv\Scripts\python.exe manage.py migrate
if errorlevel 1 goto error
.venv\Scripts\python.exe manage.py seed_programs
if errorlevel 1 goto error
if /I "%~1"=="--check" goto verify
echo.
echo Сайт: http://127.0.0.1:8000/
echo Откройте этот адрес в браузере. Это окно не закрывайте.
echo Для остановки сервера нажмите Ctrl+C.
echo.
.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
if errorlevel 1 goto error
exit /b 0
:verify
.venv\Scripts\python.exe manage.py check
if errorlevel 1 goto error
.venv\Scripts\python.exe manage.py test monitor --verbosity 1
if errorlevel 1 goto error
exit /b 0
:try_python
if defined PYTHON_CMD exit /b 0
%* -c "import sys; raise SystemExit(0 if sys.version_info[:2] in ((3,12),(3,13),(3,14)) else 1)" >nul 2>&1
if errorlevel 1 exit /b 0
set "PYTHON_CMD=%*"
exit /b 0
:no_python
echo Не найден установленный Python 3.12, 3.13 или 3.14.
echo Если вы только скачали установщик, сначала запустите его и завершите установку.
:error
echo.
echo Запуск не завершён. Сообщение об ошибке находится выше.
if /I not "%~1"=="--check" if /I not "%~1"=="--detect" pause
exit /b 1
