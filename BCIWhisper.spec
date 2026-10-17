# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_submodules,
    collect_data_files,
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

# Explicitly collect BCI packages because portions of the application
# operate across runtime/service/process boundaries that static import
# analysis may not always discover.

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

# Script 57.8 retains its runtime backend selection logic:
#
#   openai-whisper -> faster-whisper -> whisper.cpp
#
# The standalone package intentionally bundles Faster-Whisper /
# CTranslate2 as its native CPU transcription implementation.
#
# OpenAI Whisper/Torch and whisper.cpp remain optional external
# backends and are NOT bundled in this build.

for package in (
    "faster_whisper",
    "ctranslate2",
):
    try:
        hiddenimports += collect_submodules(package)
    except Exception:
        pass


# Faster-Whisper package data.
try:
    datas += collect_data_files("faster_whisper")
except Exception:
    pass


# Preserve package metadata used by importlib.metadata and dependency
# version checks.
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

# CTranslate2 wheels ship their Python extension inside ctranslate2/
# and may place additional shared libraries in the adjacent
# ctranslate2.libs/ directory.
#
# PyInstaller normally follows shared-library dependencies, but we
# include the wheel-side runtime explicitly so the frozen executable
# does not depend on the build virtual environment.

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

    # Prevent the lean Faster-Whisper package from accidentally pulling
    # the former multi-gigabyte OpenAI Whisper / Torch / CUDA stack back
    # into this standalone build.
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


# =====================================================================
# PYTHON ARCHIVE
# =====================================================================

pyz = PYZ(a.pure)


# =====================================================================
# EXECUTABLE
# =====================================================================

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

    # Keep console enabled throughout 57.8 engineering validation.
    # PortAudio, multiprocessing, transcription, and telemetry faults
    # must remain directly observable.
    console=True,
)


# =====================================================================
# ONEDIR COLLECTION
# =====================================================================

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="BCIWhisper",
)
