@echo off
REM ============================================================
REM  NEXUS - lanzador "siempre encendido" (Windows)
REM ------------------------------------------------------------
REM  Edita las variables de abajo a tu gusto y ejecuta este .bat.
REM  Para que arranque solo con Windows: pulsa Win+R, escribe
REM    shell:startup
REM  y copia un ACCESO DIRECTO a este archivo en esa carpeta.
REM
REM  Si Nexus se cierra por un error, este script lo reinicia solo.
REM ============================================================

cd /d "%~dp0"

REM --- Configuracion (ajusta a tu caso; deja en blanco lo que no uses) ---
set NEXUS_BACKEND=ollama
set NEXUS_NT_SIMULAR=1
REM set NEXUS_PASSWORD=tu_clave
REM set NEXUS_SECRET=texto_largo_al_azar
REM set NEXUS_HOST=0.0.0.0
REM set NEXUS_TELEGRAM_TOKEN=123456:ABC...
REM set NEXUS_TELEGRAM_CHAT_ID=tu_chat_id
REM set NEXUS_BRIEFING_HORA=08:00
set NEXUS_OPEN=0

:loop
echo [%date% %time%] Iniciando NEXUS...
python nexus_web.py
echo [%date% %time%] NEXUS se detuvo. Reiniciando en 5s... (Ctrl+C para salir)
timeout /t 5 /nobreak >nul
goto loop
