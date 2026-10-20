@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Missing .venv - run setup.bat first.
  pause
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --name BiliPick ^
  --add-data "web;web" ^
  --collect-data bilibili_api ^
  --distpath "%~dp0dist" ^
  --workpath "%~dp0build" ^
  "%~dp0app.py"
echo.
echo Output: %~dp0dist\BiliPick.exe
pause
