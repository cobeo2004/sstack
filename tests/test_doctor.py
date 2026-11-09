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
        e["PATH"] = f"{REPO / 'bin'}:{e.get('PATH', '')}"  # `record` in payloads runs sstack-dispatch
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

    def test_bad_toml(self):
        self.glob_cfg(roles())
        (self.home / ".sstack" / "roles" / "scout.toml").write_text("harness = \n")
        code, out, _ = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn("FAIL config loads", out)

    def test_legacy(self):
        (self.home / ".sstack").mkdir()
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
        ad.mkdir()
        (ad / "mine.toml").write_text("auto = false\n[delegate]\nkind = \"hook\"\n")
        (ad / "mine.hook").write_text("#!/bin/sh\n")
        code, out, _ = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn("FAIL hooks executable: not executable:", out)
        self.assertIn("mine.hook", out)


class SmokeTests(DoctorBase):
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

    def crafted(self, run_dirs, name="20260101-0000-smoke", lines=(), roles=None):
        """A --check dir made by hand: smoke.json naming `run_dirs`, plus raw index lines."""
        runs = self.root / ".sstack" / "runs"
        d = runs / name
        d.mkdir(parents=True)
        for l in lines:
            D.append_index(self.root, l)
        (d / "smoke.json").write_text(json.dumps({"token": "t", "baseline": D.snapshot(self.root), "roles": roles or {},
                                                  "run_dirs": [str(x) for x in run_dirs], "errors": []}))
        return d

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
        link = self.root / ".sstack" / "runs" / "20260101-0000-scout"
        link.parent.mkdir(parents=True)
        link.symlink_to(victim)
        code, out, _ = self.doctor("--smoke", "--check", str(self.crafted([link])))
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL cleanup: not a run of this smoke test", out)
        self.assertTrue((victim / "keep.txt").exists())

    def test_check_refuses_unrelated_run_inside_runs(self):
        victim = self.root / ".sstack" / "runs" / "20260101-0000-scout"
        victim.mkdir(parents=True)
        (victim / "run.json").write_text(json.dumps({"report_base": ".sstack/runs/other/scout"}))
        code, out, _ = self.doctor("--smoke", "--check", str(self.crafted([victim])))
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
        d = self.crafted([], lines=[{"report": ".sstack/runs/20260101-0000-smoke/scout.md"}],
                         roles={"scout": ["fake/x"]})
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
                cmd = c["record"].replace("{exit}", "0").split()[1:]
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
