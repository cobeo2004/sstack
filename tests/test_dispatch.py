import json, os, sys, io, time, contextlib
from pathlib import Path
from unittest import mock

from helpers import TempEnv, REPO
from test_contracts import INDEX_KEYS
import sstack_dispatch as D

FAKE = f'[harness.fake]\nheadless = ["{sys.executable}", "{REPO}/tests/fakes/fake_agent.py", "{{model}}"]\n' \
       f'headless_readonly = ["{sys.executable}", "{REPO}/tests/fakes/fake_agent.py", "{{model}}"]\n'
# no ADE markers from the session running the tests
NO_T3 = {k: v for k, v in os.environ.items()
         if not k.startswith(("T3CODE", "SSTACK_", "ORCA_", "CONDUCTOR_", "FAKE_"))}


class DispatchBase(TempEnv):
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


class DispatchTests(DispatchBase):
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
                                     "--dry-run", env={"T3CODE_THREAD_ID": "x"})
        self.assertEqual(code, 0)
        self.assertIn("ade: t3 (env T3CODE_THREAD_ID)", out)
        self.assertIn('tool delegate_task: {', out)
        self.assertIn('"providerInstanceId": "pi"', out)
        self.assertIn('"thinking": "high"', out)

    def test_via_headless_in_t3(self):
        self.example()
        code, out, _ = self.run_main("review", "--brief", self.brief(), "--report", str(self.report()),
                                     "--dry-run", "--via", "headless", env={"T3CODE_THREAD_ID": "x"})
        self.assertEqual(code, 0)
        self.assertNotIn("tool ", out)
        self.assertIn("headless: codex exec --sandbox read-only", out)

    def test_readonly_without_readonly_cmd_refused(self):
        self.example()
        # the example config gives cursor a plan-mode read-only command; take it away again
        self.repo_cfg('[harness.cursor]\nheadless=["cursor-agent"]\n'
                      '[role.scout]\nharness="cursor"\nmodel="x"\n')
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
        self.assertEqual(set(rec), INDEX_KEYS)
        self.assertEqual((rec["ade"], rec["via"], rec["readonly_warning"]), (None, "headless", []))
        run = json.loads((self.root / rec["run_dir"] / "run.json").read_text())
        self.assertEqual((run["members"], run["readonly"], run["panel_report"]), (["fake/echo"], False, None))

    def test_empty_report_is_failure(self):
        self.glob_cfg(FAKE + '[role.implement]\nharness="fake"\nmodel="empty"\n')
        self.assertEqual(self.run_main("implement", "--brief", self.brief(), "--report", str(self.report()))[0], 1)

    def test_child_failure(self):
        self.glob_cfg(FAKE + '[role.implement]\nharness="fake"\nmodel="fail"\n')
        self.assertEqual(self.run_main("implement", "--brief", self.brief(), "--report", str(self.report()))[0], 1)

    def test_timeout_kills_process_group(self):
        self.glob_cfg(FAKE + '[dispatch]\ntimeout_min=0.05\n[role.implement]\nharness="fake"\nmodel="sleep"\n')
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
        code, _, _ = self.run_main("review", "--brief", self.brief(), "--report", str(self.report()), "--panel")
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


FIXTURES = REPO / "tests" / "fixtures"
FAKES = REPO / "tests" / "fakes"
T3 = {"T3CODE_THREAD_ID": "x"}
PANEL_OK = __import__("re").compile(r": exit 0 → (.+)$", __import__("re").M)  # bin/sstack-reflect-hook:21


