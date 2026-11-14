@echo off
chcp 65001 >nul
title J.A.R.V.I.S. - Installation
cd /d "%~dp0"
echo.
echo   === J.A.R.V.I.S. : installation ===
echo.
where py >nul 2>nul || (echo Python introuvable. Installe Python 3.11 x64 depuis python.org puis relance. & pause & exit /b 1)
if not exist .venv (
  echo Creation de l'environnement Python...
  py -3.11 -m venv .venv 2>nul || py -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo Telechargement du modele "Hey Jarvis"...
python -c "import openwakeword.utils as u; u.download_models(['hey_jarvis'])"
echo.
echo   Installation terminee. Lance 2_lancer.bat pour tester, ou 3_creer_exe.bat pour le .exe.
pause
