@echo off
chcp 65001 >nul
title J.A.R.V.I.S. - Compilation
cd /d "%~dp0"
call .venv\Scripts\activate.bat
for /f "delims=" %%i in ('python -c "import openwakeword,os;print(os.path.dirname(openwakeword.__file__))"') do set OWW=%%i
pyinstaller --noconfirm --clean --windowed --name Jarvis ^
  --icon assets\jarvis.ico ^
  --add-data "assets;assets" ^
  --add-data "%OWW%;openwakeword" ^
  --collect-all onnxruntime ^
  --collect-all edge_tts ^
  --collect-all sounddevice ^
  --hidden-import pystray._win32 ^
  run_jarvis.py
echo.
echo   Termine : dist\Jarvis\Jarvis.exe
explorer dist\Jarvis
pause
