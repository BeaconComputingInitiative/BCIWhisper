# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 59.3 | Engineering Build 2026.10.23-r6.36.3
# Developer Seal: CJB-DEV-2026

# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

datas = [
    ("bciwhisper/ui_qml/qml", "bciwhisper/ui_qml/qml"),
    ("assets/bciwhisper.png", "assets"),
    ("services/broadcast-gateway", "services/broadcast-gateway"),
]

binaries = []
hiddenimports = [
    "bci_audio.boundary",
    "bci_core.state",
    "bciwhisper.native._bci_native",
    "websockets.sync.client",
]

for package in (
    "faster_whisper",
    "ctranslate2",
    "av",
    "tokenizers",
    "huggingface_hub",
    "websockets",
):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

binaries += collect_dynamic_libs("bciwhisper.native")

a = Analysis(
    ["bciwhisper/ui_qml/main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PyQt5",
        "PyQt6",
        "torch",
        "tensorflow",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BCIWhisper-59.3",
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
    name="BCIWhisper-59.3",
)
