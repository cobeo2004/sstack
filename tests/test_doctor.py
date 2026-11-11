import json, os, subprocess, sys
from pathlib import Path

from helpers import TempEnv, REPO
from test_dispatch import NO_T3
import sstack_dispatch as D

DOCTOR = REPO / "bin" / "sstack-doctor"
FAKE = f'[harness.fake]\nheadless = ["{sys.executable}", "{REPO}/tests/fakes/fake_agent.py", "{{model}}"]\n' \
       f'headless_readonly = ["{sys.executable}", "{REPO}/tests/fakes/fake_agent.py", "{{model}}"]\n'


def roles(scout="canary", implement="canary", review="canary-review"):  # review ≠ implement (review_not_implementer)
    return (FAKE + f'[role.scout]\nharness="fake"\nmodel="{scout}"\n'
            f'[role.implement]\nharness="fake"\nmodel="{implement}"\n'
            f'[role.review]\nharness="fake"\nmodel="{review}"\n')


class DoctorBase(TempEnv):
    def setUp(self):
        super().setUp()
        (self.root / "a.txt").write_text("a\n")
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "init"], check=True)

    def doctor(self, *args, env=None):
        e = dict(NO_T3, HOME=str(self.home), **(env or {}))
        # `record` in payloads runs sstack-dispatch. PATH comes from os.environ now, not NO_T3's
        # import-time copy, so TempEnv's claude stub is on it (CI hosts have no claude).
        e["PATH"] = f"{REPO / 'bin'}:{(env or {}).get('PATH', os.environ['PATH'])}"
        r = subprocess.run([sys.executable, str(DOCTOR), *args], cwd=self.root, env=e, capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr

    def index(self):
        p = self.root / D.INDEX
        return p.read_text().splitlines() if p.exists() else []


    def assertCleaned(self):
        """Nothing left under .sstack/runs/ but the index."""
        self.assertEqual([p.name for p in (self.root / ".sstack" / "runs").iterdir()], ["index.jsonl"])


class StaticTests(DoctorBase):
    def test_all_pass(self):
        self.glob_cfg(roles())
        code, out, _ = self.doctor()
        self.assertEqual(code, 0, out)
        for c in ("config loads", "no legacy files", "roles resolve", "harness CLIs", "active ADE", "hooks executable"):
            self.assertIn(f"PASS {c}", out)
        self.assertIn("name None", out)

    def test_profile_first_drift_warns_then_passes_after_sync(self):
        self.glob_cfg(roles())
        code, out, _ = self.doctor()
        self.assertTrue(out.startswith("PASS profile: "), out)
        (self.home / ".sstack/harnesses/pi.toml").unlink()
        cfg = self.home / ".sstack/config.toml"
        cfg.write_text("".join(x for x in cfg.read_text().splitlines(keepends=True) if not x.startswith("stop_at")))
        code, out, _ = self.doctor()
        self.assertRegex(out, r"(?m)^WARN profile: drift: .*harnesses/pi\.toml.*overnight\.stop_at.*sstack-config sync")
        subprocess.run([sys.executable, str(REPO / "bin/sstack-config"), "sync"], env=dict(os.environ, HOME=str(self.home)),
                       check=True, capture_output=True)
        code, out, _ = self.doctor()
        self.assertRegex(out, r"(?m)^PASS profile: ")

    def test_no_profile_fails_with_the_fix(self):
        import shutil
        shutil.rmtree(self.home / ".sstack")
        code, out, _ = self.doctor()
        self.assertEqual(code, 1)
        self.assertRegex(out, r"(?m)^FAIL profile: no sstack profile at .*sstack-config sync")

    def test_roles_without_a_file_are_named(self):
        self.glob_cfg(roles())
        (self.home / ".sstack/roles/investigate.toml").unlink()
        code, out, _ = self.doctor()
        self.assertIn("investigate → local (no roles/investigate.toml)", out)
        self.assertNotIn("scout → local (no", out)

    def test_bad_toml(self):
        self.glob_cfg(roles())
        (self.home / ".sstack" / "roles" / "scout.toml").write_text("harness = \n")
        code, out, _ = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn("FAIL config loads", out)

    def test_legacy(self):
        (self.home / ".sstack").mkdir(exist_ok=True)
        (self.home / ".sstack" / "config.toml").write_text('[role.scout]\nharness = "claude"\n')
        code, out, _ = self.doctor()
        self.assertEqual(code, 1)
        self.assertRegex(out, r"FAIL no legacy files: .*sstack-config migrate")

    def test_unknown_harness(self):
        self.glob_cfg(roles() + '[role.plan]\nharness="nope"\n')
        code, out, _ = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn("FAIL roles resolve: unknown harness 'nope'", out)

    def test_missing_cli(self):
        self.glob_cfg(roles() + '[harness.ghost]\nheadless=["no-such-cli-xyz"]\nheadless_readonly=["no-such-cli-xyz"]\n'
                      '[role.plan]\nharness="ghost"\n')
        code, out, _ = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn("FAIL harness CLIs: not on PATH: ghost.headless: no-such-cli-xyz", out)

    def test_bad_forced_ade(self):
        self.glob_cfg(roles())
        code, out, _ = self.doctor(env={"SSTACK_ADE": "bogus"})
        self.assertEqual(code, 1)
        self.assertIn("FAIL active ADE: SSTACK_ADE=bogus", out)

    def test_hook_not_executable(self):
        self.glob_cfg(roles())
        ad = self.home / ".sstack" / "ades"
        ad.mkdir(exist_ok=True)
        (ad / "mine.toml").write_text("auto = false\n[delegate]\nkind = \"hook\"\n")
        (ad / "mine.hook").write_text("#!/bin/sh\n")
        code, out, _ = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn("FAIL hooks executable: not executable:", out)
        self.assertIn("mine.hook", out)


class SmokeTests(DoctorBase):
    def glob_cfg(self, text):
        """The template routes investigate and plan to claude; these tests fake scout, implement and
        review only, so a role the text leaves out has no file (local)."""
        p = DoctorBase.glob_cfg(self, text)
        for r in ("investigate", "plan"):
            if f"[role.{r}]" not in text:
                (self.home / ".sstack/roles" / f"{r}.toml").unlink()
        return p

    def test_headless_passes_and_cleans_up(self):
        self.glob_cfg(roles())
        code, out, err = self.doctor("--smoke")
        self.assertEqual(code, 0, out + err)
        for r in ("scout fake/canary", "implement fake/canary", "review fake/canary-review", "tree unchanged"):
            self.assertIn(f"PASS {r}", out)
        self.assertCleaned()
        lines = [json.loads(l) for l in self.index()]  # index stays append-only: lines kept, tagged
        self.assertEqual(len(lines), 3)
        self.assertEqual({l["task"] for l in lines}, {"sstack smoke"})

    def test_two_clean_smokes_pass(self):
        self.glob_cfg(roles())
        for _ in range(2):
            code, out, err = self.doctor("--smoke")
            self.assertEqual(code, 0, out + err)
        self.assertCleaned()
        self.assertEqual(len(self.index()), 6)

    def test_route_failure_fails(self):
        self.glob_cfg(roles() + '[role.plan]\nharness="nope"\n')
        code, out, _ = self.doctor("--smoke")
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL plan", out)
        self.assertCleaned()

    def test_failed_member_fails_and_does_not_escalate(self):
        self.glob_cfg(roles(scout="fail") + '[tier.strong]\nharness="fake"\nmodel="canary"\n')
        code, out, err = self.doctor("--smoke")
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL scout fake/fail: exit 1", out)
        self.assertNotIn("escalating", err)
        self.assertEqual([json.loads(l)["model"] for l in self.index() if json.loads(l)["role"] == "scout"], ["fail"])
        self.assertCleaned()

    def test_canary_file_missing_fails(self):
        self.glob_cfg(roles(implement="canary-nofile"))
        code, out, _ = self.doctor("--smoke")
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL implement fake/canary-nofile: canary.txt missing or wrong", out)
        self.assertCleaned()

    def test_readonly_warning_fails(self):
        self.glob_cfg(roles(scout="canary-dirty"))  # a read-only role that edits the tree
        code, out, _ = self.doctor("--smoke")
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL scout fake/canary-dirty: readonly_warning", out)
        self.assertCleaned()

    def test_stray_file_under_runs_fails(self):
        self.glob_cfg(roles(implement="canary-stray"))
        code, out, _ = self.doctor("--smoke")
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL tree unchanged: .sstack/runs/stray.txt", out)

    def test_exception_cleans_up(self):
        import sstack_doctor as S
        from unittest import mock
        self.glob_cfg(roles())
        with mock.patch.object(S, "_dispatch", side_effect=RuntimeError("boom")), self.assertRaises(RuntimeError):
            S.smoke(self.root)
        self.assertEqual(list((self.root / ".sstack" / "runs").iterdir()), [])

    def crafted(self, run_dirs, name="smoke-20260101-0000", lines=(), roles=None):
        """A --check dir made by hand: smoke.json naming `run_dirs`, plus raw index lines."""
        runs = self.root / ".sstack" / "runs"
        d = runs / "doctor" / name
        d.mkdir(parents=True)
        for l in lines:
            D.append_index(self.root, l)
        (d / "smoke.json").write_text(json.dumps({"token": "t", "baseline": D.snapshot(self.root), "roles": roles or {},
                                                  "run_dirs": [str(x) for x in run_dirs], "errors": []}))
        return d

    def set_run_dirs(self, d, run_dirs):
        p = d / "smoke.json"
        state = json.loads(p.read_text())
        state["run_dirs"] = [str(x) for x in run_dirs]
        p.write_text(json.dumps(state))

    def test_check_refuses_outside_run_dir(self):
        victim = self.home / "victim"
        victim.mkdir()
        (victim / "keep.txt").write_text("x")
        d = self.crafted([victim])
        code, out, _ = self.doctor("--smoke", "--check", str(d))
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL cleanup: not a run of this smoke test", out)
        self.assertTrue((victim / "keep.txt").exists())
        self.assertTrue(d.exists())

    def test_check_refuses_symlinked_run_dir(self):
        victim = self.home / "victim"
        victim.mkdir()
        (victim / "keep.txt").write_text("x")
        d = self.crafted([])
        link = d / "dispatch" / "0000-scout"
        link.parent.mkdir(parents=True)
        link.symlink_to(victim)
        self.set_run_dirs(d, [link])
        code, out, _ = self.doctor("--smoke", "--check", str(d))
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL cleanup: not a run of this smoke test", out)
        self.assertTrue((victim / "keep.txt").exists())

    def test_check_refuses_unrelated_run_inside_runs(self):
        victim = self.root / ".sstack" / "runs" / "other" / "dispatch" / "0000-scout"
        victim.mkdir(parents=True)
        (victim / "run.json").write_text(json.dumps({"report_base": ".sstack/runs/other/scout"}))
        d = self.crafted([])
        self.set_run_dirs(d, [victim])
        code, out, _ = self.doctor("--smoke", "--check", str(d))
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL cleanup: not a run of this smoke test", out)
        self.assertTrue((victim / "run.json").exists())

    def test_check_refuses_non_smoke_dir(self):
        d = self.crafted([], name="20260101-0000-scout")
        code, out, _ = self.doctor("--smoke", "--check", str(d))
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL check:", out)
        self.assertTrue(d.exists())

    def test_check_tolerates_foreign_index_line(self):
        d = self.crafted([], roles={"scout": ["fake/x"]})
        report = (d / "scout.md").relative_to(self.root).as_posix()
        self.set_run_dirs(d, [])
        idx = d.parent.parent / "index.jsonl"
        idx.write_text(json.dumps({"report": report}) + "\n")
        code, out, err = self.doctor("--smoke", "--check", str(d))
        self.assertEqual(code, 1, out + err)
        self.assertIn("FAIL scout fake/x: no index line", out)
        self.assertNotIn("Traceback", err)
        self.assertFalse(d.exists())

    def test_wrong_token_fails(self):
        self.glob_cfg(roles(scout="canary-wrong"))
        code, out, _ = self.doctor("--smoke")
        self.assertEqual(code, 1)
        self.assertIn("FAIL scout fake/canary-wrong: no `CANARY", out)
        self.assertIn("PASS implement", out)
        self.assertCleaned()

    def test_dirty_tree_fails(self):
        self.glob_cfg(roles(implement="canary-dirty"))
        code, out, _ = self.doctor("--smoke")
        self.assertEqual(code, 1)
        self.assertIn("PASS implement fake/canary-dirty", out)
        self.assertIn("FAIL tree unchanged: dirty.txt", out)

    def test_tool_path_stdout_stays_json_with_a_local_role(self):
        self.glob_cfg(roles("haiku", "haiku", "opus").replace('"fake"', '"claude"') + '[role.plan]\nharness="local"\n')
        code, out, err = self.doctor("--smoke", env={"T3CODE_THREAD_ID": "x"})
        self.assertEqual(code, 4, out)
        self.assertNotIn("plan", {x["role"] for x in json.loads(out)["payloads"]})
        self.assertIn("SKIP plan", err)

    def test_tool_path_payloads_then_check(self):
        self.glob_cfg(roles("haiku", "haiku", "opus").replace('"fake"', '"claude"'))
        env = {"T3CODE_THREAD_ID": "x"}
        code, out, _ = self.doctor("--smoke", env=env)
        self.assertEqual(code, 4, out)
        p = json.loads(out)
        d = Path(p["smoke_run_dir"])
        self.assertEqual({x["role"] for x in p["payloads"]}, {"scout", "implement", "review"})
        self.assertFalse(self.index())  # nothing ran
        token = json.loads((d / "smoke.json").read_text())["token"]
        for pl in p["payloads"]:
            for c in pl["calls"]:
                self.assertEqual(c["tool"], "delegate_task")
                report = Path(c["args"]["task"].split("Write your report to ")[1].split(". If")[0])
                report.write_text(f"CANARY {token}\n")
                if pl["role"] == "implement":
                    (d / "canary.txt").write_text(token + "\n")
                cmd = c["record"].replace("{exit}", "0").replace("'<CHILD_THREAD_ID>'", "thread-1").split()[1:]
                with self.subTest(role=pl["role"]):
                    e = dict(NO_T3, HOME=str(self.home))
                    r = subprocess.run([sys.executable, str(REPO / "bin" / "sstack-dispatch"), *cmd],
                                       cwd=self.root, env=e, capture_output=True, text=True)
                    self.assertEqual(r.returncode, 0, r.stderr)
        code, out, _ = self.doctor("--smoke", "--check", str(d), env=env)
        self.assertEqual(code, 0, out)
        self.assertIn("PASS implement claude/haiku", out)
        self.assertFalse(d.exists())
        self.assertCleaned()
        self.assertEqual({json.loads(l)["task"] for l in self.index()}, {"sstack smoke"})


class EntryPointerErrorTests(DoctorBase):
    def test_unreadable_dir_warns_not_fails(self):
        """A permission error inside the advice-only check is WARN, exit unchanged."""
        from test_setup_audit import POINTER
        self.glob_cfg(roles())
        (self.home / ".claude").mkdir()
        (self.home / ".claude" / "CLAUDE.md").write_text(POINTER + "\n")
        (self.home / ".codex").mkdir()
        os.chmod(self.home / ".codex", 0)
        try:
            code, out, _ = self.doctor()
        finally:
            os.chmod(self.home / ".codex", 0o755)
        self.assertEqual(code, 0, out)
        self.assertNotIn("FAIL entry pointers", out)


class WorkflowDoctorTests(DoctorBase):
    """Answer key: doctor validates step folders (decisions R6, R7, R19)."""

    def step(self, name, toml="", **files):
        d = self.root / ".sstack" / "steps" / name
        d.mkdir(parents=True, exist_ok=True)
        if toml:
            (d / "step.toml").write_text(toml)
        for fname, text in files.items():
            (d / fname.replace("_", ".")).write_text(text)

    def check(self, want):
        self.glob_cfg(roles())
        code, out, _ = self.doctor()
        self.assertIn(f"{want} workflow", out)
        return code, out

    def test_defaults_pass(self):
        code, _ = self.check("PASS")
        self.assertEqual(code, 0)

    def test_pr_gate_cannot_be_disabled(self):
        self.step("pr", "gate = false\n")
        code, _ = self.check("FAIL")
        self.assertEqual(code, 1)

    def test_pr_step_cannot_be_disabled(self):
        self.step("pr", "enabled = false\n")
        self.assertEqual(self.check("FAIL")[0], 1)

    def test_unknown_on_fail(self):
        self.step("review", 'on_fail = "nowhere"\n')
        self.assertEqual(self.check("FAIL")[0], 1)

    def test_unknown_after(self):
        self.step("dmm", 'after = "nowhere"\n', run_sh="#!/bin/sh\n")
        self.assertEqual(self.check("FAIL")[0], 1)

    def test_on_fail_to_a_disabled_step(self):
        self.step("plan", "enabled = false\n")
        self.step("review", 'on_fail = "plan"\n')
        self.assertEqual(self.check("FAIL")[0], 1)

    def test_custom_step_with_both_brief_and_run(self):
        self.step("dmm", 'after = "implement"\nrole = "review"\n', brief_md="x\n", run_sh="#!/bin/sh\n")
        self.assertEqual(self.check("FAIL")[0], 1)

    def test_custom_step_with_neither(self):
        self.step("dmm", 'after = "implement"\n')
        self.assertEqual(self.check("FAIL")[0], 1)

    def test_role_step_without_role(self):
        self.step("dmm", 'after = "implement"\n', brief_md="x\n")
        self.assertEqual(self.check("FAIL")[0], 1)

    def test_min_score_out_of_range(self):
        self.step("review", "min_score = 11\n")
        self.assertEqual(self.check("FAIL")[0], 1)

    def test_max_agents_over_max_parallel_warns(self):
        self.step("review", "max_agents = 9\n")
        code, _ = self.check("WARN")
        self.assertEqual(code, 0)
