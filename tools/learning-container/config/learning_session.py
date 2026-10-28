#!/usr/bin/env python3
"""Supervise one interactive docker-exec shell and reap its descendants."""

import ctypes
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def descendants():
    parents = {}
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            # comm can contain spaces, so split after its closing parenthesis.
            fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            parents[int(entry.name)] = int(fields[1])
        except (OSError, ValueError, IndexError):
            continue
    found = {os.getpid()}
    while True:
        added = {pid for pid, parent in parents.items() if parent in found} - found
        if not added:
            return found - {os.getpid()}
        found.update(added)


def send(pids, sig):
    for pid in pids:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass


def reap():
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                return
        except ChildProcessError:
            return


def main():
    token = sys.argv[1]
    if not token.isalnum():
        raise ValueError('Invalid session token')
    pid_file = Path('/tmp') / ('ros2_learning_session_' + token + '.pid')
    if len(sys.argv) == 3 and sys.argv[2] == '--stop':
        try:
            pid = int(pid_file.read_text())
            # Check identity before sending a signal to a PID that may be reused.
            args = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
            if token.encode() in args and b'/learning/config/learning_session.py' in args:
                os.kill(pid, signal.SIGHUP)
        except (OSError, ValueError):
            pass
        return

    # Adopt/reap orphaned grandchildren instead of handing them to sleep PID 1.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), 'Cannot enable child subreaper')

    stopping = False

    def request_stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGHUP, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    pid_file.write_text(str(os.getpid()))

    def restore_child_signals():
        # The supervisor ignores Ctrl+C; the interactive shell/nodes must not.
        for sig in (signal.SIGINT, signal.SIGHUP, signal.SIGTERM):
            signal.signal(sig, signal.SIG_DFL)

    shell = subprocess.Popen([
        'bash', '--noprofile', '--rcfile', '/learning/config/learning.bashrc',
    ], preexec_fn=restore_child_signals)
    try:
        while not stopping and shell.poll() is None:
            time.sleep(0.1)
    finally:
        # Give ROS nodes time to cancel/park before terminating the shell.
        send(descendants() - {shell.pid}, signal.SIGINT)
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            reap()
            if not (descendants() - {shell.pid}):
                break
            time.sleep(0.05)
        send(descendants(), signal.SIGTERM)
        deadline = time.monotonic() + 1.0
        while descendants() and time.monotonic() < deadline:
            reap()
            time.sleep(0.05)
        # Interactive bash can ignore TERM; collect it and all remaining children.
        while descendants():
            send(descendants(), signal.SIGKILL)
            reap()
            time.sleep(0.02)
        reap()
        pid_file.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
