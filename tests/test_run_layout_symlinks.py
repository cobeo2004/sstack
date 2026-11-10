"""Review findings on the nested run layout: symlinks never carry a run or a cleanup outside
.sstack/runs/, and the reflect state migration keeps every session's offset."""
import json, os, tempfile, unittest
from pathlib import Path

from test_dispatch import FakeCliBase, T3
from test_doctor import DoctorBase
from test_reflect_dedupe import ReflectDedupeTests
import sstack_dispatch as D
import sstack_doctor as Doc


class DispatchSymlinkTests(FakeCliBase):
    def test_symlinked_dispatch_dir_stays_flat(self):
        self.example()
        outside = Path(tempfile.mkdtemp())
        task = self.root / ".sstack/runs/task-x"
        task.mkdir(parents=True)
        os.symlink(outside, task / "dispatch")
        code, out, err = self.run_main("scout", "--brief", self.brief(), "--report", str(task / "s.md"), env=T3)
        self.assertEqual(code, 4, err)
        run_dir = Path(json.loads(out)["run_dir"])
        self.assertEqual(run_dir.parent, self.root / ".sstack/runs")
        self.assertEqual(list(outside.iterdir()), [])


class DoctorSymlinkTests(DoctorBase):
    def test_cleanup_refuses_a_symlinked_doctor_dir(self):
        outside = self.home / "outside"
        victim = outside / "smoke-20260101-1200"
        victim.mkdir(parents=True)
        (victim / "keep.txt").write_text("x")
        runs = self.root / ".sstack/runs"
        runs.mkdir(parents=True)
        os.symlink(outside, runs / "doctor")
        self.assertIsNone(Doc._owned(self.root, runs / "doctor/smoke-20260101-1200"))
        self.assertFalse(Doc._cleanup(self.root, runs / "doctor/smoke-20260101-1200", []))
        self.assertTrue((victim / "keep.txt").exists())


class ReflectMigrationTests(ReflectDedupeTests):
    def test_migration_keeps_other_sessions_offsets(self):
        self.setup_agent("NONE\nPASS")
        self.write(self.root, ".sstack/runs/reflect-state.json", '{"s1": 1, "s2": 1}')
        t = self.root / "t.jsonl"; t.write_text('{"n":1}\n{"n":2}\n')
        self.hook(t, session="s1")
        state = json.loads((self.root / ".sstack/runs/reflect/state.json").read_text())
        self.assertEqual(state, {"s1": 2, "s2": 1})


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for cls in (DispatchSymlinkTests, DoctorSymlinkTests, ReflectMigrationTests):
        for name in sorted(cls.__dict__):
            if name.startswith("test_"):
                suite.addTest(cls(name))
    return suite
