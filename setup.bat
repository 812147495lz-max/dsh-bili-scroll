@echo off
cd /d "%~dp0"
set "PY="
if exist "%~dp0python-path.txt" set /p PY=<"%~dp0python-path.txt"
if not defined PY (
  where py >nul 2>nul
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo Python 3.10+ not found.
  echo Install it from https://www.python.org/downloads/
  echo Or put the full path of python.exe into python-path.txt
  exit /b 1
)
echo Using Python: %PY%
%PY% -m venv "%~dp0.venv"
if errorlevel 1 exit /b 1
"%~dp0.venv\Scripts\python.exe" -m pip install -U pip -i https://pypi.tuna.tsinghua.edu.cn/simple
"%~dp0.venv\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
  echo Dependency install failed.
  exit /b 1
)
echo Done.
