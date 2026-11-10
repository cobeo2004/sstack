"""ADE layer (docs/spec/ade.md): detection checks and hook lifecycles from tests/fixtures/ades/,
the `ade` subcommand, and the built-in orca/conductor hooks against fake CLIs."""
import json, os, shutil, time
from pathlib import Path

from helpers import TempEnv, FIXTURES, REPO
from test_dispatch import FakeCliBase, T3
import sstack_ade as A
import sstack_config as C

ADES = FIXTURES / "ades"
WHY_FORMAT = ("env ", "SSTACK_ADE=", "ade = ", "no adapter detected")  # whys that are sstack's own text


class DetectionChecks(TempEnv):
    def test_every_fixture_check(self):
        n = 0
        for case in sorted(ADES.iterdir()):
            want = json.loads((case / "expected.json").read_text())
            sstack_home = self.profile(self.home / case.name, case / "home" if (case / "home").is_dir() else None)
            os.environ["SSTACK_HOME"] = str(sstack_home)
            self.assertEqual([[a["name"], a["layer"]] for a in C.ades(None)], want["order"], case.name)
            for c in want.get("checks", []):
                with self.subTest(case=case.name, why=c["why"]):
                    a, why = A.active(None, {"ade": c["ade"]}, c["env"])
                    self.assertEqual(a and a["name"], c["active"])
                    if c["why"].startswith(WHY_FORMAT):
                        self.assertEqual(why, c["why"])
                    n += 1
        self.assertEqual(n, 9)  # t3: 4, cursor-off: 3, user-overrides-builtin: 2

    def test_auto_false_never_detected_but_forceable(self):
        self.profile(self.home / "s")
        self.write(self.home, "s/ades/x.toml", 'auto = false\n[detect]\nenv = ["X_SESSION"]\n[delegate]\nkind = "none"\n')
        os.environ["SSTACK_HOME"] = str(self.home / "s")
        self.assertEqual(A.active(None, {"ade": "auto"}, {"X_SESSION": "1"}), (None, "no adapter detected"))
        self.assertEqual(A.active(None, {"ade": "x"}, {})[0]["name"], "x")

    def test_hook_detect(self):
        self.profile(self.home / "s", ADES / "hook-async/home")
        os.environ["SSTACK_HOME"] = str(self.home / "s")
        a, why = A.active(None, {"ade": "auto"}, {"PATH": os.environ["PATH"]})
        self.assertEqual((a["name"], why), ("fake", "hook detect"))


