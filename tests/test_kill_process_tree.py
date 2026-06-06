"""R3-20: a stream-execute timeout must kill the whole child tree, not just the
direct child. Spawns a real parent process that spawns a real grandchild, then
asserts _kill_process_tree reaps both.
"""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

psutil = pytest.importorskip("psutil")

import core.handlers.code_exec as ce


def _spawn_parent_with_child() -> tuple[subprocess.Popen, int]:
    # Parent prints its child's PID, then both sleep well past the test.
    code = (
        "import subprocess, sys, time;"
        "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
        "print(c.pid, flush=True);"
        "time.sleep(60)"
    )
    grp: dict = {}
    if sys.platform == "win32":
        grp["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        grp["start_new_session"] = True
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                            text=True, **grp)
    child_pid = int(proc.stdout.readline().strip())
    return proc, child_pid


def test_kill_process_tree_reaps_grandchild() -> None:
    proc, child_pid = _spawn_parent_with_child()
    try:
        assert psutil.pid_exists(child_pid)        # grandchild is alive

        ce._kill_process_tree(proc)

        # Give the OS a moment to tear the tree down.
        deadline = time.monotonic() + 5.0
        while psutil.pid_exists(child_pid) and time.monotonic() < deadline:
            time.sleep(0.05)

        assert proc.poll() is not None, "parent survived the tree-kill"
        assert not psutil.pid_exists(child_pid), "grandchild orphaned by the kill"
    finally:
        # Safety net so a failed assert never leaves test processes running.
        for pid in (child_pid, proc.pid):
            try:
                psutil.Process(pid).kill()
            except Exception:
                pass
