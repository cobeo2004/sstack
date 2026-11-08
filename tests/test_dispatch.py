import json, os, sys, io, time, contextlib
from pathlib import Path
from unittest import mock

from helpers import TempEnv, REPO
import sstack_dispatch as D

FAKE = f'[harness.fake]\nheadless = ["{sys.executable}", "{REPO}/tests/fakes/fake_agent.py", "{{model}}"]\n' \
       f'headless_readonly = ["{sys.executable}", "{REPO}/tests/fakes/fake_agent.py", "{{model}}"]\n'
NO_T3 = {k: v for k, v in os.environ.items() if not k.startswith("T3CODE")}


class DispatchTests(TempEnv):
    def run_main(self, *args, env=None):
        out, err = io.StringIO(), io.StringIO()
        e = dict(NO_T3, HOME=str(self.home), **(env or {}))
        with mock.patch.dict(os.environ, e, clear=True), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            old = os.getcwd(); os.chdir(self.root)
            try:
                code = D.main(list(args))
            finally:
                os.chdir(old)
        return code, out.getvalue(), err.getvalue()

    def brief(self, text="do the thing"):
        p = self.root / "b.md"; p.write_text(text); return str(p)

    def report(self):
        return self.root / "out" / "r.md"

    def example(self):
        self.glob_cfg((REPO / "config.example.toml").read_text())

    def test_fill_drops_unset_flag(self):
        self.assertEqual(D.fill(["pi", "--model", "{model}", "--thinking", "{effort}"],
                                {"model": "m", "effort": None}), ["pi", "--model", "m"])

    def test_dry_run_default_implement(self):
        self.example()
        code, out, _ = self.run_main("implement", "--brief", self.brief(), "--report", str(self.report()), "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("headless: pi -p --no-session --model opencode-go/deepseek-v4.1-flash --thinking high", out)
        self.assertFalse(self.report().exists())

    def test_dry_run_in_t3(self):
        self.example()
        code, out, _ = self.run_main("implement", "--brief", self.brief(), "--report", str(self.report()),
                                     "--dry-run", env={"T3CODE_THREAD_ID": "x", "T3CODE_CLI_PATH": "/t3"})
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("thread: /t3 thread start"), out)
        self.assertIn("--provider pi", out)
        self.assertIn("effort dropped", out)

    def test_readonly_role_never_thread(self):
        self.example()
        code, out, _ = self.run_main("review", "--brief", self.brief(), "--report", str(self.report()),
                                     "--dry-run", env={"T3CODE_THREAD_ID": "x"})
        self.assertEqual(code, 0)
        self.assertNotIn("thread:", out)
        self.assertIn("headless: codex exec --sandbox read-only", out)

    def test_readonly_without_readonly_cmd_refused(self):
        self.example()
        self.repo_cfg('[role.scout]\nharness="cursor"\nmodel="x"\n')
        code, _, err = self.run_main("scout", "--brief", self.brief(), "--report", str(self.report()), "--dry-run")
        self.assertEqual(code, 1)
        self.assertIn("headless_readonly", err)

    def test_real_run_ok(self):
        self.glob_cfg(FAKE + '[role.implement]\nharness="fake"\nmodel="echo"\n')
        code, _, _ = self.run_main("implement", "--brief", self.brief("hello brief"), "--report", str(self.report()))
        self.assertEqual(code, 0)
        text = self.report().read_text()
        self.assertIn("REPORT", text); self.assertIn("hello brief", text)
        lines = (self.root / ".sstack/runs/index.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual(rec["exit"], 0)
        self.assertEqual(set(rec), {"ts", "task", "role", "harness", "model", "transport", "exit", "secs", "report"})

    def test_empty_report_is_failure(self):
        self.glob_cfg(FAKE + '[role.implement]\nharness="fake"\nmodel="empty"\n')
        self.assertEqual(self.run_main("implement", "--brief", self.brief(), "--report", str(self.report()))[0], 1)

    def test_child_failure(self):
        self.glob_cfg(FAKE + '[role.implement]\nharness="fake"\nmodel="fail"\n')
        self.assertEqual(self.run_main("implement", "--brief", self.brief(), "--report", str(self.report()))[0], 1)

    def test_timeout_kills_process_group(self):
        self.glob_cfg(FAKE + '[transport]\ntimeout_min=0.05\n[role.implement]\nharness="fake"\nmodel="sleep"\n')
        t = time.monotonic()
        code, _, _ = self.run_main("implement", "--brief", self.brief(), "--report", str(self.report()))
        self.assertEqual(code, 2)
        self.assertLess(time.monotonic() - t, 8)
        pgid = int(self.report().read_text().split()[1])
        for _ in range(20):  # grandchild reaping by init is async
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            self.fail("process group still alive")

    def test_unconfigured_role_exit_3(self):
        self.example()
        code, out, _ = self.run_main("investigate", "--brief", self.brief(), "--report", str(self.report()))
        self.assertEqual((code, out.strip()), (3, "local"))

    def test_repo_harness_local_exit_3(self):
        self.glob_cfg(FAKE + '[role.implement]\nharness="fake"\nmodel="echo"\n')
        self.repo_cfg('[role.implement]\nharness="local"\n')
        self.assertEqual(self.run_main("implement", "--brief", self.brief(), "--report", str(self.report()))[0], 3)

    def test_panel_partial_failure(self):
        self.glob_cfg(FAKE + '[role.review]\npanel=[{harness="fake",model="echo"},{harness="fake",model="fail"}]\n')
        code, _, _ = self.run_main("review", "--brief", self.brief(), "--report", str(self.report()))
        self.assertEqual(code, 0)
        index = self.report().read_text()
        self.assertIn("fake/echo: exit 0", index)
        self.assertIn("fake/fail: exit 1", index)
        self.assertTrue((self.root / "out/r.fake-echo.md").exists())
        self.assertFalse((self.root / "out/r.fake-fail.md").exists())

    def test_child_env_marks_reflect(self):
        self.glob_cfg(FAKE + '[role.implement]\nharness="fake"\nmodel="env"\n')
        code, _, _ = self.run_main("implement", "--brief", self.brief(), "--report", str(self.report()))
        self.assertEqual(code, 0)
        self.assertIn("SSTACK_REFLECT=1", self.report().read_text())

    def test_readonly_child_edit_is_flagged(self):
        self.glob_cfg(FAKE + '[role.scout]\nharness="fake"\nmodel="dirty"\n')
        code, _, _ = self.run_main("scout", "--brief", self.brief(), "--report", str(self.report()))
        self.assertEqual(code, 0)
        self.assertIn("read-only role changed the working tree", self.report().read_text())
