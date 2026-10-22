# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.1 | Engineering Build 2026.10.22-r6.35.1
# Developer Seal: CJB-DEV-2026
# Canonical Payload SHA-256: a35cd5707e909392d0a9b1e236aafebcce5f58ef19850615601243e9f0df21c1
# Integrity rule: hash covers this file's payload below this header, if and only if the payload is unchanged.

# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all


datas = [
    ("bciwhisper/ui_qml/qml", "bciwhisper/ui_qml/qml"),
    ("assets/bciwhisper.png", "assets"),
]
binaries = []
hiddenimports = []

for package in (
    "faster_whisper",
    "ctranslate2",
    "av",
    "tokenizers",
    "huggingface_hub",
):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis(
    ["bciwhisper/ui_qml/main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "torch", "tensorflow"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BCIWhisper-58.1-QML",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="BCIWhisper-58.1-QML",
)
