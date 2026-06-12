@echo off
chcp 65001 >nul 2>nul
cd /d "%~dp0"
echo.
echo ============================
echo   Health Data Manager
echo   Starting...
echo ============================
echo.
python app.py
pause