class HookLifecycle(FakeCliBase):
    """Each hook fixture through a real scout dispatch (example config; headless = fake claude)."""

    def run_case(self, name, env=None):
        self.example()
        shutil.copytree(ADES / name / "home/ades", self.home / ".sstack/ades", dirs_exist_ok=True)
        want = json.loads((ADES / name / "expected.json").read_text())
        code, out, err = self.dispatch("scout", env=env)
        [run_dir] = [d for d in (self.root / ".sstack/runs").iterdir() if d.is_dir()]
        return want, code, err, run_dir / "hook.claude-haiku"

    def index(self):
        return [json.loads(l) for l in (self.root / ".sstack/runs/index.jsonl").read_text().splitlines()]

    def test_sync(self):
        want, code, err, _ = self.run_case("hook-sync")
        self.assertEqual(code, want["dispatch_exit"], err)
        self.assertEqual(self.report().read_text(), want["report"])
        self.assertEqual(self.log(), "")
        [rec] = self.index()
        self.assertEqual((rec["ade"], rec["via"], rec["exit"]), ("fake", "auto", 0))

    def test_async_polls_then_collects(self):
        want, code, err, state = self.run_case("hook-async")
        self.assertEqual(code, want["dispatch_exit"], err)
        self.assertEqual(self.report().read_text(), want["report"])
        self.assertEqual((state / "polls").read_text().strip(), str(len(want["wait"])))  # 10, 10, 0
        self.assertFalse((state / want["cancel_marker"]).exists())  # finished: never cancelled
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), [".git", ".sstack", "b.md", "out"])

    def test_timeout_cancels_exit_2(self):
        self.write(self.root, ".sstack/config.toml", "[dispatch]\ntimeout_min = 0.005\n")
        want, code, err, state = self.run_case("hook-timeout")
        self.assertEqual(code, want["dispatch_exit"], err)
        self.assertTrue((state / want["cancel_marker"]).is_file())
        self.assertEqual(self.index()[0]["exit"], 2)

    def test_empty_collect_exit_1(self):
        want, code, err, _ = self.run_case("hook-empty-collect")
        self.assertEqual(code, want["dispatch_exit"], err)

    def test_wait_fails_exit_1(self):
        want, code, err, _ = self.run_case("hook-wait-fails")
        self.assertEqual(code, want["dispatch_exit"], err)

    def check_headless(self, name, note, env=None):
        want, code, err, _ = self.run_case(name, env)
        self.assertEqual(want["falls_back_to"], "headless")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.report().read_text(), "REPORT claude\n")
        self.assertIn("claude -p --model haiku", self.log())
        self.assertIn(note, err)
        [rec] = self.index()
        self.assertEqual((rec["ade"], rec["via"]), (None, "headless"))

    def test_fails_falls_back_to_headless(self):
        self.check_headless("hook-fails", "hook delegate exit 1")

    def test_bad_json_falls_back_to_headless(self):
        self.check_headless("hook-bad-json", "no valid action")

    def test_missing_creds_headless_with_note(self):
        self.check_headless("hook-missing-creds", "note: FAKE_API_KEY not set; running headless")

    def test_with_creds_runs(self):
        want, code, err, _ = self.run_case("hook-missing-creds", env={"FAKE_API_KEY": "k"})
        self.assertEqual((code, self.report().read_text()), (0, "REPORT keyed\n"), err)


class AdeSubcommand(FakeCliBase):
    def ade(self, env=None):
        code, out, err = self.run_main("ade", env=env)
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_t3(self):
        self.assertEqual(self.ade(T3), {
            "name": "t3", "why": "env T3CODE_THREAD_ID", "layer": "home", "delegate": "tool delegate_task",
            "readonly": "instructed", "browser": "tool: preview_* tools (see t3.md)",
            "device": "tool: device_* tools (see t3.md)", "capture": "tool: preview_recording_* tools (see t3.md)",
            "note": str(self.home / ".sstack/ades/t3.md")})

    def test_none(self):
        d = self.ade()
        self.assertEqual(d, {"name": None, "why": "no adapter detected", "layer": None, "delegate": None,
                             "readonly": None, "browser": None, "device": None, "capture": None, "note": None})

    def test_conductor_capabilities_none(self):
        d = self.ade({"CONDUCTOR_SESSION_ID": "s"})
        self.assertEqual((d["name"], d["delegate"], d["browser"]), ("conductor", "hook", "none"))


