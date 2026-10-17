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


# =====================================================================
# BCI IMMUTABLE APPLICATION DATA
# =====================================================================

for name in (
    "assets",
    "services",
):
    source = ROOT / name
    if source.exists():
        datas.append((str(source), name))


# =====================================================================
# BCI-OWNED PACKAGES
# =====================================================================

for package in (
    "bci",
    "bci_audio",
    "bci_core",
    "bciwhisper",
):
    try:
        hiddenimports += collect_submodules(package)
    except Exception:
        pass


# =====================================================================
# TRANSCRIPTION BACKEND
# =====================================================================

for package in (
    "faster_whisper",
    "ctranslate2",
):
    try:
        hiddenimports += collect_submodules(package)
    except Exception:
        pass

for package in (
    "faster_whisper",
    "sounddevice",
):
    try:
        datas += collect_data_files(package)
    except Exception:
        pass

for package in (
    "sounddevice",
    "ctranslate2",
):
    try:
        binaries += collect_dynamic_libs(package)
    except Exception:
        pass

for package in (
    "faster-whisper",
    "ctranslate2",
    "tokenizers",
    "huggingface-hub",
):
    try:
        datas += copy_metadata(package)
    except Exception:
        pass


# =====================================================================
# CTRANSLATE2 NATIVE RUNTIME
# =====================================================================

try:
    import ctranslate2

    ct2_package_dir = Path(ctranslate2.__file__).resolve().parent
    ct2_site_dir = ct2_package_dir.parent
    ct2_libs_dir = ct2_site_dir / "ctranslate2.libs"

    if ct2_libs_dir.exists():
        for file in ct2_libs_dir.rglob("*"):
            if file.is_file():
                relative_parent = file.parent.relative_to(ct2_libs_dir)
                destination = Path("ctranslate2.libs")

                if str(relative_parent) != ".":
                    destination /= relative_parent

                binaries.append(
                    (
                        str(file),
                        str(destination),
                    )
                )

except Exception as exc:
    print(
        "[BCI][PACKAGING] "
        f"CTranslate2 native-library discovery warning: {exc}"
    )


# =====================================================================
# ANALYSIS
# =====================================================================

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
        "whisper",
        "torch",
        "torchvision",
        "torchaudio",
        "triton",
        "nvidia",
        "onnx",
        "onnxruntime",
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
)


coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="BCIWhisper",
)


# =====================================================================
# macOS APPLICATION BUNDLE
# =====================================================================

app = BUNDLE(
    coll,
    name="BCIWhisper.app",
    icon=str(ROOT / "assets" / "bciwhisper.icns"),
    bundle_identifier="org.beaconcomputinginitiative.bciwhisper",
    info_plist={
        "CFBundleName": "BCIWhisper",
        "CFBundleDisplayName": "BCIWhisper",
        "CFBundleShortVersionString": "6.0",
        "CFBundleVersion": "57.10",
        "NSMicrophoneUsageDescription": (
            "BCIWhisper requires microphone access for audio monitoring, "
            "analysis, and recording."
        ),
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.utilities",
    },
)
