@echo off
chcp 65001 >nul
title N.E.X.U.S.
cd /d "%~dp0"
"%LOCALAPPDATA%\Programs\Python\Python312\python.exe" nexus.py
echo.
echo (Nexus se ha cerrado. Pulsa una tecla para salir.)
pause >nul
