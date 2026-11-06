# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_dynamic_libs

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=collect_dynamic_libs("sqlcipher3"),
    datas=[("amdh_hr/assets", "amdh_hr/assets")],
    hiddenimports=["sqlcipher3", "sqlcipher3.dbapi2"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tests", "tools"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AMDH-HR",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="amdh_hr/assets/icon.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AMDH-HR",
)
