@echo off
REM ============================================================
REM  Construye el ejecutable de NEXUS para Windows (PyInstaller).
REM  Resultado:  dist\NEXUS\NEXUS.exe
REM ============================================================
cd /d "%~dp0"

echo Instalando dependencias...
pip install -r requirements.txt || goto :err
pip install pyinstaller || goto :err

echo Compilando NEXUS.exe ...
pyinstaller --noconfirm nexus.spec || goto :err

echo.
echo ============================================================
echo  Listo. Ejecutable en:  dist\NEXUS\NEXUS.exe
echo  Copia esa carpeta donde quieras y haz doble clic en NEXUS.exe
echo  (define tus variables NEXUS_* antes, o usa nexus_servicio.bat)
echo ============================================================
goto :eof

:err
echo.
echo [ERROR] Fallo la compilacion. Revisa el mensaje de arriba.
exit /b 1
