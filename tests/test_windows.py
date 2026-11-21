"""Windows launch / sh / kill paths (issue #49), driven on any OS by patching sstack_ade._WINDOWS."""
import sys
from pathlib import Path
from unittest import mock

from helpers import REPO, TempEnv
import sstack_ade as A
import sstack_gate as G


class WindowsPaths(TempEnv):
    def script(self, name, first):
        p = self.home / name
        p.write_text(first + "\necho hi\n", encoding="utf-8")
        return p

    def test_kill_group_taskkills_the_tree_then_kills(self):
        p = mock.Mock(pid=4242)
        with mock.patch.object(A, "_WINDOWS", True), mock.patch.object(A.subprocess, "run") as run:
            A.kill_group(p)
        run.assert_called_once_with(["taskkill", "/T", "/F", "/PID", "4242"], capture_output=True)
        p.kill.assert_called_once_with()
        p.wait.assert_called_once_with()

    def test_launch(self):
        py = self.script("x.hook", "#!/usr/bin/env python3")
        shs = self.script("run.sh", "#!/bin/sh")
        with mock.patch.object(A, "_WINDOWS", False):
            self.assertEqual(A.launch(py), [str(py)])  # POSIX: unchanged
        with mock.patch.object(A, "_WINDOWS", True), \
                mock.patch.object(A.shutil, "which", return_value=r"C:\Git\bin\sh.exe"):
            self.assertEqual(A.launch(py), [sys.executable, str(py)])
            self.assertEqual(A.launch(shs), [r"C:\Git\bin\sh.exe", str(shs)])

    def test_missing_sh_fails_verify_with_one_clear_line(self):
        with mock.patch.object(A.shutil, "which", return_value=None):
            ok, summary, errors, log = G._run_verify(self.home, ["true"])
        self.assertFalse(ok)
        self.assertIn("could not start", summary)
        self.assertIn("needs sh on PATH (install Git for Windows, or use WSL)", errors[0])
        self.assertNotIn("Traceback", log)

    def test_every_bin_command_has_a_cmd_shim(self):
        for f in (REPO / "bin").iterdir():
            if f.is_file() and not f.suffix:
                shim = f.with_name(f.name + ".cmd")
                self.assertTrue(shim.is_file(), f"{shim.name} missing")
                self.assertEqual(shim.read_bytes(), f'@python "%~dp0{f.name}" %*\r\n'.encode())

    def test_lock_owner_is_posix_and_matches_release(self):
        import sstack_dispatch as D
        import sstack_workflow as W
        run = self.root / ".sstack" / "runs" / "task-1"
        owner = D.lock_owner(self.root, run / "sub" / "r.md")
        self.assertEqual(owner, ".sstack/runs/task-1")
        with mock.patch.object(D, "lock_release") as rel:
            W.release(self.root, run)
        rel.assert_called_once_with(self.root, owner)

    def test_resolve_finds_cmd_shims_on_windows_only(self):
        with mock.patch.object(A.shutil, "which", return_value=r"C:\npm\codex.CMD"):
            with mock.patch.object(A, "_WINDOWS", False):
                self.assertEqual(A.resolve(["codex", "exec"]), ["codex", "exec"])
            with mock.patch.object(A, "_WINDOWS", True):
                self.assertEqual(A.resolve(["codex", "exec"]), [r"C:\npm\codex.CMD", "exec"])
        with mock.patch.object(A, "_WINDOWS", True), mock.patch.object(A.shutil, "which", return_value=None):
            self.assertEqual(A.resolve(["nope"]), ["nope"])
