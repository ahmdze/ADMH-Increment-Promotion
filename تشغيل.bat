@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=%LOCALAPPDATA%\Python\bin\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" run.py
if errorlevel 1 pause