class BuiltinHooks(FakeCliBase):
    """defaults/ades/{orca,conductor}.hook against tests/fakes/{orca,conductor}."""

    def test_orca_implement(self):
        self.example()
        code, _, err = self.dispatch("implement", env={"ORCA_AGENT_SESSION_ID": "s"})
        self.assertEqual(code, 0, err)
        self.assertEqual(self.report().read_text(), "REPORT orca\n")
        log = self.log()
        self.assertIn("orca orchestration task-create '--title=sstack implement' --prompt", log)
        self.assertIn("orca orchestration worker-start --task task-1 --worktree new-child --agent pi "
                      "--model opencode-go/deepseek-v4.1-flash", log)
        self.assertIn("orca orchestration check --task task-1 --wait", log)
        self.assertNotIn("\npi ", log)  # no headless child

    def test_orca_scout_current_worktree(self):
        self.example()
        self.assertEqual(self.dispatch("scout", env={"ORCA_AGENT_SESSION_ID": "s"})[0], 0)
        self.assertIn("--worktree current --agent claude --model haiku", self.log())

    def test_orca_check_fails(self):
        self.example()
        code, _, _ = self.dispatch("scout", env={"ORCA_AGENT_SESSION_ID": "s", "FAKE_ORCA_CHECK": "1"})
        self.assertEqual(code, 1)
        self.assertNotIn("task-cancel", self.log())

    def test_conductor_without_key_is_headless(self):
        self.example()
        code, _, err = self.dispatch("scout", env={"CONDUCTOR_SESSION_ID": "s"})
        self.assertEqual(code, 0, err)
        self.assertIn("note: CONDUCTOR_API_KEY not set; running headless", err)
        self.assertEqual(self.report().read_text(), "REPORT claude\n")
        self.assertNotIn("conductor ", self.log())

    def test_conductor_with_key(self):
        self.example()
        code, _, err = self.dispatch("scout", env={"CONDUCTOR_SESSION_ID": "s", "CONDUCTOR_API_KEY": "k"})
        self.assertEqual(code, 0, err)
        self.assertEqual(self.report().read_text(), "REPORT conductor\n")
        log = self.log()
        self.assertIn("conductor workspace create '--name=sstack scout' --agent claude --model haiku --json", log)
        self.assertIn("conductor message create --workspace ws-1 --plan --message", log)

    def test_conductor_failed_status(self):
        self.example()
        code, _, _ = self.dispatch("scout", env={"CONDUCTOR_SESSION_ID": "s", "CONDUCTOR_API_KEY": "k",
                                                 "FAKE_CONDUCTOR_STATUS": "error"})
        self.assertEqual(code, 1)


class HookDeadline(FakeCliBase):
    """fix-B2: one deadline across delegate → wait → collect; hook output validated; process groups killed."""

    def hook(self, body, poll_s=0, timeout_min=None):
        self.example()
        self.write(self.home, ".sstack/ades/fake.toml",
                   f'auto = true\n[detect]\nenv = ["FAKE_SESSION"]\n[delegate]\nkind = "hook"\npoll_s = {poll_s}\n')
        h = self.write(self.home, ".sstack/ades/fake.hook", '#!/bin/sh\nS="$SSTACK_HOOK_STATE"\ncase "$1" in\n'
                       + body + '\n  cancel) cat >/dev/null; touch "$S/cancelled" ;;\n  *) cat >/dev/null; exit 1 ;;\nesac\n')
        h.chmod(0o755)
        if timeout_min is not None:
            self.write(self.root, ".sstack/config.toml", f"[dispatch]\ntimeout_min = {timeout_min}\n")

    def go(self, env=None):
        t = time.monotonic()
        code, out, err = self.dispatch("scout", env={"FAKE_SESSION": "1", **(env or {})})
        [run_dir] = [d for d in (self.root / ".sstack/runs").iterdir() if d.is_dir()]
        return code, err, run_dir / "hook.claude-haiku", time.monotonic() - t

    def test_bad_delegate_output_runs_headless(self):
        self.hook('  delegate) cat >/dev/null; echo "$FAKE_OUT" ;;')
        for bad in ('{"action": "async"}', '{"action": "async", "id": [1]}', '{"action": "async", "id": true}',
                    '{"action": "run", "argv": [1, 2]}', '{"action": "run", "argv": "sh"}'):
            with self.subTest(out=bad):
                shutil.rmtree(self.root / ".sstack/runs", ignore_errors=True)
                code, err, _, _ = self.go({"FAKE_OUT": bad})
                self.assertEqual(code, 0, err)
                self.assertIn("running headless", err)
                self.assertEqual(self.report().read_text(), "REPORT claude\n")

    def test_delegate_hang_is_timeout_and_group_killed(self):
        self.hook('  delegate) cat >/dev/null; echo $$ > "$S/pgid"; sleep 3; sleep 3 ;;', timeout_min=0.005)
        code, err, state, secs = self.go()
        self.assertEqual(code, 2, err)
        self.assertLess(secs, 2.5)
        pgid = int((state / "pgid").read_text())
        for _ in range(20):
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            self.fail("hook process group still alive")

    def test_collect_hang_is_timeout_and_cancels(self):
        self.hook('  delegate) cat >/dev/null; echo \'{"action": "async", "id": "j"}\' ;;\n'
                  '  wait) cat >/dev/null; exit 0 ;;\n  collect) cat >/dev/null; sleep 3; echo late ;;', timeout_min=0.005)
        code, err, state, secs = self.go()
        self.assertEqual(code, 2, err)
        self.assertTrue((state / "cancelled").is_file())
        self.assertLess(secs, 2.5)

    def test_missing_wait_hook_is_failure_not_loop(self):
        self.hook('  delegate) cat >/dev/null; chmod -x "$0"; echo \'{"action": "async", "id": "j"}\' ;;',
                  timeout_min=0.01)
        self.go()
        rec = json.loads((self.root / ".sstack/runs/index.jsonl").read_text().splitlines()[0])
        self.assertEqual((rec["model"], rec["exit"]), ("haiku", 1))  # not 2: no polling to the deadline

    def test_sleeps_min_poll_remaining_before_cancel(self):
        self.hook('  delegate) cat >/dev/null; echo \'{"action": "async", "id": "j"}\' ;;\n'
                  '  wait) cat >/dev/null; exit 10 ;;', poll_s=100, timeout_min=0.01)
        code, err, state, secs = self.go()
        self.assertEqual(code, 2, err)
        self.assertTrue((state / "cancelled").is_file())
        self.assertGreater(secs, 0.5)  # ran to the deadline, not cancelled because poll_s > remaining
        self.assertLess(secs, 5)

    def test_title_option_value_cannot_be_a_flag(self):
        self.example()
        code, _, err = self.dispatch("scout", "--title=-x", env={"ORCA_AGENT_SESSION_ID": "s"})
        self.assertEqual(code, 0, err)
        self.assertIn("task-create --title=-x --prompt", self.log())


