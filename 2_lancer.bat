@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m jarvis
if errorlevel 1 pause
