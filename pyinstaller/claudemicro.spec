# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller definition for the ClaudeMicro desktop tray application."""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


PROJECT_ROOT = Path(SPECPATH).parent

# app.tray intentionally imports GUI packages lazily so `--smoke` and the
# headless server work without them. Collect their dynamically selected GUI
# backends and package data explicitly for the frozen application.
gui_datas = []
gui_binaries = []
gui_hiddenimports = []
for package in ("pystray", "webview", "PIL"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    gui_datas += package_datas
    gui_binaries += package_binaries
    gui_hiddenimports += package_hiddenimports

a = Analysis(
    [str(PROJECT_ROOT / "app" / "__main__.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=gui_binaries,
    datas=[(str(PROJECT_ROOT / "console" / "index.html"), "console")] + gui_datas,
    hiddenimports=gui_hiddenimports,
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
    [],
    exclude_binaries=True,
    name="ClaudeMicro",
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ClaudeMicro",
)
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="ClaudeMicro.app",
        icon=None,
        bundle_identifier="com.aieoproduct.claudemicro",
        info_plist={
            # A menu-bar utility: do not leave a second, redundant Dock icon.
            "LSUIElement": True,
            "NSHighResolutionCapable": True,
            "NSInputMonitoringUsageDescription": (
                "Codex Micro の物理キー入力の読み取りに使用します"
            ),
        },
    )
