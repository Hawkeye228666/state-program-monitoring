@echo off
cd /d "%~dp0"
where docker >nul 2>&1
if errorlevel 1 goto error
if not exist .env (
 echo Create .env first: python scripts/create_env.py
 goto error
)
docker compose config --quiet
if errorlevel 1 goto error
docker compose up --build -d --wait app
if errorlevel 1 goto error
echo Open http://127.0.0.1:8000/ . First setup commands are in README.md
exit /b 0
:error
echo Docker Compose setup failed. See README.md
pause
exit /b 1
