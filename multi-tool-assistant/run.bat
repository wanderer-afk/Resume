@echo off
rem Starts the assistant's web page on this PC. Double-click this file, then open http://127.0.0.1:8000
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1

rem Find Python
set PY=
where py >nul 2>nul
if not errorlevel 1 set PY=py -3
if "%PY%"=="" (
  where python >nul 2>nul
  if not errorlevel 1 set PY=python
)
if "%PY%"=="" (
  echo Python is not installed on this PC, or it is not on your PATH.
  echo.
  echo To fix it: install Python 3.11 or newer from https://www.python.org/downloads/
  echo On the first install screen, tick "Add python.exe to PATH". Then double-click run.bat again.
  echo.
  pause
  exit /b 1
)

rem Install the app's packages the first time (or if they are missing)
%PY% -c "import requests, anthropic" >nul 2>nul
if errorlevel 1 (
  echo Installing the packages the app needs. This happens once and can take a minute.
  %PY% -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo The packages could not be installed. Check your internet connection and run this file again.
    echo.
    pause
    exit /b 1
  )
)

echo.
echo Starting the assistant.
echo Open this address in your browser:  http://127.0.0.1:8000
echo Press Ctrl+C in this window to stop it.
echo.
%PY% main.py --web %*
if errorlevel 1 (
  echo.
  echo The assistant stopped with an error. If port 8000 is already in use, close the other program and try again.
  echo.
  pause
)