class RecheckB2(TempEnv):
    """B2 re-check (sonnet): process-group SIGKILL, worktree rename parse, index truncation when
    .sstack/runs/ is gitignored, tool adapter without a name."""

    def test_kill_group_kills_term_ignoring_grandchild(self):
        import signal, subprocess
        pidf = self.home / "pid"
        p = subprocess.Popen(["sh", "-c", f"(trap '' TERM; exec sleep 300) & echo $! > {pidf}; wait"],
                             start_new_session=True)
        for _ in range(50):
            if pidf.exists() and pidf.read_text().strip():
                break
            time.sleep(0.05)
        A.kill_group(p)
        pid = int(pidf.read_text())
        time.sleep(0.2)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_worktree_rename_entry(self):
        import sstack_dispatch as D
        self.assertEqual(D._entries(" R kept.txt\0gone.txt\0?? new.txt\0"),
                         {"kept.txt": " R", "new.txt": "??"})

    def test_index_truncation_seen_when_runs_ignored(self):
        import subprocess, sstack_dispatch as D
        root = self.root
        (root / ".gitignore").write_text(".sstack/runs/\n")
        idx = root / D.INDEX; idx.parent.mkdir(parents=True)
        idx.write_text('{"a":1}\n{"b":2}\n')
        base = D.snapshot(root)
        idx.write_text('{"a":1}\n{"b":2}\n{"c":3}\n')
        self.assertEqual(D.tree_changes(root, base, []), [])
        idx.write_text('{"x":1}\n')
        self.assertIn(D.INDEX, D.tree_changes(root, base, []))

    def test_tool_without_name_is_config_error(self):
        with self.assertRaises(C.ConfigError):
            A.kind({"name": "x", "toml": {"delegate": {"kind": "tool"}}})
