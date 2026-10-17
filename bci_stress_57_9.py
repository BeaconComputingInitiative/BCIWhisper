#!/usr/bin/env python3

import argparse
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
FROZEN_EXECUTABLE = PROJECT_ROOT / "dist" / "BCIWhisper" / "BCIWhisper"

DATA_ROOT = Path(
    os.environ.get(
        "BCI_DATA_DIR",
        Path.home() / ".local" / "share" / "BCIWhisper",
    )
)

TELEMETRY_DB = DATA_ROOT / "bci_telemetry.db"

TEXT_REPORT = PROJECT_ROOT / "bci_stress_57_9.txt"
JSON_REPORT = PROJECT_ROOT / "bci_stress_57_9.json"
LOG_DIR = PROJECT_ROOT / "stress_logs_57_9"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def run_command(command, timeout=10):
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as exc:
        return 255, "", str(exc)


def frozen_helpers():
    """
    Return BCIWhisper multiprocessing helper processes currently alive.
    """
    code, out, err = run_command(
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
        timeout=5,
    )

    return [
        line.strip()
        for line in out.splitlines()
        if line.strip()
    ]


def frozen_processes():
    """
    Return all currently running frozen BCIWhisper processes.
    """
    code, out, err = run_command(
        [
            "bash",
            "-lc",
            (
                "ps -eo pid,ppid,pgid,stat,etime,cmd | "
                "grep '/dist/BCIWhisper/BCIWhisper' | "
                "grep -v grep || true"
            ),
        ],
        timeout=5,
    )

    return [
        line.strip()
        for line in out.splitlines()
        if line.strip()
    ]


def coredump_snapshot():
    """
    Snapshot BCIWhisper-related coredumpctl output.

    Historical entries are retained. We only care whether the set grows
    during this stress run.
    """
    if shutil.which("coredumpctl") is None:
        return set()

    code, out, err = run_command(
        [
            "bash",
            "-lc",
            (
                "coredumpctl --no-pager --no-legend list 2>/dev/null | "
                "grep -i 'BCIWhisper' || true"
            ),
        ],
        timeout=10,
    )

    return {
        line.strip()
        for line in out.splitlines()
        if line.strip()
    }


def sqlite_integrity():
    if not TELEMETRY_DB.exists():
        return False, f"Telemetry DB missing: {TELEMETRY_DB}"

    try:
        connection = sqlite3.connect(
            f"file:{TELEMETRY_DB}?mode=ro",
            uri=True,
            timeout=5.0,
        )

        try:
            row = connection.execute(
                "PRAGMA quick_check;"
            ).fetchone()
        finally:
            connection.close()

        if row and str(row[0]).lower() == "ok":
            return True, "PRAGMA quick_check = ok"

        return False, f"quick_check returned: {row}"

    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def kill_process_group(process):
    if process.poll() is not None:
        return

    try:
        os.killpg(
            process.pid,
            signal.SIGTERM,
        )
    except ProcessLookupError:
        return

    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        os.killpg(
            process.pid,
            signal.SIGKILL,
        )
    except ProcessLookupError:
        return

    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass


def build_command():
    xvfb = shutil.which("xvfb-run")

    if xvfb:
        return (
            [
                xvfb,
                "-a",
                "-s",
                "-screen 0 1920x1080x24",
                str(FROZEN_EXECUTABLE),
            ],
            "Xvfb/XCB",
        )

    return (
        [str(FROZEN_EXECUTABLE)],
        "Qt offscreen",
    )


def run_cycle(index, runtime_ms, timeout_seconds):
    command, backend = build_command()

    env = os.environ.copy()
    env["BCI_QA_AUTOCLOSE_MS"] = str(runtime_ms)

    if backend == "Qt offscreen":
        env["QT_QPA_PLATFORM"] = "offscreen"

    log_path = LOG_DIR / f"cycle_{index:03d}.log"

    started = time.monotonic()

    process = subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )

    timed_out = False
    output = ""

    try:
        output, _ = process.communicate(
            timeout=timeout_seconds,
        )

    except subprocess.TimeoutExpired:
        timed_out = True
        kill_process_group(process)

        try:
            remaining, _ = process.communicate(
                timeout=3,
            )
            output += remaining or ""
        except Exception:
            pass

    elapsed = time.monotonic() - started

    log_path.write_text(
        output,
        encoding="utf-8",
        errors="replace",
    )

    # Give multiprocessing cleanup a short opportunity to complete.
    time.sleep(1.0)

    helpers = frozen_helpers()
    processes = frozen_processes()

    timer_fired = (
        "[BCI][QA] autoclose timer FIRED"
        in output
    )

    close_enter = (
        "[BCI][SHUTDOWN] closeEvent ENTER"
        in output
    )

    boundary_stopped = (
        "[BCI][SHUTDOWN] audio boundary stop returned running=False"
        in output
    )

    close_exit = (
        "[BCI][SHUTDOWN] closeEvent EXIT accepted"
        in output
    )

    window_returned = (
        "[BCI][QA] window.close() returned True"
        in output
    )

    return {
        "cycle": index,
        "backend": backend,
        "runtime_ms": runtime_ms,
        "elapsed_seconds": round(elapsed, 3),
        "returncode": process.returncode,
        "timed_out": timed_out,
        "timer_fired": timer_fired,
        "close_enter": close_enter,
        "boundary_stopped": boundary_stopped,
        "close_exit": close_exit,
        "window_returned": window_returned,
        "surviving_helpers": helpers,
        "surviving_processes": processes,
        "log": str(log_path),
    }


