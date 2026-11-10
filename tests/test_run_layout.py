"""Answer key for the nested run layout (docs/spec/dispatch.md § Run layout): a task's dispatches
nest under its run folder, reflect and smoke get their own homes, and old runs can be pruned."""
import json, os, re, subprocess, time, unittest
from pathlib import Path

from helpers import TempEnv
from test_dispatch import FakeCliBase, T3
from test_doctor import DoctorBase, SmokeTests, roles
from test_reflect_dedupe import ReflectDedupeTests
from test_ui import ServerTests
import sstack_dispatch as D


def entries(d: Path) -> set[str]:
    return {p.name for p in d.iterdir()} if d.exists() else set()


class NestedDispatchTests(FakeCliBase):
    def runs(self) -> Path:
        return self.root / ".sstack/runs"

    def dispatch_to(self, role, report: Path, *extra):
        code, out, err = self.run_main(role, "--brief", self.brief(), "--report", str(report), *extra, env=T3)
        self.assertEqual(code, 4, err)
        return json.loads(out)

    def test_report_in_task_folder_nests_dispatch(self):  # T1.a
        self.example()
        d = self.dispatch_to("scout", self.runs() / "task-x" / "s.md")
        run_dir = Path(d["run_dir"])
        self.assertEqual(run_dir.parent, self.runs() / "task-x" / "dispatch")
        self.assertRegex(run_dir.name, r"^\d{4}-scout$")
        self.assertTrue((run_dir / "run.json").is_file())
        self.assertEqual(entries(self.runs()), {"task-x"})

    def test_report_directly_in_runs_stays_flat(self):  # T1.a2
        self.example()
        d = self.dispatch_to("scout", self.runs() / "x.md")
        run_dir = Path(d["run_dir"])
        self.assertEqual(run_dir.parent, self.runs())
        self.assertRegex(run_dir.name, r"^\d{8}-\d{4}-scout$")
        self.assertFalse((self.runs() / "dispatch").exists())

    def test_report_in_task_subfolder_nests_beside_it(self):  # T1.a3
        self.example()
        d = self.dispatch_to("review", self.runs() / "task-x" / "reviews" / "r.md")
        run_dir = Path(d["run_dir"])
        self.assertEqual(run_dir.parent, self.runs() / "task-x" / "reviews" / "dispatch")
        self.assertRegex(run_dir.name, r"^\d{4}-review$")
        self.assertEqual(entries(self.runs()), {"task-x"})

    def test_report_outside_runs_stays_flat(self):  # T1.b
        self.example()
        d = self.dispatch_to("scout", self.report())
        run_dir = Path(d["run_dir"])
        self.assertEqual(run_dir.parent, self.runs())
        self.assertRegex(run_dir.name, r"^\d{8}-\d{4}-scout$")

    def test_record_nested_and_flat_run_dirs(self):  # T1.c
        self.example()
        report = self.runs() / "task-x" / "s.md"
        d = self.dispatch_to("scout", report)
        report.write_text("PASS\n")
        code, _, err = self.record(d["calls"][0], 0, env=T3)
        self.assertEqual(code, 0, err)
        rel = Path(d["run_dir"]).relative_to(self.root).as_posix()
        self.assertTrue(rel.startswith(".sstack/runs/task-x/dispatch/"), rel)
        line = json.loads((self.runs() / "index.jsonl").read_text().splitlines()[-1])
        self.assertEqual(line["run_dir"], rel)

        flat = self.dispatch_to("scout", self.report())
        self.report().parent.mkdir(exist_ok=True)
        self.report().write_text("PASS\n")
        code, _, err = self.record(flat["calls"][0], 0, env=T3)
        self.assertEqual(code, 0, err)

    def test_record_refuses_dirs_outside_runs(self):  # T1.c
        self.example()
        d = self.dispatch_to("scout", self.runs() / "task-x" / "s.md")
        (self.root / ".sstack/roles").mkdir(parents=True, exist_ok=True)
        for bad in ("/", str(self.root / ".sstack/roles")):
            code, _, err = self.run_main("record", "scout", "--report", str(self.runs() / "task-x" / "s.md"),
                                         "--member", "claude/haiku", "--exit", "0", "--run-dir", bad, env=T3)
            self.assertEqual(code, 1, f"{bad}: {err}")
            self.assertIn(".sstack/runs/", err)
        self.assertTrue(Path(d["run_dir"]).is_dir())

    def test_three_dispatches_one_top_level_folder(self):  # T1.d (DONE WHEN)
        self.example()
        task = self.runs() / "task-x"
        for i, role in enumerate(("scout", "scout", "review")):
            self.dispatch_to(role, task / f"r{i}.md")
        self.assertEqual(entries(self.runs()), {"task-x"})
        self.assertEqual(len(list((task / "dispatch").iterdir())), 3)

    def test_route_reports_the_nested_dir_and_creates_nothing(self):  # T1.d
        self.example()
        code, out, err = self.run_main("scout", "--brief", self.brief(), "--report",
                                       str(self.runs() / "task-x" / "s.md"), "--route", env=T3)
        self.assertEqual(code, 0, err)
        self.assertRegex(json.loads(out)["run_dir"], r"/\.sstack/runs/task-x/dispatch/\d{4}-scout$")
        self.assertFalse(self.runs().exists())

    def test_readonly_child_writing_inside_its_task_is_not_flagged(self):  # T1.i (R16)
        self.example()
        report = self.runs() / "task-x" / "s.md"
        d = self.dispatch_to("scout", report)
        report.write_text("PASS\n")
        self.write(self.runs(), "task-x/notes.md", "task scratch\n")
        self.write(self.runs(), "task-x/dispatch/0000-other/x.md", "another dispatch of this task\n")
        code, _, err = self.record(d["calls"][0], 0, env=T3)
        self.assertEqual(code, 0, err)
        line = json.loads((self.runs() / "index.jsonl").read_text().splitlines()[-1])
        self.assertEqual(line["readonly_warning"], [])


