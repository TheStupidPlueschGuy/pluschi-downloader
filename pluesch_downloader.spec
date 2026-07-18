# -*- mode: python ; coding: utf-8 -*-
# PyInstaller Spec für Plüsch Downloader
# Bauen: pyinstaller pluesch_downloader.spec

import sys
from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[
        # FFmpeg muss im selben Ordner wie app.py liegen!
        ('ffmpeg.exe', '.'),
        ('ffprobe.exe', '.'),
    ],
    datas=[
        # HTML Templates
        ('templates', 'templates'),
        # Static Files (falls vorhanden)
        # ('static', 'static'),
    ],
    hiddenimports=[
        'yt_dlp',
        'yt_dlp.extractor',
        'yt_dlp.postprocessor',
        'webview',
        'webview.platforms.winforms',
        'clr',
        'flask',
        'jinja2',
        'werkzeug',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'PIL',
        'PyQt5',
        'PyQt6',
        'wx',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PlüschDownloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # Kein schwarzes CMD-Fenster
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',        # App-Icon (icon.ico im selben Ordner)
    version='version_info.txt',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PlüschDownloader',
)
