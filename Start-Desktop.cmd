@echo off
setlocal
cd /d "%~dp0"
set "FYPPPPP_DATA_DIR=%~dp0.local\workspace-clean"
if not exist "dist\index.html" (
  echo Please run npm run build first.
  pause
  exit /b 1
)
call npm run desktop