class ReflectHomeTests(ReflectDedupeTests):
    def test_reflect_writes_under_runs_reflect(self):  # T1.e
        self.setup_agent("NONE\nPASS")
        t = self.root / "t.jsonl"; t.write_text('{"n":1}\n')
        self.hook(t)
        runs = self.root / ".sstack/runs"
        [report] = runs.glob("reflect/*/scout.report.md")
        self.assertIn("NONE", report.read_text())
        self.assertEqual(json.loads((runs / "reflect/state.json").read_text()), {"s1": 1})
        self.assertFalse([p for p in runs.iterdir() if p.name.startswith("reflect-")])
        self.assertTrue(entries(runs) <= {"reflect", "index.jsonl"}, entries(runs))

    def test_old_state_file_is_read_once(self):  # T1.e
        self.setup_agent("NONE\nPASS")
        old = self.write(self.root, ".sstack/runs/reflect-state.json", '{"s1": 1}')
        t = self.root / "t.jsonl"; t.write_text('{"n":1}\n')
        self.hook(t)
        self.assertEqual(self.briefs(), [])  # the old offset said line 1 was already read
        self.assertTrue(old.exists() or (self.root / ".sstack/runs/reflect/state.json").exists())


class SmokeHomeTests(DoctorBase):
    glob_cfg = SmokeTests.glob_cfg

    def test_smoke_runs_under_runs_doctor_and_cleans_up(self):  # T1.f
        self.glob_cfg(roles())
        code, out, err = self.doctor("--smoke")
        self.assertEqual(code, 0, out + err)
        runs = self.root / ".sstack/runs"
        self.assertEqual(entries(runs), {"index.jsonl"})
        reports = [json.loads(l)["report"] for l in self.index()]
        self.assertTrue(reports)
        for r in reports:
            self.assertRegex(r, r"^\.sstack/runs/doctor/smoke-\d{8}-\d{4}(-\d+)?/")

    def test_check_refuses_to_delete_outside_its_smoke_dir(self):  # T1.f
        victim = self.home / "victim"
        victim.mkdir()
        (victim / "keep.txt").write_text("x")
        d = self.root / ".sstack/runs/doctor/smoke-20260101-0000"
        d.mkdir(parents=True)
        (d / "smoke.json").write_text(json.dumps({"token": "t", "baseline": D.snapshot(self.root), "roles": {},
                                                  "run_dirs": [str(victim)], "errors": []}))
        code, out, _ = self.doctor("--smoke", "--check", str(d))
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL cleanup", out)
        self.assertTrue((victim / "keep.txt").exists())