class FakeCliBase(DispatchBase):
    """Fake t3 / harness / orca / conductor CLIs first on PATH; every call lands in self.calls."""

    def setUp(self):
        super().setUp()
        self.calls = self.root.parent / "calls.log"

    def run_main(self, *args, env=None):
        e = {"PATH": f"{FAKES}:{os.environ['PATH']}", "FAKE_CALLS_LOG": str(self.calls), **(env or {})}
        return super().run_main(*args, env=e)

    def log(self) -> str:
        return self.calls.read_text() if self.calls.exists() else ""

    def dispatch(self, role, *extra, env=None):
        return self.run_main(role, "--brief", self.brief(), "--report", str(self.report()), *extra, env=env)

    def normalise(self, out: str) -> dict:
        d = json.loads(out)
        run_dir, rep = d["run_dir"], str(self.report())
        for real, ph in ((run_dir, "<RUN_DIR>"), (str(self.root / "b.md"), "<BRIEF>"), (rep, "<REPORT>"),
                         (rep[:-3], "<REPORT_BASE>")):
            out = out.replace(real, ph)
        return json.loads(out)

    def record(self, call: dict, code: int, env=None):
        import shlex
        argv = shlex.split(call["record"].replace("{exit}", str(code)))
        self.assertEqual(argv[:2], ["sstack-dispatch", "record"])
        return self.run_main(*argv[1:], env=env)


class ToolPayloadTests(FakeCliBase):
    """Inside T3, plain dispatch starts nothing and prints the delegate_task payload (exit 4)."""

    def check_payload(self, role, fixture, *extra):
        self.example()
        code, out, err = self.dispatch(role, *extra, env=T3)
        self.assertEqual(code, 4, err)
        want = json.loads((FIXTURES / "payloads" / fixture).read_text())
        self.assertEqual(self.normalise(out), want)
        self.assertEqual(self.log(), "")  # no harness CLI, no t3 thread
        return json.loads(out)

    def test_scout_payload(self):
        d = self.check_payload("scout", "t3-scout.json")
        run_dir = Path(d["run_dir"])
        self.assertEqual(run_dir.parent, self.root / ".sstack/runs")
        self.assertRegex(run_dir.name, r"^\d{8}-\d{4}-scout$")
        run = json.loads((run_dir / "run.json").read_text())
        self.assertEqual((run["members"], run["readonly"], run["panel_report"], run["report_base"]),
                         (["claude/haiku"], True, None, "out/r"))
        self.assertEqual(set(json.loads((run_dir / "baseline.json").read_text())), {"head", "status", "files", "index"})
        self.assertFalse((self.root / ".sstack/runs/index.jsonl").exists())  # record writes it

    def test_review_panel_payload(self):
        d = self.check_payload("review", "t3-review-panel.json", "--panel")
        run = json.loads((Path(d["run_dir"]) / "run.json").read_text())
        self.assertEqual(run["panel_report"], "out/r.md")

    def test_implement_payload_unmapped_model_note(self):
        d = self.check_payload("implement", "t3-implement.json")
        self.assertFalse((Path(d["run_dir"]) / "baseline.json").exists())  # write role: no baseline

    def test_route_creates_nothing(self):
        self.example()
        code, out, err = self.dispatch("scout", "--route", env=T3)
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual(d["calls"][0]["tool"], "delegate_task")
        self.assertRegex(d["run_dir"], r"/\.sstack/runs/\d{8}-\d{4}-scout$")
        self.assertFalse((self.root / ".sstack").exists())

    def test_ade_cursor_tool_readonly_arg(self):
        self.example()
        code, out, err = self.dispatch("scout", env={"SSTACK_ADE": "cursor"})
        self.assertEqual(code, 4, err)
        c = json.loads(out)["calls"][0]
        self.assertEqual((c["tool"], c["args"]["readonly"], c["args"]["model"]), ("Task", True, "haiku"))