def cycle_passed(result):
    return all(
        [
            not result["timed_out"],
            result["returncode"] == 0,
            result["timer_fired"],
            result["close_enter"],
            result["boundary_stopped"],
            result["close_exit"],
            result["window_returned"],
            not result["surviving_helpers"],
            not result["surviving_processes"],
        ]
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "BCIWhisper v6.0 / Script 57.9 "
            "runtime lifecycle stress test"
        )
    )

    parser.add_argument(
        "--cycles",
        type=int,
        default=25,
        help="Number of complete launch/shutdown cycles.",
    )

    parser.add_argument(
        "--runtime-ms",
        type=int,
        default=8000,
        help="Milliseconds each BCIWhisper instance runs before Qt close.",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Hard timeout for each cycle in seconds.",
    )

    parser.add_argument(
        "--continue-on-failure",
        action="store_true",
        help="Continue remaining cycles after a failed cycle.",
    )

    args = parser.parse_args()

    if args.cycles < 1:
        raise SystemExit("--cycles must be >= 1")

    if args.runtime_ms < 1000:
        raise SystemExit("--runtime-ms must be >= 1000")

    if args.timeout < 5:
        raise SystemExit("--timeout must be >= 5")

    if not FROZEN_EXECUTABLE.exists():
        raise SystemExit(
            f"[FAIL] Frozen executable missing: {FROZEN_EXECUTABLE}"
        )

    LOG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 78)
    print("BCIWHISPER v6.0 / SCRIPT 57.9 RUNTIME STRESS TEST")
    print("=" * 78)
    print()
    print(f"[INFO] Executable: {FROZEN_EXECUTABLE}")
    print(f"[INFO] Cycles: {args.cycles}")
    print(f"[INFO] Runtime per cycle: {args.runtime_ms} ms")
    print(f"[INFO] Hard timeout: {args.timeout}s")
    print()

    preexisting_helpers = frozen_helpers()

    if preexisting_helpers:
        print("[FAIL] Pre-existing BCIWhisper helpers detected:")
        for line in preexisting_helpers:
            print(f"       {line}")

        print()
        print(
            "Clean old test processes before running the stress test."
        )

        return 2

    db_before_ok, db_before_detail = sqlite_integrity()

    print(
        f"[{'PASS' if db_before_ok else 'FAIL'}] "
        f"Telemetry pre-test: {db_before_detail}"
    )

    cores_before = coredump_snapshot()

    results = []

    stress_started = time.monotonic()

    for cycle in range(1, args.cycles + 1):
        print()
        print(
            f"[CYCLE {cycle:03d}/{args.cycles:03d}] "
            f"launching...",
            flush=True,
        )

        result = run_cycle(
            cycle,
            args.runtime_ms,
            args.timeout,
        )

        passed = cycle_passed(result)

        result["passed"] = passed
        results.append(result)

        status = "PASS" if passed else "FAIL"

        print(
            f"[{status}] cycle={cycle:03d} "
            f"exit={result['returncode']} "
            f"time={result['elapsed_seconds']:.3f}s "
            f"helpers={len(result['surviving_helpers'])} "
            f"processes={len(result['surviving_processes'])}"
        )

        if not passed:
            print(
                f"       timer={result['timer_fired']} "
                f"close_enter={result['close_enter']} "
                f"boundary_stop={result['boundary_stopped']} "
                f"close_exit={result['close_exit']} "
                f"window_return={result['window_returned']} "
                f"timeout={result['timed_out']}"
            )

            print(
                f"       log={result['log']}"
            )

            if result["surviving_helpers"]:
                print("       surviving helpers:")
                for line in result["surviving_helpers"]:
                    print(f"         {line}")

            if result["surviving_processes"]:
                print("       surviving processes:")
                for line in result["surviving_processes"]:
                    print(f"         {line}")

            if not args.continue_on_failure:
                print(
                    "[INFO] stopping stress test on first failure"
                )
                break

    total_elapsed = time.monotonic() - stress_started

    # Final cleanup/integrity checks.
    time.sleep(2)

    db_after_ok, db_after_detail = sqlite_integrity()

    cores_after = coredump_snapshot()
    new_cores = sorted(
        cores_after - cores_before
    )

    final_helpers = frozen_helpers()
    final_processes = frozen_processes()

    passed_cycles = sum(
        1 for result in results
        if result["passed"]
    )

    failed_cycles = len(results) - passed_cycles

    lifecycle_pass = (
        failed_cycles == 0
        and len(results) == args.cycles
    )

    orphan_pass = (
        not final_helpers
        and not final_processes
    )

    coredump_pass = (
        not new_cores
    )

    telemetry_pass = (
        db_before_ok
        and db_after_ok
    )

    overall_pass = all(
        [
            lifecycle_pass,
            orphan_pass,
            coredump_pass,
            telemetry_pass,
        ]
    )

    report = {
        "test": "BCIWhisper Script 57.9 Runtime Stress",
        "timestamp_utc": now_iso(),
        "cycles_requested": args.cycles,
        "cycles_completed": len(results),
        "cycles_passed": passed_cycles,
        "cycles_failed": failed_cycles,
        "runtime_ms": args.runtime_ms,
        "timeout_seconds": args.timeout,
        "total_elapsed_seconds": round(
            total_elapsed,
            3,
        ),
        "telemetry_before": {
            "passed": db_before_ok,
            "detail": db_before_detail,
        },
        "telemetry_after": {
            "passed": db_after_ok,
            "detail": db_after_detail,
        },
        "new_coredumps": new_cores,
        "final_helpers": final_helpers,
        "final_processes": final_processes,
        "overall_pass": overall_pass,
        "cycles": results,
    }

    JSON_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    text_lines = [
        "=" * 78,
        "BCIWHISPER v6.0 / SCRIPT 57.9 RUNTIME STRESS REPORT",
        "=" * 78,
        "",
        f"Timestamp UTC: {report['timestamp_utc']}",
        f"Cycles requested: {args.cycles}",
        f"Cycles completed: {len(results)}",
        f"Cycles passed: {passed_cycles}",
        f"Cycles failed: {failed_cycles}",
        f"Runtime per cycle: {args.runtime_ms} ms",
        f"Total elapsed: {total_elapsed:.3f}s",
        "",
        (
            "Telemetry before: "
            f"{'PASS' if db_before_ok else 'FAIL'} "
            f"({db_before_detail})"
        ),
        (
            "Telemetry after: "
            f"{'PASS' if db_after_ok else 'FAIL'} "
            f"({db_after_detail})"
        ),
        (
            "New coredumps: "
            f"{len(new_cores)}"
        ),
        (
            "Final multiprocessing helpers: "
            f"{len(final_helpers)}"
        ),
        (
            "Final frozen processes: "
            f"{len(final_processes)}"
        ),
        "",
        (
            "RESULT: "
            + (
                "STRESS TEST PASSED"
                if overall_pass
                else "STRESS TEST FAILED"
            )
        ),
        "",
    ]

    TEXT_REPORT.write_text(
        "\n".join(text_lines),
        encoding="utf-8",
    )

    print()
    print("=" * 78)
    print("57.9 STRESS TEST COMPLETE")
    print("=" * 78)

    print(
        f"Cycles: {passed_cycles} PASS / "
        f"{failed_cycles} FAIL"
    )

    print(
        f"Telemetry: "
        f"{'PASS' if telemetry_pass else 'FAIL'}"
    )

    print(
        f"New coredumps: {len(new_cores)}"
    )

    print(
        f"Surviving helpers: {len(final_helpers)}"
    )

    print(
        f"Surviving frozen processes: {len(final_processes)}"
    )

    print()
    print(f"Text report: {TEXT_REPORT}")
    print(f"JSON report: {JSON_REPORT}")
    print(f"Cycle logs: {LOG_DIR}")

    print()

    if overall_pass:
        print("RESULT: STRESS TEST PASSED")
        return 0

    print("RESULT: STRESS TEST FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