class PruneTests(DoctorBase):
    OLD = time.time() - 30 * 86400

    def run_folder(self, rel, files, old=True):
        runs = self.root / ".sstack/runs"
        for name, text in files.items():
            p = self.write(runs, f"{rel}/{name}", text)
            if old:
                os.utime(p, (self.OLD, self.OLD))
        return runs / rel

    def setUp(self):
        super().setUp()
        self.done = self.run_folder("old-done", {"progress.md": "step 1\ndone: https://example.test/pr/1\n"})
        self.open = self.run_folder("old-open", {"progress.md": "step 1\nstep 2\n"})
        self.young = self.run_folder("old-young", {"progress.md": "step 1\ndone: merged\n"})
        self.write(self.young, "dispatch/0000-scout/run.json", "{}")  # a fresh file keeps the task alive
        self.legacy = self.run_folder("20200101-0000-scout", {"run.json": "{}"})
        self.run_folder("reflect/20200101-000000", {"scout.report.md": "x"})
        self.run_folder("doctor/smoke-20200101-0000", {"smoke.json": "{}"})
        idx = self.write(self.root, ".sstack/runs/index.jsonl", "{}\n")
        os.utime(idx, (self.OLD, self.OLD))

    def test_lists_without_yes_and_deletes_nothing(self):  # T1.g
        code, out, err = self.doctor("--prune-runs", "14")
        self.assertEqual(code, 0, out + err)
        self.assertIn(".sstack/runs/old-done", out)
        self.assertIn(".sstack/runs/20200101-0000-scout", out)
        for kept in ("old-open", "old-young", "reflect", "doctor", "index.jsonl"):
            self.assertNotRegex(out, rf"\.sstack/runs/{re.escape(kept)}(\s|/|$)")
        self.assertTrue(self.done.exists() and self.legacy.exists())

    def test_yes_deletes_only_finished_old_runs(self):  # T1.g
        code, out, err = self.doctor("--prune-runs", "14", "--yes")
        self.assertEqual(code, 0, out + err)
        runs = self.root / ".sstack/runs"
        self.assertEqual(entries(runs), {"old-open", "old-young", "reflect", "doctor", "index.jsonl"})


class RunsApiTests(ServerTests):
    def line(self, run_dir, ts, role):
        return json.dumps({"ts": ts, "role": role, "task": "t", "member": "claude/opus", "harness": "claude",
                           "model": "opus", "exit": 0, "secs": 1, "run_dir": run_dir, "report": f"{run_dir}/r.md",
                           "ade": None, "readonly_warning": []})

    def test_runs_are_grouped_by_task(self):  # T1.h
        lines = [self.line(".sstack/runs/task-x/dispatch/1200-scout", "2026-11-10T12:00:00", "scout"),
                 self.line(".sstack/runs/20261110-1100-implement", "2026-11-10T11:00:00", "implement"),
                 self.line(".sstack/runs/task-x/dispatch/1201-review", "2026-11-10T12:01:00", "review")]
        self.write(self.root, ".sstack/runs/index.jsonl", "\n".join(lines) + "\n")
        runs = self.get(f"/api/runs?repo={self.root}")["runs"]
        self.assertEqual([r["task"] for r in runs],
                         [".sstack/runs/task-x", ".sstack/runs/20261110-1100-implement"])
        self.assertEqual({c["run_dir"] for c in runs[0]["children"]},
                         {".sstack/runs/task-x/dispatch/1200-scout", ".sstack/runs/task-x/dispatch/1201-review"})
        self.assertEqual([c["run_dir"] for c in runs[1]["children"]], [".sstack/runs/20261110-1100-implement"])


def load_tests(loader, tests, pattern):
    """Only this file's tests: the base classes come from other test modules and keep their own."""
    suite = unittest.TestSuite()
    for cls in (NestedDispatchTests, ReflectHomeTests, SmokeHomeTests, PruneTests, RunsApiTests):
        for name in sorted(cls.__dict__):
            if name.startswith("test_"):
                suite.addTest(cls(name))
    return suite
