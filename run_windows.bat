@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
if errorlevel 1 (
 echo Startup failed. Read the error above, then run this file again.
 pause
 exit /b 1
)
exit /b 0