class RecordTests(FakeCliBase):
    def git(self, *a):
        __import__("subprocess").run(["git", "-C", str(self.root), *a], check=True, capture_output=True)

    def index(self) -> list[dict]:
        return [json.loads(l) for l in (self.root / ".sstack/runs/index.jsonl").read_text().splitlines()]

    def test_record_writes_index_line(self):
        self.example()
        _, out, _ = self.dispatch("scout", env=T3)
        call = json.loads(out)["calls"][0]
        self.report().parent.mkdir(exist_ok=True)
        self.report().write_text("# scout\nPASS\n")
        code, _, err = self.record(call, 0, env=T3)
        self.assertEqual(code, 0, err)
        [rec] = self.index()
        self.assertEqual(set(rec), INDEX_KEYS)
        self.assertEqual((rec["ade"], rec["via"], rec["role"], rec["harness"], rec["model"], rec["exit"]),
                         ("t3", "auto", "scout", "claude", "haiku", 0))
        self.assertEqual((rec["report"], rec["readonly_warning"]), ("out/r.md", []))
        self.assertTrue(rec["run_dir"].startswith(".sstack/runs/"))
        self.assertNotIn("WARNING", self.report().read_text())

    def test_record_flags_tree_change(self):
        self.example()
        (self.root / "a.txt").write_text("one\n")
        self.git("add", "a.txt"); self.git("commit", "-qm", "a")
        (self.root / "a.txt").write_text("dirty before\n")  # dirty at baseline: compared by content
        (self.root / "same.txt").write_text("untouched\n")
        _, out, _ = self.dispatch("scout", env=T3)
        (self.root / "a.txt").write_text("dirty after\n")
        (self.root / "scratch.txt").write_text("x\n")
        self.report().parent.mkdir(exist_ok=True)
        self.report().write_text("PASS\n")
        self.record(json.loads(out)["calls"][0], 0, env=T3)
        [rec] = self.index()
        self.assertEqual(rec["readonly_warning"], ["a.txt", "scratch.txt"])
        self.assertIn("WARNING: read-only role changed the working tree:\na.txt\nscratch.txt\n",
                      self.report().read_text())

    def test_record_failure_escalates_one_tier(self):
        self.example()  # implement = tier cheap (pi); next up: tier.standard (claude/sonnet)
        _, out, _ = self.dispatch("implement", env=T3)
        call = json.loads(out)["calls"][0]
        self.report().parent.mkdir(exist_ok=True)
        self.report().write_text("half done\n")
        code, out2, err = self.record(call, 1, env=T3)
        self.assertEqual(code, 4, err)
        d = json.loads(out2)
        [c] = d["calls"]
        self.assertEqual((c["member"], c["args"]["target"]["model"], c["args"]["isolation"]),
                         ("claude/sonnet", "claude-sonnet-5-5", "worktree"))
        self.assertIn("escalating once to tier.standard", err)
        self.assertTrue((self.root / "out/r.failed.md").exists())
        brief = Path(d["run_dir"]) / "brief.escalated.md"
        self.assertIn(str(brief), c["args"]["task"])
        self.assertIn("do the thing", brief.read_text())
        self.assertIn("a previous attempt on a cheaper model failed", brief.read_text())
        self.assertEqual(json.loads((Path(d["run_dir"]) / "run.json").read_text())["members"], ["claude/sonnet"])
        code, out3, _ = self.record(c, 1, env=T3)  # once only
        self.assertEqual((code, out3), (1, ""))
        self.assertEqual([(r["model"], r["exit"]) for r in self.index()], [("opencode-go/deepseek-v4.1-flash", 1),
                                                                            ("sonnet", 1)])

    def test_record_failure_without_auto_escalate(self):
        self.example()
        self.write(self.root, ".sstack/config.toml", "[rules]\nauto_escalate = false\n")
        _, out, _ = self.dispatch("implement", env=T3)
        code, out2, _ = self.record(json.loads(out)["calls"][0], 1, env=T3)
        self.assertEqual((code, out2), (1, ""))

    def test_last_panel_record_writes_index(self):
        self.example()
        _, out, _ = self.dispatch("review", "--panel", env=T3)
        codex, claude = json.loads(out)["calls"]
        self.report().parent.mkdir(exist_ok=True)
        Path(self.root / "out/r.codex-gpt-6.1-sol.md").write_text("# review\nPASS\n")
        self.record(codex, 0, env=T3)
        self.assertFalse(self.report().exists())  # not every member recorded yet
        code, _, _ = self.record(claude, 1, env=T3)
        self.assertEqual(code, 0)  # one member reported
        panel = self.report().read_text()
        self.assertEqual(panel, "# review panel\n\n- codex/gpt-6.1-sol: exit 0 → out/r.codex-gpt-6.1-sol.md\n"
                                "- claude/opus: exit 1 → gap (no report)\n")
        self.assertEqual(PANEL_OK.findall(panel), ["out/r.codex-gpt-6.1-sol.md"])


