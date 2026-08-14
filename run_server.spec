# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

dist_dir = Path('../areatekqcweb/dist')
dist_datas = [(str(dist_dir), 'dist')] if dist_dir.is_dir() else []

a = Analysis(
    ['run_server.py'],
    pathex=[],
    binaries=[],
    datas=dist_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='run_server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
