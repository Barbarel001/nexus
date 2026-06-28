# -*- mode: python ; coding: utf-8 -*-
# Spec de PyInstaller para empaquetar NEXUS como ejecutable de Windows.
#   pip install pyinstaller
#   pyinstaller nexus.spec
# Genera dist/NEXUS/NEXUS.exe (modo carpeta: rápido de arrancar y fácil de firmar).

block_cipher = None

a = Analysis(
    ['nexus_web.py'],
    pathex=[],
    binaries=[],
    # Empaqueta los assets web y los iconos junto al ejecutable.
    datas=[('web', 'web')],
    # Módulos que PyInstaller podría no detectar por los imports perezosos/dinámicos.
    hiddenimports=[
        'nexus', 'nexus_ninjatrader', 'nexus_tareas', 'nexus_alertas', 'nexus_docs',
        'nexus_noticias', 'nexus_gastos', 'nexus_clima', 'nexus_google', 'nexus_util',
        'nexus_telegram', 'nexus_scheduler', 'nexus_discord', 'nexus_ollama',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='NEXUS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,                 # muestra una consola con el log (útil al inicio)
    icon='web/icon-512.png',
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=True, upx_exclude=[], name='NEXUS',
)
