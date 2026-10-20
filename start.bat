@echo off
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" goto run
echo First run: creating Python environment, this may take a few minutes...
call "%~dp0setup.bat"
:run
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Failed to create environment.
  echo Please install Python 3.10+ from https://www.python.org/downloads/
  pause
  exit /b 1
)
echo Starting BiliPick ... keep this window open.
"%~dp0.venv\Scripts\python.exe" "%~dp0app.py"
pause
