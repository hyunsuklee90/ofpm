from __future__ import annotations

import os
import selectors
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar


T = TypeVar("T")


def _render_live_line(label: str, spinner_index: int, started: float, status: str) -> None:
    spinner = "|/-\\"
    elapsed = time.monotonic() - started
    frame = spinner[spinner_index % len(spinner)]
    sys.stdout.write(f"\r - {label} {frame} {elapsed:4.1f}s {status[:120]}")
    sys.stdout.flush()


def run_command_live(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    label: str,
    merge_stderr: bool = True,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
        text=False,
        bufsize=0,
    )
    assert process.stdout is not None

    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    if not merge_stderr and process.stderr is not None:
        selector.register(process.stderr, selectors.EVENT_READ)

    spinner_index = 0
    started = time.monotonic()
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    partials: dict[object, str] = {}
    last_message = "starting"
    last_render = 0.0

    while True:
        events = selector.select(timeout=0.2)
        if events:
            for key, _mask in events:
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                if key.fileobj is process.stdout:
                    stdout_chunks.append(data)
                else:
                    stderr_chunks.append(data)
                partial = partials.get(key.fileobj, "") + data.decode("utf-8", errors="replace")
                while "\n" in partial:
                    line, partial = partial.split("\n", 1)
                    stripped = line.strip()
                    if stripped:
                        last_message = stripped
                partials[key.fileobj] = partial
        if process.poll() is not None and not events:
            break
        now = time.monotonic()
        if now - last_render >= 0.2:
            _render_live_line(label, spinner_index, started, last_message)
            spinner_index += 1
            last_render = now

    for partial in partials.values():
        if partial.strip():
            last_message = partial.strip().splitlines()[-1]

    selector.close()
    output = b"".join(stdout_chunks).decode("utf-8", errors="replace")
    stderr_output = b"".join(stderr_chunks).decode("utf-8", errors="replace")
    if merge_stderr:
        output = output + stderr_output
    if process.returncode == 0:
        sys.stdout.write(f"\r - {label} done {time.monotonic() - started:4.1f}s {last_message[:120]}\n")
        sys.stdout.flush()
        return subprocess.CompletedProcess(cmd, 0, output, stderr_output)

    sys.stdout.write(f"\r - {label} failed {time.monotonic() - started:4.1f}s {last_message[:120]}\n")
    sys.stdout.flush()
    raise subprocess.CalledProcessError(process.returncode or 1, cmd, output=output, stderr=stderr_output)


def run_task_live(
    label: str,
    func: Callable[[], T],
    *,
    status: str = "working",
) -> T:
    started = time.monotonic()
    spinner_index = 0
    last_render = 0.0
    result: dict[str, T] = {}
    error: dict[str, BaseException] = {}

    def worker() -> None:
        try:
            result["value"] = func()
        except BaseException as exc:
            error["value"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    while thread.is_alive():
        now = time.monotonic()
        if now - last_render >= 0.2:
            _render_live_line(label, spinner_index, started, status)
            spinner_index += 1
            last_render = now
        thread.join(timeout=0.2)

    thread.join()
    if "value" in error:
        sys.stdout.write(f"\r - {label} failed {time.monotonic() - started:4.1f}s {status[:120]}\n")
        sys.stdout.flush()
        raise error["value"]

    sys.stdout.write(f"\r - {label} done {time.monotonic() - started:4.1f}s {status[:120]}\n")
    sys.stdout.flush()
    return result["value"]
