@echo off
chcp 65001 >nul
title NEXUS (web)
cd /d "%~dp0"
"%LOCALAPPDATA%\Programs\Python\Python312\python.exe" nexus_web.py
echo.
echo (Nexus web se detuvo. Pulsa una tecla para salir.)
pause >nul
