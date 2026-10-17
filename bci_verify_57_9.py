#!/usr/bin/env python3

"""
BCIWhisper v6.0 / Script 57.8
Autonomous Verification, Diagnosis, Remediation and Acceptance Controller

Beacon Computing Initiative
Developer Seal: CJB-DEV-2026

Operating cycle:

    OBSERVE
      ↓
    TEST
      ↓
    ANALYZE
      ↓
    DIAGNOSE
      ↓
    BACKUP
      ↓
    APPLY DETERMINISTIC FIX
      ↓
    COMPILE / REBUILD
      ↓
    RETEST
      ↓
    KEEP or ROLLBACK
      ↓
    CONTINUE

No interactive confirmation is required.

The controller is permitted to autonomously repair only deterministic,
known BCIWhisper 57.8 defects. Novel architectural/native failures are
diagnosed and marked BLOCKED rather than guessed at.

BCI principles:
    Observe accurately.
    Preserve faithfully.
    Analyze transparently.
    Communicate securely.
    Act deliberately.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import traceback
import wave

from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


# =============================================================================
# RELEASE IDENTITY
# =============================================================================

EXPECTED_PROJECT_VERSION = "v6.0"
EXPECTED_SCRIPT_REVISION = "57.9"
EXPECTED_SCRIPT_TALLY = 57
EXPECTED_BUILD = "2026.10.17-r6.34.9"

MIN_RETAINED_SECONDS = 15.0

PROJECT_ROOT = Path(__file__).resolve().parent
MAIN_SCRIPT = PROJECT_ROOT / "BCIWhisper.py"
SPEC_FILE = PROJECT_ROOT / "BCIWhisper.spec"

VENV_PYTHON = (
    PROJECT_ROOT
    / ".venv-bciwhisper"
    / "bin"
    / "python"
)

DIST_ROOT = (
    PROJECT_ROOT
    / "dist"
    / "BCIWhisper"
)

FROZEN_EXECUTABLE = (
    DIST_ROOT
    / "BCIWhisper"
)

RUNTIME_ROOT = Path(
    os.environ.get(
        "BCI_DATA_DIR",
        os.environ.get(
            "XDG_DATA_HOME",
            str(
                Path.home()
                / ".local"
                / "share"
            ),
        )
        + "/BCIWhisper"
        if not os.environ.get("BCI_DATA_DIR")
        else os.environ["BCI_DATA_DIR"],
    )
).expanduser()

MODEL_PATH = Path(
    os.environ.get(
        "BCI_FASTER_WHISPER_MODEL",
        str(
            RUNTIME_ROOT
            / "models"
            / "faster-whisper-small.en"
        ),
    )
).expanduser()

REPORT_TXT = (
    PROJECT_ROOT
    / "bci_verification_57_9.txt"
)

REPORT_JSON = (
    PROJECT_ROOT
    / "bci_verification_57_9.json"
)

ACTION_LOG = (
    PROJECT_ROOT
    / "bci_verification_57_9_actions.log"
)

BACKUP_ROOT = (
    PROJECT_ROOT
    / "versions"
    / "57.9-runtime-hardening"
)


# =============================================================================
# STATE
# =============================================================================

@dataclass
class CheckResult:
    subsystem: str
    status: str
    detail: str
    evidence: Optional[str] = None
    remediation: Optional[str] = None


@dataclass
class ActionResult:
    action: str
    status: str
    detail: str
    before_sha: Optional[str] = None
    after_sha: Optional[str] = None
    backup: Optional[str] = None


RESULTS: list[CheckResult] = []
ACTIONS: list[ActionResult] = []

INITIAL_CORE_IDS: set[str] = set()


# =============================================================================
# OUTPUT
# =============================================================================

def log(message=""):
    print(message)

    with ACTION_LOG.open(
        "a",
        encoding="utf-8",
    ) as handle:
        handle.write(
            str(message) + "\n"
        )


def record(
    subsystem,
    status,
    detail,
    evidence=None,
    remediation=None,
):
    result = CheckResult(
        subsystem=subsystem,
        status=status,
        detail=detail,
        evidence=evidence,
        remediation=remediation,
    )

    RESULTS.append(result)

    marker = f"[{status}]"

    print(
        f"{marker:<14} "
        f"{subsystem}: {detail}"
    )


def action(
    action_name,
    status,
    detail,
    before_sha=None,
    after_sha=None,
    backup=None,
):
    entry = ActionResult(
        action=action_name,
        status=status,
        detail=detail,
        before_sha=before_sha,
        after_sha=after_sha,
        backup=backup,
    )

    ACTIONS.append(entry)

    print(
        f"[{status}] "
        f"ACTION {action_name}: {detail}"
    )


# =============================================================================
# GENERIC HELPERS
# =============================================================================

def sha256(path: Path) -> Optional[str]:
    if not path.exists():
        return None

    digest = hashlib.sha256()

    with path.open(
        "rb",
    ) as handle:
        while True:
            block = handle.read(
                1024 * 1024
            )

            if not block:
                break

            digest.update(block)

    return digest.hexdigest()


def run(
    command,
    *,
    timeout=60,
    cwd=None,
    env=None,
):
    try:
        completed = subprocess.run(
            command,
            cwd=(
                str(cwd)
                if cwd
                else None
            ),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

        return (
            completed.returncode,
            completed.stdout or "",
            completed.stderr or "",
        )

    except subprocess.TimeoutExpired as exc:
        stdout = (
            exc.stdout
            if isinstance(
                exc.stdout,
                str,
            )
            else ""
        )

        stderr = (
            exc.stderr
            if isinstance(
                exc.stderr,
                str,
            )
            else ""
        )

        return (
            124,
            stdout,
            stderr + "\nTIMEOUT",
        )

    except Exception as exc:
        return (
            255,
            "",
            repr(exc),
        )


def source_text():
    return MAIN_SCRIPT.read_text(
        encoding="utf-8",
        errors="replace",
    )


def find_assignment(
    text,
    variable,
):
    match = re.search(
        rf"^{re.escape(variable)}"
        r"\s*=\s*(.+?)\s*$",
        text,
        re.MULTILINE,
    )

    if not match:
        return None

    raw = match.group(1)

    try:
        return ast.literal_eval(raw)
    except Exception:
        return raw


def timestamp():
    return datetime.now().strftime(
        "%Y%m%d-%H%M%S"
    )


def backup_files(
    label,
    files,
):
    destination = (
        BACKUP_ROOT
        / f"{timestamp()}-{label}"
    )

    destination.mkdir(
        parents=True,
        exist_ok=True,
    )

    copied = []

    for file_path in files:
        file_path = Path(file_path)

        if not file_path.exists():
            continue

        target = (
            destination
            / file_path.name
        )

        shutil.copy2(
            file_path,
            target,
        )

        copied.append(
            str(target)
        )

    metadata = {
        "created_at": (
            datetime.now()
            .astimezone()
            .isoformat()
        ),
        "files": copied,
        "source_sha": sha256(
            MAIN_SCRIPT
        ),
        "spec_sha": sha256(
            SPEC_FILE
        ),
    }

    (
        destination
        / "BACKUP.json"
    ).write_text(
        json.dumps(
            metadata,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return destination


def restore_file(
    backup_dir,
    filename,
):
    source = (
        Path(backup_dir)
        / filename
    )

    destination = (
        PROJECT_ROOT
        / filename
    )

    if source.exists():
        shutil.copy2(
            source,
            destination,
        )

        return True

    return False


def compile_main():
    code, out, err = run(
        [
            str(VENV_PYTHON),
            "-m",
            "py_compile",
            str(MAIN_SCRIPT),
        ],
        timeout=60,
        cwd=PROJECT_ROOT,
    )

    return (
        code == 0,
        out + err,
    )


def compile_all_modules():
    roots = []

    for name in (
        "bci",
        "bciwhisper",
        "bci_audio",
        "bci_core",
        "bci_dsp",
    ):
        candidate = (
            PROJECT_ROOT
            / name
        )

        if candidate.exists():
            roots.append(
                candidate
            )

    files = []

    for root in roots:
        files.extend(
            root.rglob("*.py")
        )

    failures = []

    for path in files:
        try:
            compile(
                path.read_text(
                    encoding="utf-8",
                    errors="replace",
                ),
                str(path),
                "exec",
            )

        except Exception as exc:
            failures.append(
                f"{path}: {exc}"
            )

    return (
        len(failures) == 0,
        files,
        failures,
    )


# =============================================================================
# SOURCE ACCEPTANCE
# =============================================================================

def test_identity():
    text = source_text()

    actual = {
        "BCI_PROJECT_VERSION":
            find_assignment(
                text,
                "BCI_PROJECT_VERSION",
            ),

        "BCI_SCRIPT_REVISION":
            find_assignment(
                text,
                "BCI_SCRIPT_REVISION",
            ),

        "BCI_SCRIPT_TALLY":
            find_assignment(
                text,
                "BCI_SCRIPT_TALLY",
            ),

        "BCI_BUILD":
            find_assignment(
                text,
                "BCI_BUILD",
            ),
    }

    expected = {
        "BCI_PROJECT_VERSION":
            EXPECTED_PROJECT_VERSION,

        "BCI_SCRIPT_REVISION":
            EXPECTED_SCRIPT_REVISION,

        "BCI_SCRIPT_TALLY":
            EXPECTED_SCRIPT_TALLY,

        "BCI_BUILD":
            EXPECTED_BUILD,
    }

    wrong = []

    for key in expected:
        if (
            actual[key]
            != expected[key]
        ):
            wrong.append(
                f"{key}="
                f"{actual[key]!r}; "
                f"expected "
                f"{expected[key]!r}"
            )

    if wrong:
        record(
            "Project identity",
            "FAIL",
            "; ".join(wrong),
        )

        return False

    record(
        "Project identity",
        "PASS",
        (
            f"{EXPECTED_PROJECT_VERSION}, "
            f"Script "
            f"{EXPECTED_SCRIPT_REVISION}, "
            f"tally "
            f"{EXPECTED_SCRIPT_TALLY}, "
            f"build {EXPECTED_BUILD}"
        ),
    )

    record(
        "Source SHA256",
        "INFO",
        sha256(
            MAIN_SCRIPT
        )
        or "unknown",
    )

    return True


def test_compile():
    passed, detail = compile_main()

    if passed:
        record(
            "BCIWhisper.py compile",
            "PASS",
            "Python source compiles.",
        )
    else:
        record(
            "BCIWhisper.py compile",
            "FAIL",
            detail.strip(),
        )

    return passed


def test_modules():
    passed, files, failures = (
        compile_all_modules()
    )

    if passed:
        record(
            "Module compilation",
            "PASS",
            (
                f"{len(files)} module "
                "files compile."
            ),
        )
    else:
        record(
            "Module compilation",
            "FAIL",
            (
                f"{len(failures)} "
                "module failures."
            ),
            "\n".join(
                failures[:40]
            ),
        )

    return passed


# =============================================================================
# TRANSCRIPTION POLICY
# =============================================================================

AUTO_TOKENS = (
    "auto_transcribe_check",
    "auto_transcribe_enabled",
    "set_auto_transcribe",
    'reason="auto"',
    'reason="auto-fallback"',
    '"auto-mastered"',
    '"auto-quality-preserved"',
    "AUTO TRANSCRIBE",
)


def test_manual_only_policy():
    text = source_text()

    found = [
        token
        for token in AUTO_TOKENS
        if token in text
    ]

    submit_count = (
        text.count(
            "transcription_thread.submit"
        )
    )

    manual = (
        'reason="manual"'
        in text
    )

    tab_manual = (
        'reason="transcripts-tab"'
        in text
    )

    if found:
        record(
            "Manual-only transcription",
            "FAIL",
            (
                "Automatic transcription "
                "machinery detected."
            ),
            ", ".join(found),
            "Known deterministic removal available.",
        )

        return False

    if not (
        manual
        and tab_manual
    ):
        record(
            "Manual-only transcription",
            "FAIL",
            (
                "Expected explicit manual "
                "submission paths are missing."
            ),
            (
                f"manual={manual}, "
                f"transcripts-tab="
                f"{tab_manual}"
            ),
        )

        return False

    record(
        "Manual-only transcription",
        "PASS",
        (
            f"{submit_count} "
            "transcription submit "
            "call(s); manual policy clean."
        ),
    )

    return True


def repair_auto_transcription():
    before = sha256(
        MAIN_SCRIPT
    )

    backup = backup_files(
        "auto-transcription",
        [MAIN_SCRIPT],
    )

    text = source_text()

    patterns = [
        (
            r'^\s*self\.auto_transcribe_check\s*=\s*'
            r'QtWidgets\.QCheckBox\("Auto Transcribe"\)\s*\n',
            "",
        ),

        (
            r'^\s*self\.auto_transcribe_check\.setChecked\(\s*\n'
            r'\s*self\.settings\.value\("auto_transcribe",'
            r'\s*False,\s*type=bool\)\s*\n'
            r'\s*\)\s*\n',
            "",
        ),

        (
            r'^\s*automation_layout\.addWidget'
            r'\(self\.auto_transcribe_check\)\s*\n',
            "",
        ),

        (
            r'^\s*self\.auto_transcribe_check\.toggled\.connect\(\s*\n'
            r'\s*self\.set_auto_transcribe\s*\n'
            r'\s*\)\s*\n',
            "",
        ),

        (
            r'''    def set_auto_transcribe\(self, enabled\):
.*?
(?=    def )''',
            "",
        ),

        (
            r'''    def auto_transcribe_enabled\(self\):
.*?
(?=    def )''',
            "",
        ),

        (
            r'''(?ms)^                if self\.auto_transcribe_enabled\(\).*?
(?=        self\._master_refresh_controls\(\))''',
            "",
        ),

        (
            r'''(?ms)^        preferred = \(
            isolated_path
.*?
            \)

(?=    @guarded_slot\("post-processing status"\))''',
            "",
        ),

        (
            r'''(?ms)^            fallback = \(
                isolated_path
.*?
                \)

(?=            self\.refresh_recordings\(\))''',
            "",
        ),

        (
            r'''(?ms)^        if \(
            self\.auto_transcribe_enabled\(\)
.*?
            \)

(?=    def transcribe_selected_recording)''',
            "",
        ),
    ]

    for pattern, replacement in patterns:
        text = re.sub(
            pattern,
            replacement,
            text,
            count=1,
            flags=re.MULTILINE,
        )

    # Replace any surviving status expression.
    text = re.sub(
        r'''
                \+ "   •   AUTO TRANSCRIBE: "
                \+ \(
                    "ON"
                    if self\.auto_transcribe_check\.isChecked\(\)
                    else "OFF"
                \)
''',
        '''
                + "   •   TRANSCRIPTION: MANUAL"
''',
        text,
        flags=re.VERBOSE,
    )

    MAIN_SCRIPT.write_text(
        text,
        encoding="utf-8",
    )

    compiled, detail = (
        compile_main()
    )

    policy_clean = not any(
        token in source_text()
        for token in AUTO_TOKENS
    )

    if (
        compiled
        and policy_clean
    ):
        after = sha256(
            MAIN_SCRIPT
        )

        action(
            "Remove automatic transcription",
            "FIXED",
            (
                "Known auto-transcription "
                "paths removed and source "
                "recompiled."
            ),
            before,
            after,
            str(backup),
        )

        return True

    restore_file(
        backup,
        MAIN_SCRIPT.name,
    )

    action(
        "Remove automatic transcription",
        "ROLLED BACK",
        (
            "Remediation failed validation; "
            "original source restored. "
            + detail.strip()
        ),
        before,
        sha256(MAIN_SCRIPT),
        str(backup),
    )

    return False


# =============================================================================
# TRANSCRIPTS TAB
# =============================================================================

def test_transcript_tab():
    text = source_text()

    required = (
        "self.transcripts_tab",
        '"TRANSCRIPTS"',
        "self._build_transcripts_tab()",
        "def _build_transcripts_tab(",
        "def refresh_transcripts(",
        "def transcribe_selected_transcript_audio(",
        "handle_transcripts_tab_result",
        "handle_transcripts_tab_status",
        'reason="transcripts-tab"',
    )

    missing = [
        item
        for item in required
        if item not in text
    ]

    if missing:
        record(
            "Transcripts tab wiring",
            "FAIL",
            (
                f"{len(missing)} required "
                "component(s) missing."
            ),
            "\n".join(missing),
        )

        return False

    record(
        "Transcripts tab wiring",
        "PASS",
        "Dedicated manual transcription workspace is wired.",
    )

    return True


def test_gui_tabs():
    text = source_text()

    expected = (
        '"MONITOR"',
        '"RECORDINGS"',
        '"TRANSCRIPTS"',
        '"MASTERING"',
    )

    missing = [
        item
        for item in expected
        if item not in text
    ]

    if missing:
        record(
            "GUI tabs",
            "FAIL",
            (
                "Missing tabs: "
                + ", ".join(
                    missing
                )
            ),
        )

        return False

    record(
        "GUI tabs",
        "PASS",
        (
            "MONITOR / RECORDINGS / "
            "TRANSCRIPTS / MASTERING present."
        ),
    )

    return True


# =============================================================================
# ARCHITECTURE
# =============================================================================

def test_architecture():
    text = source_text()

    required = {
        "audio processor":
            "AudioProcessorThread",

        "audio boundary":
            "BCIAudioBoundaryThread",

        "transcription":
            "TranscriptionThread",

        "mastering":
            "MasterRenderThread",

        "adaptive GUI":
            "BCIAdaptiveFrame",
    }

    missing = [
        name
        for name, symbol
        in required.items()
        if symbol not in text
    ]

    if missing:
        record(
            "Architecture markers",
            "FAIL",
            (
                "Missing: "
                + ", ".join(
                    missing
                )
            ),
        )

        return False

    record(
        "Architecture markers",
        "PASS",
        "Expected 57.x subsystem markers present.",
    )

    return True


# =============================================================================
# BACKEND / MODEL
# =============================================================================

def module_exists(name):
    try:
        return (
            importlib.util.find_spec(
                name
            )
            is not None
        )

    except Exception:
        return False


def test_backends():
    faster = module_exists(
        "faster_whisper"
    )

    ctranslate = module_exists(
        "ctranslate2"
    )

    whisper = module_exists(
        "whisper"
    )

    cpp = bool(
        shutil.which("whisper-cli")
        or shutil.which("main")
    )

    available = []

    if whisper:
        available.append(
            "openai-whisper"
        )

    if faster:
        available.append(
            "faster-whisper"
        )

    if ctranslate:
        available.append(
            "ctranslate2"
        )

    if cpp:
        available.append(
            "whisper.cpp"
        )

    if faster and ctranslate:
        record(
            "Transcription backend",
            "PASS",
            (
                "Faster-Whisper + "
                "CTranslate2 available. "
                "Additional: "
                + ", ".join(
                    available
                )
            ),
        )

        return True

    record(
        "Transcription backend",
        "FAIL",
        (
            "Required Faster-Whisper "
            "CPU backend incomplete."
        ),
        ", ".join(
            available
        )
        or "none",
        "Install missing venv backend packages.",
    )

    return False


def repair_backend():
    before = sha256(
        MAIN_SCRIPT
    )

    code, out, err = run(
        [
            str(VENV_PYTHON),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "faster-whisper==1.2.1",
            "ctranslate2==4.8.2",
            "av<19",
        ],
        timeout=900,
        cwd=PROJECT_ROOT,
    )

    if (
        code == 0
        and module_exists(
            "faster_whisper"
        )
        and module_exists(
            "ctranslate2"
        )
    ):
        action(
            "Repair Faster-Whisper backend",
            "FIXED",
            (
                "Installed/normalized "
                "Faster-Whisper, CTranslate2 "
                "and PyAV compatibility."
            ),
            before,
            sha256(MAIN_SCRIPT),
        )

        return True

    action(
        "Repair Faster-Whisper backend",
        "FAILED",
        (
            "Package installation failed.\n"
            + out[-1500:]
            + "\n"
            + err[-1500:]
        ),
    )

    return False


def test_model():
    if not MODEL_PATH.exists():
        record(
            "Faster-Whisper model",
            "FAIL",
            f"Missing: {MODEL_PATH}",
            remediation=(
                "Download Systran/"
                "faster-whisper-small.en."
            ),
        )

        return False

    files = [
        p
        for p in MODEL_PATH.rglob("*")
        if p.is_file()
    ]

    if not files:
        record(
            "Faster-Whisper model",
            "FAIL",
            (
                f"Model directory empty: "
                f"{MODEL_PATH}"
            ),
        )

        return False

    total = sum(
        p.stat().st_size
        for p in files
    )

    record(
        "Faster-Whisper model",
        "PASS",
        (
            f"{MODEL_PATH} "
            f"({len(files)} files, "
            f"{total / 1024**2:.1f} MiB)"
        ),
    )

    return True


def repair_model():
    try:
        from huggingface_hub import (
            snapshot_download,
        )

    except Exception:
        code, out, err = run(
            [
                str(VENV_PYTHON),
                "-m",
                "pip",
                "install",
                "huggingface-hub",
            ],
            timeout=600,
            cwd=PROJECT_ROOT,
        )

        if code != 0:
            action(
                "Install model downloader",
                "FAILED",
                err[-1500:],
            )

            return False

        # Current process will not necessarily
        # see newly installed module metadata.
        script = (
            "from huggingface_hub import "
            "snapshot_download; "
            "snapshot_download("
            "'Systran/faster-whisper-small.en',"
            f"local_dir={str(MODEL_PATH)!r})"
        )

        code, out, err = run(
            [
                str(VENV_PYTHON),
                "-c",
                script,
            ],
            timeout=1800,
            cwd=PROJECT_ROOT,
        )

        success = (
            code == 0
            and MODEL_PATH.exists()
        )

    else:
        try:
            MODEL_PATH.mkdir(
                parents=True,
                exist_ok=True,
            )

            snapshot_download(
                repo_id=(
                    "Systran/"
                    "faster-whisper-small.en"
                ),
                local_dir=str(
                    MODEL_PATH
                ),
            )

            success = (
                MODEL_PATH.exists()
                and any(
                    MODEL_PATH.iterdir()
                )
            )

            out = ""
            err = ""

        except Exception as exc:
            success = False
            out = ""
            err = repr(exc)

    if success:
        action(
            "Download Faster-Whisper model",
            "FIXED",
            str(MODEL_PATH),
        )

        return True

    action(
        "Download Faster-Whisper model",
        "FAILED",
        (
            out[-1000:]
            + "\n"
            + err[-1000:]
        ),
    )

    return False


# =============================================================================
# INFERENCE
# =============================================================================

def create_test_wav(path):
    sample_rate = 16000
    duration = 2.0
    frames = int(
        sample_rate
        * duration
    )

    import math

    with wave.open(
        str(path),
        "wb",
    ) as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(
            sample_rate
        )

        payload = bytearray()

        for index in range(
            frames
        ):
            value = int(
                1000
                * math.sin(
                    2
                    * math.pi
                    * 440.0
                    * index
                    / sample_rate
                )
            )

            payload.extend(
                struct.pack(
                    "<h",
                    value,
                )
            )

        handle.writeframes(
            bytes(payload)
        )


def test_inference():
    if not (
        module_exists(
            "faster_whisper"
        )
        and MODEL_PATH.exists()
    ):
        record(
            "Isolated inference",
            "BLOCKED",
            (
                "Backend/model "
                "prerequisite unavailable."
            ),
        )

        return False

    script = r'''
import sys
from pathlib import Path
from faster_whisper import WhisperModel

model_path = Path(sys.argv[1])
wav_path = Path(sys.argv[2])

model = WhisperModel(
    str(model_path),
    device="cpu",
    compute_type="int8",
)

segments, info = model.transcribe(
    str(wav_path),
    language="en",
    vad_filter=False,
    beam_size=5,
)

segments = list(segments)

print(
    "PASS",
    getattr(info, "language", "unknown"),
    len(segments),
)
'''

    with tempfile.TemporaryDirectory(
        prefix="bci-inference-"
    ) as temp:
        wav_path = (
            Path(temp)
            / "test.wav"
        )

        create_test_wav(
            wav_path
        )

        code, out, err = run(
            [
                str(VENV_PYTHON),
                "-c",
                script,
                str(MODEL_PATH),
                str(wav_path),
            ],
            timeout=600,
            cwd=PROJECT_ROOT,
        )

    if (
        code == 0
        and "PASS" in out
    ):
        record(
            "Isolated inference",
            "PASS",
            out.strip(),
        )

        return True

    record(
        "Isolated inference",
        "FAIL",
        (
            f"exit={code}"
        ),
        (
            out[-2000:]
            + "\n"
            + err[-2000:]
        ),
    )

    return False


# =============================================================================
# RECORDINGS
# =============================================================================

def discover_recordings():
    candidates = [
        RUNTIME_ROOT
        / "bci_audio_logs",

        PROJECT_ROOT
        / "bci_audio_logs",
    ]

    for directory in candidates:
        if (
            directory.exists()
            and any(
                directory.glob(
                    "*.wav"
                )
            )
        ):
            return directory

    return None


def wav_metadata(path):
    try:
        with wave.open(
            str(path),
            "rb",
        ) as handle:
            rate = (
                handle.getframerate()
            )

            frames = (
                handle.getnframes()
            )

            channels = (
                handle.getnchannels()
            )

            width = (
                handle.getsampwidth()
            )

        duration = (
            frames / rate
            if rate
            else 0.0
        )

        return {
            "ok": True,
            "duration": duration,
            "rate": rate,
            "channels": channels,
            "width": width,
        }

    except Exception as exc:
        return {
            "ok": False,
            "error": repr(exc),
        }


def logical_key(path):
    stem = path.stem

    if stem.endswith("_raw"):
        return stem[:-4]

    if stem.endswith(
        "_isolated"
    ):
        return stem[:-9]

    return stem


def test_recordings():
    directory = (
        discover_recordings()
    )

    if directory is None:
        record(
            "Recording library",
            "BLOCKED",
            "No retained WAVs found.",
        )

        return False

    wavs = sorted(
        directory.glob("*.wav"),
        key=lambda p: (
            p.stat().st_mtime
        ),
        reverse=True,
    )

    invalid = []
    retained = []
    groups = {}

    for path in wavs:
        meta = wav_metadata(
            path
        )

        if not meta["ok"]:
            invalid.append(
                f"{path.name}: "
                f"{meta['error']}"
            )

            continue

        if (
            meta["duration"]
            >= MIN_RETAINED_SECONDS
        ):
            retained.append(
                (
                    path,
                    meta["duration"],
                )
            )

        key = logical_key(
            path
        )

        group = groups.setdefault(
            key,
            {
                "raw": None,
                "isolated": None,
                "other": [],
            },
        )

        if path.stem.endswith(
            "_raw"
        ):
            group["raw"] = path

        elif path.stem.endswith(
            "_isolated"
        ):
            group["isolated"] = path

        else:
            group["other"].append(
                path
            )

    if invalid:
        record(
            "WAV integrity",
            "FAIL",
            (
                f"{len(invalid)} "
                "invalid WAV(s)."
            ),
            "\n".join(
                invalid
            ),
        )
    else:
        record(
            "WAV integrity",
            "PASS",
            (
                f"{len(wavs)} WAV "
                "file(s) decode."
            ),
        )

    paired = sum(
        bool(
            group["raw"]
            and group["isolated"]
        )
        for group in groups.values()
    )

    incomplete = sum(
        bool(
            (
                group["raw"]
                or group["isolated"]
            )
            and not (
                group["raw"]
                and group["isolated"]
            )
        )
        for group in groups.values()
    )

    record(
        "Logical recordings",
        (
            "PASS"
            if paired > 0
            else "PARTIAL"
        ),
        (
            f"{len(groups)} logical "
            f"recording(s); "
            f"{paired} RAW+isolated "
            f"pair(s); "
            f"{incomplete} incomplete."
        ),
    )

    if retained:
        longest = max(
            retained,
            key=lambda item:
                item[1],
        )

        record(
            ">=15s retention",
            "PASS",
            (
                f"{len(retained)} WAV(s) "
                f">= 15s. Longest: "
                f"{longest[0].name} "
                f"({longest[1]:.2f}s)"
            ),
        )
    else:
        record(
            ">=15s retention",
            "FAIL",
            (
                "No retained WAV proves "
                "the >=15 second branch."
            ),
        )

    transcript_count = sum(
        path.with_suffix(
            ".txt"
        ).exists()
        for path in wavs
    )

    record(
        "Transcript sidecars",
        (
            "PASS"
            if transcript_count
            else "PARTIAL"
        ),
        (
            f"{transcript_count} "
            "direct transcript "
            "sidecar(s) discovered."
        ),
    )

    record(
        "Recording directory",
        "INFO",
        str(directory),
    )

    return not invalid


# =============================================================================
# FFMPEG
# =============================================================================

def test_ffmpeg():
    executable = shutil.which(
        "ffmpeg"
    )

    if not executable:
        record(
            "FFmpeg",
            "FAIL",
            "ffmpeg not found.",
        )

        return False

    code, out, err = run(
        [
            executable,
            "-version",
        ],
        timeout=20,
    )

    first = (
        out.splitlines()[0]
        if out.strip()
        else err.splitlines()[0]
        if err.strip()
        else executable
    )

    if code == 0:
        record(
            "FFmpeg",
            "PASS",
            first,
        )

        return True

    record(
        "FFmpeg",
        "FAIL",
        first,
    )

    return False


# =============================================================================
# PACKAGE
# =============================================================================

def package_size():
    if not DIST_ROOT.exists():
        return 0

    return sum(
        path.stat().st_size
        for path
        in DIST_ROOT.rglob("*")
        if path.is_file()
    )


def test_package():
    if not FROZEN_EXECUTABLE.exists():
        record(
            "Frozen package",
            "FAIL",
            "Frozen executable missing.",
            remediation=(
                "PyInstaller rebuild available."
            ),
        )

        return False

    size = package_size()

    record(
        "Frozen package",
        "PASS",
        (
            f"{FROZEN_EXECUTABLE} "
            f"exists; "
            f"{size / 1024**2:.1f} MiB."
        ),
    )

    internal = (
        DIST_ROOT
        / "_internal"
    )

    required = (
        internal
        / "faster_whisper",

        internal
        / "ctranslate2",

        internal
        / "ctranslate2.libs",
    )

    missing = [
        str(path)
        for path in required
        if not path.exists()
    ]

    if missing:
        record(
            "Frozen transcription payload",
            "FAIL",
            "Missing bundled components.",
            "\n".join(missing),
        )

        return False

    record(
        "Frozen transcription payload",
        "PASS",
        (
            "Faster-Whisper, "
            "CTranslate2 and native "
            "libraries present."
        ),
    )

    unwanted = []

    for path in (
        internal.iterdir()
        if internal.exists()
        else []
    ):
        lowered = (
            path.name.lower()
        )

        if any(
            token in lowered
            for token in (
                "torch",
                "triton",
                "nvidia",
            )
        ):
            unwanted.append(
                path.name
            )

    if unwanted:
        record(
            "Frozen heavyweight payload",
            "FAIL",
            (
                "Unexpected heavyweight "
                "payload: "
                + ", ".join(
                    unwanted
                )
            ),
        )

        return False

    record(
        "Frozen heavyweight payload",
        "PASS",
        (
            "No Torch/Triton/NVIDIA "
            "top-level payload detected."
        ),
    )

    record(
        "Frozen executable SHA256",
        "INFO",
        sha256(
            FROZEN_EXECUTABLE
        )
        or "unknown",
    )

    return True


def package_is_stale():
    if not FROZEN_EXECUTABLE.exists():
        return True

    sources = [
        MAIN_SCRIPT,
        SPEC_FILE,
    ]

    for package in (
        "bci",
        "bciwhisper",
        "bci_audio",
        "bci_core",
        "bci_dsp",
    ):
        directory = (
            PROJECT_ROOT
            / package
        )

        if directory.exists():
            sources.extend(
                directory.rglob(
                    "*.py"
                )
            )

    newest_source = max(
        (
            p.stat().st_mtime
            for p in sources
            if p.exists()
        ),
        default=0,
    )

    frozen_time = (
        FROZEN_EXECUTABLE
        .stat()
        .st_mtime
    )

    return (
        newest_source
        > frozen_time
    )


def rebuild_package():
    if not SPEC_FILE.exists():
        action(
            "Rebuild frozen package",
            "FAILED",
            "BCIWhisper.spec missing.",
        )

        return False

    backup = backup_files(
        "pre-package-rebuild",
        [
            MAIN_SCRIPT,
            SPEC_FILE,
        ],
    )

    if DIST_ROOT.exists():
        shutil.rmtree(
            DIST_ROOT
        )

    build_dir = (
        PROJECT_ROOT
        / "build"
        / "BCIWhisper"
    )

    if build_dir.exists():
        shutil.rmtree(
            build_dir
        )

    code, out, err = run(
        [
            str(VENV_PYTHON),
            "-m",
            "PyInstaller",
            "--clean",
            "--noconfirm",
            str(SPEC_FILE),
        ],
        timeout=3600,
        cwd=PROJECT_ROOT,
    )

    if (
        code == 0
        and FROZEN_EXECUTABLE.exists()
    ):
        action(
            "Rebuild frozen package",
            "FIXED",
            (
                "PyInstaller rebuild "
                "completed."
            ),
            backup=str(
                backup
            ),
            after_sha=sha256(
                FROZEN_EXECUTABLE
            ),
        )

        return True

    action(
        "Rebuild frozen package",
        "FAILED",
        (
            out[-3000:]
            + "\n"
            + err[-3000:]
        ),
        backup=str(
            backup
        ),
    )

    return False


# =============================================================================
# PORTABLE DATA
# =============================================================================

def test_runtime_data():
    telemetry = (
        RUNTIME_ROOT
        / "bci_telemetry.db"
    )

    short_events = (
        RUNTIME_ROOT
        / "bci_short_events.jsonl"
    )

    present = []

    if telemetry.exists():
        present.append(
            telemetry.name
        )

    if short_events.exists():
        present.append(
            short_events.name
        )

    if present:
        record(
            "Portable runtime data",
            "PASS",
            (
                f"{RUNTIME_ROOT}: "
                + ", ".join(
                    present
                )
            ),
        )

        return True

    record(
        "Portable runtime data",
        "PARTIAL",
        (
            f"Portable root resolves "
            f"to {RUNTIME_ROOT}; "
            "runtime telemetry not "
            "yet present."
        ),
    )

    return False


# =============================================================================
# CORE DUMP ANALYSIS
# =============================================================================

def list_core_ids():
    if not shutil.which(
        "coredumpctl"
    ):
        return set()

    code, out, err = run(
        [
            "coredumpctl",
            "--no-pager",
            "list",
            "BCIWhisper",
        ],
        timeout=30,
    )

    text = (
        out
        if out.strip()
        else err
    )

    ids = set()

    for line in text.splitlines():
        if "BCIWhisper" not in line:
            continue

        match = re.search(
            r"\b(\d+)\b.*BCIWhisper",
            line,
        )

        if match:
            ids.add(
                match.group(1)
            )

    return ids


def newest_core_id():
    ids = list_core_ids()

    if not ids:
        return None

    return max(
        ids,
        key=lambda value:
            int(value),
    )


def analyze_core(core_id):
    if not core_id:
        return {
            "classification": "none",
            "detail": "No core ID.",
        }

    code, out, err = run(
        [
            "coredumpctl",
            "debug",
            str(core_id),
            "--debugger-arguments="
            "-batch "
            "-ex 'set pagination off' "
            "-ex 'thread apply all bt'",
        ],
        timeout=180,
    )

    text = out + "\n" + err

    if (
        "QWaylandShmBackingStore"
        in text
        or (
            "QPaintDevice"
            in text
            and "QtWayland"
            in text
        )
    ):
        return {
            "classification":
                "qt-wayland-backing-store",

            "detail":
                "SIGSEGV stack enters "
                "Qt Wayland backing-store "
                "painting.",

            "trace":
                text[-12000:],
        }

    if (
        "ctranslate2"
        in text.lower()
    ):
        return {
            "classification":
                "ctranslate2",

            "detail":
                "Native stack includes "
                "CTranslate2.",

            "trace":
                text[-12000:],
        }

    if (
        "libavcodec"
        in text.lower()
        or "libavformat"
        in text.lower()
    ):
        return {
            "classification":
                "ffmpeg-pyav",

            "detail":
                "Native stack includes "
                "FFmpeg/PyAV.",

            "trace":
                text[-12000:],
        }

    if (
        "portaudio"
        in text.lower()
    ):
        return {
            "classification":
                "portaudio",

            "detail":
                "Native stack includes "
                "PortAudio.",

            "trace":
                text[-12000:],
        }

    return {
        "classification":
            "unknown-native",

        "detail":
            "No known deterministic "
            "native signature matched.",

        "trace":
            text[-12000:],
    }


# =============================================================================
# GUI STARTUP CONTROL
# =============================================================================

def launch_smoke(
    qpa=None,
    seconds=12,
):
    if not FROZEN_EXECUTABLE.exists():
        return {
            "ok": False,
            "reason": "missing executable",
            "returncode": None,
        }

    env = os.environ.copy()

    if qpa:
        env["QT_QPA_PLATFORM"] = (
            qpa
        )

    process = subprocess.Popen(
        [
            str(
                FROZEN_EXECUTABLE
            )
        ],
        cwd=str(
            PROJECT_ROOT
        ),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    deadline = (
        time.monotonic()
        + seconds
    )

    while (
        time.monotonic()
        < deadline
    ):
        returncode = (
            process.poll()
        )

        if (
            returncode
            is not None
        ):
            stdout, stderr = (
                process.communicate()
            )

            return {
                "ok":
                    returncode == 0,

                "alive": False,

                "returncode":
                    returncode,

                "stdout":
                    stdout,

                "stderr":
                    stderr,
            }

        time.sleep(
            0.25
        )

    process.terminate()

    try:
        stdout, stderr = (
            process.communicate(
                timeout=5
            )
        )

    except subprocess.TimeoutExpired:
        process.kill()

        stdout, stderr = (
            process.communicate()
        )

    return {
        "ok": True,
        "alive": True,
        "returncode": None,
        "stdout": stdout,
        "stderr": stderr,
    }


def test_gui_autonomously():
    """
    Launch the actual frozen BCIWhisper application headlessly.

    The application is instructed to close itself through Qt closeEvent()
    using BCI_QA_AUTOCLOSE_MS. This verifies the real shutdown path:

        Qt close
        -> closeEvent
        -> audio boundary stop
        -> multiprocessing supervisor cleanup
        -> QApplication exit

    The operator desktop is never used.
    """

    if not FROZEN_EXECUTABLE.exists():
        record(
            "Frozen GUI startup/shutdown",
            "BLOCKED",
            "Frozen executable unavailable.",
        )
        return False

    env = os.environ.copy()

    # Force the application itself to perform a normal Qt close.
    env["BCI_QA_AUTOCLOSE_MS"] = "12000"

    xvfb = shutil.which("xvfb-run")

    if xvfb:
        command = [
            xvfb,
            "-a",
            "-s",
            "-screen 0 1920x1080x24",
            str(FROZEN_EXECUTABLE),
        ]
        backend = "Xvfb/XCB"

    else:
        command = [
            str(FROZEN_EXECUTABLE),
        ]
        env["QT_QPA_PLATFORM"] = "offscreen"
        backend = "Qt offscreen"

    print(
        f"[QA] Launching frozen application under {backend}...",
        flush=True,
    )

    before_cores = list_core_ids()

    process = subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )

    try:
        stdout, stderr = process.communicate(
            timeout=30,
        )

    except subprocess.TimeoutExpired:
        import signal

        print(
            "[QA] Graceful shutdown timeout; terminating QA process group.",
            flush=True,
        )

        try:
            os.killpg(
                process.pid,
                signal.SIGTERM,
            )
        except ProcessLookupError:
            pass

        try:
            stdout, stderr = process.communicate(
                timeout=5,
            )

        except subprocess.TimeoutExpired:
            try:
                os.killpg(
                    process.pid,
                    signal.SIGKILL,
                )
            except ProcessLookupError:
                pass

            try:
                stdout, stderr = process.communicate(
                    timeout=3,
                )
            except subprocess.TimeoutExpired:
                stdout = ""
                stderr = (
                    "QA process group retained inherited "
                    "stdout/stderr descriptors after SIGKILL."
                )

        record(
            "Frozen GUI startup/shutdown",
            "FAIL",
            (
                "Frozen BCIWhisper failed to terminate after "
                "its QA-requested graceful Qt close."
            ),
            stdout[-8000:] + "\n" + stderr[-4000:],
        )

        return False

    print(
        f"[QA] Frozen application exited with code {process.returncode}",
        flush=True,
    )

    after_cores = list_core_ids()
    new_cores = after_cores - before_cores

    if new_cores:
        newest = max(
            new_cores,
            key=lambda value: int(value),
        )

        diagnosis = analyze_core(
            newest
        )

        record(
            "Frozen GUI startup/shutdown",
            "FAIL",
            (
                f"Graceful frozen QA generated coredump PID "
                f"{newest}: {diagnosis['classification']}"
            ),
            diagnosis.get(
                "trace",
                stdout[-8000:] + "\n" + stderr[-4000:],
            ),
        )

        return False

    if process.returncode != 0:
        record(
            "Frozen GUI startup/shutdown",
            "FAIL",
            (
                f"Frozen BCIWhisper exited with status "
                f"{process.returncode}."
            ),
            stdout[-8000:] + "\n" + stderr[-4000:],
        )

        return False

    # Give multiprocessing/resource-tracker cleanup a short grace period.
    time.sleep(2)

    # Look specifically for surviving helpers from the frozen executable.
    code, helper_out, helper_err = run(
        [
            "bash",
            "-lc",
            (
                "ps -eo pid,ppid,pgid,stat,etime,cmd | "
                "grep '/dist/BCIWhisper/BCIWhisper' | "
                "grep -E 'resource_tracker|multiprocessing-fork' | "
                "grep -v grep || true"
            ),
        ],
        timeout=10,
        cwd=PROJECT_ROOT,
    )

    surviving_helpers = helper_out.strip()

    if surviving_helpers:
        record(
            "Frozen multiprocessing cleanup",
            "FAIL",
            (
                "Frozen application exited, but multiprocessing "
                "helpers remained alive after graceful Qt shutdown."
            ),
            surviving_helpers,
        )

        return False

    record(
        "Frozen multiprocessing cleanup",
        "PASS",
        (
            "No frozen BCIWhisper resource_tracker or "
            "multiprocessing-fork helper survived shutdown."
        ),
    )

    record(
        "Frozen GUI startup/shutdown",
        "PASS",
        (
            f"Frozen BCIWhisper launched under {backend}, "
            "closed through Qt closeEvent(), and exited normally."
        ),
        stdout[-6000:] + "\n" + stderr[-3000:],
    )

    return True


# =============================================================================
# AUTONOMOUS CYCLE
# =============================================================================

def clear_results_for(
    subsystem_names,
):
    global RESULTS

    RESULTS = [
        result
        for result in RESULTS
        if result.subsystem
        not in subsystem_names
    ]


def autonomous_source_cycle():
    # Source must compile first.
    if not test_compile():
        record(
            "Autonomous repair",
            "BLOCKED",
            (
                "No deterministic generic "
                "repair is permitted for "
                "unknown Python syntax."
            ),
        )

        return False

    test_modules()
    test_identity()
    test_gui_tabs()
    test_transcript_tab()

    if not test_manual_only_policy():
        repair_auto_transcription()

        clear_results_for(
            {
                "Manual-only transcription",
                "BCIWhisper.py compile",
            }
        )

        test_compile()
        test_manual_only_policy()

    test_architecture()

    return True


def autonomous_backend_cycle():
    test_ffmpeg()

    backend_ok = test_backends()

    if not backend_ok:
        repair_backend()

        clear_results_for(
            {
                "Transcription backend",
            }
        )

        backend_ok = (
            test_backends()
        )

    model_ok = test_model()

    if not model_ok:
        repair_model()

        clear_results_for(
            {
                "Faster-Whisper model",
            }
        )

        model_ok = test_model()

    if (
        backend_ok
        and model_ok
    ):
        test_inference()
    else:
        record(
            "Isolated inference",
            "BLOCKED",
            (
                "Backend/model repair "
                "did not reach acceptance."
            ),
        )


def autonomous_package_cycle():
    stale = package_is_stale()

    package_ok = test_package()

    if (
        stale
        or not package_ok
    ):
        reason = (
            "source/spec newer than "
            "frozen executable"
            if stale
            else "package acceptance failed"
        )

        action(
            "Package rebuild decision",
            "AUTO",
            reason,
        )

        rebuilt = rebuild_package()

        clear_results_for(
            {
                "Frozen package",
                "Frozen transcription payload",
                "Frozen heavyweight payload",
                "Frozen executable SHA256",
            }
        )

        if rebuilt:
            test_package()
        else:
            record(
                "Frozen package rebuild",
                "FAIL",
                (
                    "Automatic package "
                    "rebuild failed."
                ),
            )


def autonomous_runtime_cycle():
    test_runtime_data()
    test_recordings()

    test_gui_autonomously()


# =============================================================================
# HISTORICAL CORE STATUS
# =============================================================================

def report_core_history():
    cores = list_core_ids()

    if not cores:
        record(
            "Recent coredumps",
            "PASS",
            (
                "No BCIWhisper "
                "coredumps listed."
            ),
        )

        return

    newest = max(
        cores,
        key=lambda x:
            int(x),
    )

    diagnosis = analyze_core(
        newest
    )

    record(
        "Recent coredumps",
        "PARTIAL",
        (
            f"{len(cores)} historical "
            "BCIWhisper coredump(s); "
            f"newest PID {newest}; "
            f"classification="
            f"{diagnosis['classification']}."
        ),
    )


# =============================================================================
# FINAL ACCEPTANCE
# =============================================================================

def derive_release_status():
    blocking = [
        result
        for result in RESULTS
        if result.status
        in {
            "FAIL",
            "BLOCKED",
        }
    ]

    if blocking:
        return (
            "NOT READY"
        )

    partial = [
        result
        for result in RESULTS
        if result.status
        == "PARTIAL"
        and result.subsystem
        != "Recent coredumps"
    ]

    if partial:
        return (
            "CONDITIONAL"
        )

    return (
        "ACCEPTANCE PASSED"
    )


def write_report():
    counts = {}

    for result in RESULTS:
        counts[
            result.status
        ] = (
            counts.get(
                result.status,
                0,
            )
            + 1
        )

    release_status = (
        derive_release_status()
    )

    payload = {
        "generated_at":
            datetime.now()
            .astimezone()
            .isoformat(),

        "project_root":
            str(PROJECT_ROOT),

        "hostname":
            platform.node(),

        "python":
            sys.version,

        "python_executable":
            sys.executable,

        "source_sha":
            sha256(
                MAIN_SCRIPT
            ),

        "frozen_sha":
            sha256(
                FROZEN_EXECUTABLE
            ),

        "release_status":
            release_status,

        "summary":
            counts,

        "results": [
            asdict(
                result
            )
            for result in RESULTS
        ],

        "actions": [
            asdict(
                item
            )
            for item in ACTIONS
        ],
    }

    REPORT_JSON.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    lines = [
        "=" * 78,
        "BEACON COMPUTING INITIATIVE",
        (
            "BCIWHISPER v6.0 / "
            "SCRIPT 57.9 RUNTIME HARDENING"
        ),
        (
            "Developer Seal: "
            "CJB-DEV-2026"
        ),
        "=" * 78,
        "",
        (
            "Generated: "
            + payload[
                "generated_at"
            ]
        ),
        (
            "Source SHA256: "
            + str(
                payload[
                    "source_sha"
                ]
            )
        ),
        (
            "Frozen SHA256: "
            + str(
                payload[
                    "frozen_sha"
                ]
            )
        ),
        "",
        "AUTONOMOUS ACTIONS",
        "-" * 78,
    ]

    if ACTIONS:
        for item in ACTIONS:
            lines.append(
                f"[{item.status}] "
                f"{item.action}"
            )

            lines.append(
                f"  {item.detail}"
            )

            if item.backup:
                lines.append(
                    "  Backup: "
                    + item.backup
                )

            if item.before_sha:
                lines.append(
                    "  Before: "
                    + item.before_sha
                )

            if item.after_sha:
                lines.append(
                    "  After: "
                    + item.after_sha
                )

            lines.append("")

    else:
        lines.append(
            "No remediation was required."
        )
        lines.append("")

    lines.extend(
        [
            "RESULTS",
            "-" * 78,
        ]
    )

    for result in RESULTS:
        lines.append(
            f"[{result.status}] "
            f"{result.subsystem}"
        )

        lines.append(
            "  "
            + result.detail
        )

        if result.evidence:
            for line in (
                result.evidence
                .splitlines()
            ):
                lines.append(
                    "    "
                    + line
                )

        if result.remediation:
            lines.append(
                "  Remediation: "
                + result.remediation
            )

        lines.append("")

    lines.extend(
        [
            "SUMMARY",
            "-" * 78,
        ]
    )

    for state in (
        "PASS",
        "FIXED",
        "FAIL",
        "PARTIAL",
        "BLOCKED",
        "INFO",
    ):
        lines.append(
            f"{state:12} "
            f"{counts.get(state, 0)}"
        )

    lines.extend(
        [
            "",
            "RELEASE STATUS",
            "-" * 78,
            release_status,
            "",
            (
                "Observe accurately. "
                "Preserve faithfully. "
                "Analyze transparently. "
                "Communicate securely. "
                "Act deliberately."
            ),
            "",
        ]
    )

    REPORT_TXT.write_text(
        "\n".join(
            lines
        ),
        encoding="utf-8",
    )

    return (
        release_status,
        counts,
    )


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description=(
            "BCIWhisper 57.8 autonomous "
            "acceptance controller."
        )
    )

    parser.add_argument(
        "--no-gui",
        action="store_true",
        help=(
            "Skip graphical runtime smoke "
            "testing while retaining all "
            "other autonomous tests."
        ),
    )

    args = parser.parse_args()

    ACTION_LOG.write_text(
        "",
        encoding="utf-8",
    )

    BACKUP_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    global INITIAL_CORE_IDS

    INITIAL_CORE_IDS = (
        list_core_ids()
    )

    print()
    print(
        "=" * 78
    )
    print(
        " BCIWHISPER v6.0 / SCRIPT 57.8 "
        "AUTONOMOUS ACCEPTANCE"
    )
    print(
        "=" * 78
    )
    print()

    record(
        "Controller mode",
        "INFO",
        (
            "Autonomous test / diagnose / "
            "repair / retest enabled."
        ),
    )

    try:
        source_ok = (
            autonomous_source_cycle()
        )

        if source_ok:
            autonomous_backend_cycle()
            autonomous_package_cycle()

            if not args.no_gui:
                autonomous_runtime_cycle()
            else:
                test_runtime_data()
                test_recordings()

                record(
                    "Frozen GUI startup",
                    "BLOCKED",
                    (
                        "Skipped by "
                        "--no-gui."
                    ),
                )

        else:
            record(
                "Downstream acceptance",
                "BLOCKED",
                (
                    "Source prerequisite "
                    "failed."
                ),
            )

        report_core_history()

    except KeyboardInterrupt:
        record(
            "Controller",
            "BLOCKED",
            "Interrupted by operator.",
        )

    except Exception:
        record(
            "Controller",
            "FAIL",
            (
                "Unhandled controller "
                "exception."
            ),
            traceback.format_exc(),
        )

    release_status, counts = (
        write_report()
    )

    print()
    print(
        "=" * 78
    )
    print(
        "AUTONOMOUS ACCEPTANCE COMPLETE"
    )
    print(
        "=" * 78
    )

    print(
        f"Text report: {REPORT_TXT}"
    )

    print(
        f"JSON report: {REPORT_JSON}"
    )

    print(
        f"Action log: {ACTION_LOG}"
    )

    print()

    print(
        "PASS={pass_count} "
        "FAIL={fail_count} "
        "PARTIAL={partial_count} "
        "BLOCKED={blocked_count}".format(
            pass_count=counts.get(
                "PASS",
                0,
            ),
            fail_count=counts.get(
                "FAIL",
                0,
            ),
            partial_count=counts.get(
                "PARTIAL",
                0,
            ),
            blocked_count=counts.get(
                "BLOCKED",
                0,
            ),
        )
    )

    print(
        "RELEASE STATUS: "
        + release_status
    )

    # Non-zero only for actual FAIL.
    # BLOCKED remains visible in the report
    # without making the controller itself
    # appear to have crashed.
    if counts.get(
        "FAIL",
        0,
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
