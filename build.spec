# -*- mode: python ; coding: utf-8 -*-
"""Ders Kilidi (FocusMe) — PyInstaller Çoklu Hedef (ders_kilidi, watchdog, recover) Yapılandırması."""

block_cipher = None

a_main = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['win32timezone', 'keyboard', 'psutil', 'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.Qt3DCore', 'PySide6.QtQuick'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz_main = PYZ(a_main.pure, a_main.zipped_data, cipher=block_cipher)
exe_main = EXE(
    pyz_main,
    a_main.scripts,
    [],
    exclude_binaries=True,
    name='ders_kilidi',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
)

a_wd = Analysis(
    ['watchdog.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['psutil'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz_wd = PYZ(a_wd.pure, a_wd.zipped_data, cipher=block_cipher)
exe_wd = EXE(
    pyz_wd,
    a_wd.scripts,
    [],
    exclude_binaries=True,
    name='ders_kilidi_watchdog',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    uac_admin=True,
)

a_rec = Analysis(
    ['recover.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz_rec = PYZ(a_rec.pure, a_rec.zipped_data, cipher=block_cipher)
exe_rec = EXE(
    pyz_rec,
    a_rec.scripts,
    [],
    exclude_binaries=True,
    name='recover',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    uac_admin=True,
)

coll = COLLECT(
    exe_main,
    a_main.binaries,
    a_main.zipfiles,
    a_main.datas,
    exe_wd,
    a_wd.binaries,
    a_wd.zipfiles,
    a_wd.datas,
    exe_rec,
    a_rec.binaries,
    a_rec.zipfiles,
    a_rec.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ders_kilidi',
)
