@echo off
REM ---------------------------------------------------------------------------
REM Hermes status API launcher (read-only status surface for Homepage).
REM Uses this folder's own .venv so it does not depend on the Hermes venv.
REM Started at logon by the "HermesStatusAPI" scheduled task.
REM ---------------------------------------------------------------------------
set "APPDIR=C:\Users\Admin\docker\homepage\status-api"
cd /d "%APPDIR%"

REM Keep the log from growing without bound.
if exist "%APPDIR%\status-api.log" (
  for %%A in ("%APPDIR%\status-api.log") do if %%~zA GTR 2000000 move /y "%APPDIR%\status-api.log" "%APPDIR%\status-api.log.1" >nul
)

"%APPDIR%\.venv\Scripts\python.exe" "%APPDIR%\status_api.py" >> "%APPDIR%\status-api.log" 2>&1