class ViaTests(FakeCliBase):
    def test_via_headless_flag_in_t3_runs_headless(self):
        self.example()
        code, _, err = self.dispatch("scout", "--via", "headless", env=T3)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.report().read_text(), "REPORT claude\n")
        self.assertIn("claude -p --model haiku --permission-mode plan", self.log())

    def test_config_via_headless(self):
        self.example()
        self.write(self.root, ".sstack/config.toml", '[dispatch]\nvia = "headless"\n')
        self.assertEqual(self.dispatch("scout", env=T3)[0], 0)
        self.assertIn("claude -p", self.log())

    def test_via_local_exit_3(self):
        self.example()
        code, out, _ = self.dispatch("scout", "--via", "local", env=T3)
        self.assertEqual((code, out.strip(), self.log()), (3, "local", ""))

    def test_ade_cli_starts_t3_thread(self):
        self.example()
        code, _, err = self.dispatch("implement", "--via", "ade-cli",
                                     env={**T3, "T3CODE_CLI_PATH": str(FAKES / "t3")})
        self.assertEqual(code, 0, err)
        self.assertEqual(self.report().read_text(), "REPORT t3\n")
        self.assertIn("t3 thread start --provider pi --model opencode-go/deepseek-v4.1-flash --title "
                      "'sstack implement' --wait . -", self.log())
        [rec] = [json.loads(l) for l in (self.root / ".sstack/runs/index.jsonl").read_text().splitlines()]
        self.assertEqual((rec["ade"], rec["via"]), ("t3", "ade-cli"))

    def test_ade_cli_without_ade_is_error(self):
        self.example()
        code, _, err = self.dispatch("implement", "--via", "ade-cli")
        self.assertEqual(code, 1)
        self.assertIn("ade-cli", err)

    def test_sstack_ade_none_in_t3_is_headless(self):
        self.example()
        code, _, _ = self.dispatch("scout", env={**T3, "SSTACK_ADE": "none"})
        self.assertEqual(code, 0)
        self.assertIn("claude -p", self.log())

    def test_config_ade_forces_orca(self):
        self.example()
        self.write(self.root, ".sstack/config.toml", 'ade = "orca"\n')  # no ORCA_* env set
        code, out, _ = self.dispatch("scout", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("ade: orca (ade = orca)", out)
        self.assertIn("orca.hook delegate (claude/haiku)", out)

    def test_unknown_forced_ade_is_error(self):
        self.example()
        code, _, err = self.dispatch("scout", env={"SSTACK_ADE": "nope"})
        self.assertEqual(code, 1)
        self.assertIn("no ades/nope.toml", err)


class AnswerKeyShell(TempEnv):
    """answer-key §B2: the real script, SSTACK_HOME = the example-equivalent fixture, fake CLIs on PATH."""

    def test_plain_dispatch_in_t3_exits_4(self):
        import subprocess
        calls = self.root.parent / "calls.log"
        env = {**NO_T3, "HOME": str(self.home), "SSTACK_HOME": str(FIXTURES / "config/example-equivalent/home"),
               "T3CODE_THREAD_ID": "x", "PATH": f"{FAKES}:{os.environ['PATH']}", "FAKE_CALLS_LOG": str(calls)}
        r = subprocess.run([str(REPO / "bin/sstack-dispatch"), "scout", "--brief", "b.md", "--report", "r.md"],
                           cwd=self.root, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 4, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual((d["calls"][0]["tool"], d["calls"][0]["args"]["target"]["model"]),
                         ("delegate_task", "claude-haiku-5-5"))
        self.assertFalse(calls.exists())


SUFFIX = " If you cannot write files, return the full report as your final message."


class FixB2Tests(FakeCliBase):
    """Review round 1 (fix-B2): kind whitelist, -z status, exclusions, record lock, no-model members."""

    def git(self, *a):
        __import__("subprocess").run(["git", "-C", str(self.root), *a], check=True, capture_output=True)

    def index(self) -> list[dict]:
        return [json.loads(l) for l in (self.root / ".sstack/runs/index.jsonl").read_text().splitlines()]

    def t3_kind(self, kind):
        text = (REPO / "defaults/ades/t3.toml").read_text().replace('kind = "tool"\nname', f'kind = "{kind}"\nname')
        self.write(self.home, ".sstack/ades/t3.toml", text)

    def test_bad_delegate_kind_is_config_error(self):
        self.example()
        env = {**T3, "T3CODE_CLI_PATH": str(FAKES / "t3")}
        for kind in ("Tool", "cli", "ade-cli", "headless", ""):
            with self.subTest(kind=kind):
                self.t3_kind(kind)
                for extra in ((), ("--dry-run",)):
                    code, _, err = self.dispatch("scout", *extra, env=env)
                    self.assertEqual(code, 1, err)
                    self.assertIn("delegate.kind", err)
                self.assertEqual(self.run_main("ade", env=env)[0], 1)
                self.assertEqual(self.log(), "")

    def test_t3_auto_never_execs_t3_cli(self):
        """Invariant: in T3 with via=auto, no delegate.kind makes dispatch run the t3 CLI."""
        self.example()
        env = {**T3, "T3CODE_CLI_PATH": str(FAKES / "t3")}
        for kind in ("tool", "hook", "none", "Tool", "cli", "ade-cli"):
            with self.subTest(kind=kind):
                self.t3_kind(kind)
                self.dispatch("scout", env=env)
                self.assertFalse([l for l in self.log().splitlines() if l.startswith("t3 ")], self.log())

    def test_status_z_space_and_unicode_names(self):
        self.example()
        for n in ("a b.txt", "tĩnh.txt"):
            (self.root / n).write_text("one\n")
        self.git("add", "-A"); self.git("commit", "-qm", "a")
        for n in ("a b.txt", "tĩnh.txt"):
            (self.root / n).write_text("dirty before\n")
        _, out, _ = self.dispatch("scout", env=T3)
        for n in ("a b.txt", "tĩnh.txt"):
            (self.root / n).write_text("dirty after\n")
        self.report().parent.mkdir(exist_ok=True)
        self.report().write_text("PASS\n")
        self.record(json.loads(out)["calls"][0], 0, env=T3)
        self.assertEqual(self.index()[0]["readonly_warning"], ["a b.txt", "tĩnh.txt"])

    def test_escalation_artifacts_and_other_runs_not_flagged(self):
        self.example()
        _, out, _ = self.dispatch("scout", env=T3)
        self.report().parent.mkdir(exist_ok=True)
        self.report().write_text("half\n")
        Path(str(self.report()) + ".err").write_text("boom\n")
        self.write(self.root, ".sstack/runs/20990101-0000-other/x.md", "another run\n")
        code, out2, err = self.record(json.loads(out)["calls"][0], 1, env=T3)
        self.assertEqual(code, 4, err)
        self.report().write_text("PASS\n")
        code, _, err = self.record(json.loads(out2)["calls"][0], 0, env=T3)
        self.assertEqual(code, 0, err)
        self.assertEqual([r["readonly_warning"] for r in self.index()], [[], []])

    def test_index_truncation_is_flagged_append_is_not(self):
        self.example()
        idx = self.write(self.root, ".sstack/runs/index.jsonl", '{"old": 1}\n')
        _, out, _ = self.dispatch("scout", env=T3)
        self.report().parent.mkdir(exist_ok=True)
        self.report().write_text("PASS\n")
        idx.write_text('{"other": 2}\n')  # replaced, not appended
        self.record(json.loads(out)["calls"][0], 0, env=T3)
        self.assertEqual(self.index()[-1]["readonly_warning"], [".sstack/runs/index.jsonl"])

    def test_record_holds_run_lock(self):
        import fcntl, subprocess
        self.example()
        _, out, _ = self.dispatch("scout", env=T3)
        call = json.loads(out)["calls"][0]
        self.report().parent.mkdir(exist_ok=True)
        self.report().write_text("PASS\n")
        argv = __import__("shlex").split(call["record"].replace("{exit}", "0"))
        env = {**NO_T3, "HOME": str(self.home), **T3}
        with open(Path(json.loads(out)["run_dir"]) / "run.lock", "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            p = subprocess.Popen([str(REPO / "bin/sstack-dispatch"), *argv[1:]], cwd=self.root, env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(1)
            self.assertIsNone(p.poll(), "record ran without the run lock")
        p.communicate(timeout=20)
        self.assertEqual(p.returncode, 0)

    def test_panel_index_written_once(self):
        self.example()
        _, out, _ = self.dispatch("review", "--panel", env=T3)
        codex, claude = json.loads(out)["calls"]
        self.report().parent.mkdir(exist_ok=True)
        self.record(codex, 1, env=T3)
        self.record(claude, 1, env=T3)
        self.report().write_text("edited by hand\n")
        self.record(claude, 1, env=T3)
        self.assertEqual(self.report().read_text(), "edited by hand\n")
        self.assertTrue(json.loads((Path(json.loads(out)["run_dir"]) / "run.json").read_text())["panel_written"])

    def test_record_rejects_unknown_member_and_shallow_run_dir(self):
        self.example()
        _, out, _ = self.dispatch("scout", env=T3)
        rd = json.loads(out)["run_dir"]
        code, _, err = self.run_main("record", "scout", "--report", str(self.report()), "--member", "pi/x",
                                     "--exit", "0", "--run-dir", rd, env=T3)
        self.assertEqual(code, 1)
        self.assertIn("not a member", err)
        code, _, err = self.run_main("record", "scout", "--report", str(self.report()), "--member", "claude/haiku",
                                     "--exit", "0", "--run-dir", "/", env=T3)
        self.assertEqual(code, 1)
        self.assertIn(".sstack/runs/", err)

    def test_no_model_member(self):
        self.example()
        self.write(self.home, ".sstack/roles/scout.toml", 'harness = "claude"\n')
        code, out, err = self.dispatch("scout", env=T3)
        self.assertEqual(code, 4, err)
        c = json.loads(out)["calls"][0]
        self.assertEqual(c["member"], "claude/default")
        self.assertNotIn("model", c["args"]["target"])
        self.assertIn("--member claude/default", c["record"])
        run = json.loads((Path(json.loads(out)["run_dir"]) / "run.json").read_text())
        self.assertEqual(run["members"], ["claude/default"])
        self.report().parent.mkdir(exist_ok=True)
        self.report().write_text("PASS\n")
        self.assertEqual(self.record(c, 0, env=T3)[0], 0)
        self.assertEqual(self.index()[0]["model"], "default")

    def test_task_text_absolute_paths_and_fallback(self):
        self.example()
        (self.root / "b.md").write_text("brief\n")
        code, out, err = self.run_main("scout", "--brief", "b.md", "--report", "out/r.md", env=T3)
        self.assertEqual(code, 4, err)
        task = json.loads(out)["calls"][0]["args"]["task"]
        self.assertEqual(task, f"Read the brief at {self.root / 'b.md'} and do exactly what it says. "
                               f"Write your report to {self.root / 'out/r.md'}.{SUFFIX}")
        run = json.loads((Path(json.loads(out)["run_dir"]) / "run.json").read_text())
        self.assertEqual(run["brief"], "b.md")  # repo-relative

    def test_escalation_note_under_worktree_isolation(self):
        self.example()
        _, out, _ = self.dispatch("implement", env=T3)
        code, out2, err = self.record(json.loads(out)["calls"][0], 1, env=T3)
        self.assertEqual(code, 4, err)
        brief = (Path(json.loads(out2)["run_dir"]) / "brief.escalated.md").read_text()
        self.assertNotIn("The working tree may hold its partial edits", brief)
        self.assertIn("worktree", brief)

    def test_panel_member_exception_keeps_others(self):
        self.glob_cfg(FAKE + '[role.review]\npanel=[{harness="fake",model="echo"},{harness="fake",model="boom"}]\n')
        real = D.run_member

        def run_member(argv, *a, **kw):
            if "boom" in argv:
                raise RuntimeError("kaboom")
            return real(argv, *a, **kw)

        with mock.patch.object(D, "run_member", run_member):
            code, _, err = self.run_main("review", "--brief", self.brief(), "--report", str(self.report()), "--panel")
        self.assertEqual(code, 0, err)
        self.assertIn("kaboom", err)
        self.assertEqual(sorted((r["model"], r["exit"]) for r in self.index()), [("boom", 1), ("echo", 0)])
        self.assertIn("fake/boom: exit 1", self.report().read_text())
