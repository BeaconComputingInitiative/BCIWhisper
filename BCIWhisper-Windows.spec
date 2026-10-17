# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_submodules,
    collect_data_files,
    collect_dynamic_libs,
    copy_metadata,
)

ROOT = Path(SPECPATH)
datas = []
binaries = []
hiddenimports = []

for name in ("assets", "services"):
    source = ROOT / name
    if source.exists():
        datas.append((str(source), name))

for package in ("bci", "bci_audio", "bci_core", "bciwhisper"):
    try:
        hiddenimports += collect_submodules(package)
    except Exception:
        pass

for package in ("faster_whisper", "ctranslate2"):
    try:
        hiddenimports += collect_submodules(package)
    except Exception:
        pass

for package in ("faster_whisper", "sounddevice"):
    try:
        datas += collect_data_files(package)
    except Exception:
        pass

for package in ("sounddevice", "ctranslate2"):
    try:
        binaries += collect_dynamic_libs(package)
    except Exception:
        pass

for package in ("faster-whisper", "ctranslate2", "tokenizers", "huggingface-hub"):
    try:
        datas += copy_metadata(package)
    except Exception:
        pass

try:
    import ctranslate2
    ct2_package_dir = Path(ctranslate2.__file__).resolve().parent
    ct2_site_dir = ct2_package_dir.parent
    for sibling_name in ("ctranslate2.libs", "ctranslate2"):
        sibling = ct2_site_dir / sibling_name
        if not sibling.exists():
            continue
        for file in sibling.rglob("*"):
            if not file.is_file():
                continue
            if file.suffix.lower() not in (".dll", ".pyd"):
                continue
            try:
                relative_parent = file.parent.relative_to(ct2_site_dir)
                destination = str(relative_parent)
            except Exception:
                destination = "."
            binaries.append((str(file), destination))
except Exception as exc:
    print("[BCI][PACKAGING] CTranslate2 native-library discovery warning: " + str(exc))

a = Analysis(
    ["BCIWhisper.py"],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "whisper", "torch", "torchvision", "torchaudio",
        "triton", "nvidia", "onnx", "onnxruntime",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BCIWhisper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=str(ROOT / "assets" / "bciwhisper.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="BCIWhisper",
)
