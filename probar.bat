@echo off
chcp 65001 >nul
title NEXUS - Probar
cd /d "%~dp0"

REM ============================================================
REM  NEXUS - Lanzador de PRUEBA (doble clic)
REM  Instala las dependencias, te pide (opcional) tu API key y
REM  abre Nexus en el navegador en modo simulacion (sin riesgo).
REM ============================================================

REM --- Elegir un Python que tenga (o pueda tener) las librerias ---
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" (
  where py >nul 2>nul && (set "PY=py") || (set "PY=python")
)

echo ============================================
echo    NEXUS - arranque de prueba
echo ============================================
echo.
echo Usando Python: %PY%
echo.
echo [1/2] Instalando dependencias (solo la primera vez, puede tardar)...
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo  ERROR instalando dependencias. Comprueba que Python este instalado
  echo  ^(https://www.python.org/downloads/^) y vuelve a ejecutar este archivo.
  pause
  exit /b 1
)
echo.

set /p "APIKEY=Pega tu ANTHROPIC_API_KEY (o pulsa Enter para modo DEMO sin chat IA): "
if "%APIKEY%"=="" (
  set "NEXUS_BACKEND=ollama"
  echo.
  echo  Modo DEMO: veras la interfaz completa y el trading SIMULADO.
  echo  El chat con IA necesita una API key de Anthropic o tener Ollama instalado.
) else (
  set "ANTHROPIC_API_KEY=%APIKEY%"
)

REM Trading en modo simulacion (precios ficticios, NADA llega a un broker).
set "NEXUS_NT_SIMULAR=1"

echo.
echo [2/2] Abriendo Nexus en http://127.0.0.1:5000 ...
echo  (Para detenerlo: cierra esta ventana o pulsa Ctrl+C)
echo.
"%PY%" nexus_web.py

echo.
echo (Nexus se detuvo. Pulsa una tecla para salir.)
pause >nul
