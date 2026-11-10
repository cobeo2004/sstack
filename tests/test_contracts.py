"""Fixtures are the referee for the B streams (docs/spec/*.md). These checks keep the fixtures
honest: every named case exists, and the loader agrees with each config case's expected.json."""
import json, os, re, shutil, subprocess, sys
from pathlib import Path
from unittest import mock

from helpers import TempEnv, EXAMPLE, FIXTURES, REPO
import sstack_config as C

CONFIG_CASES = ["defaults-only", "home-override", "repo+local", "legacy-only", "legacy-local",
                "mixed-legacy-split", "worktree-fallback", "worktree-local-fallback", "example-equivalent", "skills-keys"]
HOOK_CASES = ["hook-sync", "hook-async", "hook-fails", "hook-missing-creds", "hook-timeout",
              "hook-empty-collect", "hook-bad-json", "hook-wait-fails"]
ADE_CASES = ["t3", "cursor-off", "user-overrides-builtin", *HOOK_CASES]
PANEL_OK = re.compile(r": exit 0 → (.+)$", re.M)  # bin/sstack-reflect-hook's panel index regex
INDEX_KEYS = {"ts", "task", "role", "ade", "via", "harness", "model", "exit", "secs", "run_dir", "report",
              "route", "readonly_warning"}
RUN_KEYS = {"role", "members", "report_base", "panel_report", "started_at", "readonly"}
RUNS = FIXTURES / "runs"  # stands for <repo>/.sstack/runs/


class ConfigCases(TempEnv):
    def build(self, case: Path) -> Path:
        """Lay a case out: home/ → $SSTACK_HOME, repo/ → the git repo, or primary/ + worktree/ →
        a primary checkout and a linked worktree of it. Returns the root to load."""
        os.environ["SSTACK_HOME"] = str(self.home / ".sstack")
        if (case / "home").is_dir():
            shutil.copytree(case / "home", self.home / ".sstack")
        if (case / "repo").is_dir():
            shutil.copytree(case / "repo", self.root, dirs_exist_ok=True)
        if not (case / "primary").is_dir():
            return self.root
        shutil.copytree(case / "primary", self.root, dirs_exist_ok=True)
        g = lambda *a: subprocess.run(["git", "-C", str(self.root), *a], check=True, capture_output=True)
        (self.root / ".git/info/exclude").write_text(".sstack/\n")
        g("commit", "-q", "--allow-empty", "-m", "init")
        wt = self.root.parent / "wt"
        g("worktree", "add", "-q", str(wt))
        if (case / "worktree").is_dir():
            shutil.copytree(case / "worktree", wt, dirs_exist_ok=True)
        return C.git_root(wt)

    def test_every_case_exists(self):
        have = sorted(p.name for p in (FIXTURES / "config").iterdir() if p.is_dir() and p.name[0] != ".")
        self.assertEqual(have, sorted(CONFIG_CASES))

    def test_load_matches_expected(self):
        for name in CONFIG_CASES:
            with self.subTest(name):
                self.tearDown(); self.setUp()
                case = FIXTURES / "config" / name
                want = json.loads((case / "expected.json").read_text())
                root = self.build(case)
                if "error" in want:
                    with self.assertRaises(C.ConfigError) as cm:
                        C.load(root)
                    self.assertIn(want["error"], str(cm.exception))
                else:
                    self.assertEqual(C.load(root), want)

    def test_example_equivalent_keeps_old_example(self):
        os.environ["SSTACK_HOME"] = str(EXAMPLE)
        cfg = C.load(None)
        self.assertEqual(sorted(cfg["tier"]), ["cheap", "standard", "strong"])
        self.assertEqual(cfg["role"]["implement"]["model"], "opencode-go/deepseek-v4.1-flash")


class AdeCases(TempEnv):
    def case(self, name):
        d = FIXTURES / "ades" / name
        return d, json.loads((d / "expected.json").read_text())

    def test_every_case_exists(self):
        have = sorted(p.name for p in (FIXTURES / "ades").iterdir() if p.is_dir() and p.name[0] != ".")
        self.assertEqual(have, sorted(ADE_CASES))

    def test_detection_order_and_flags(self):
        for name in ADE_CASES:
            with self.subTest(name):
                d, want = self.case(name)
                with mock.patch.dict(os.environ, {"SSTACK_HOME": str(d / "home")}):
                    got = C.ades(None)
                self.assertEqual([(a["name"], a["layer"]) for a in got], [tuple(x) for x in want["order"]])
                for a in got:
                    self.assertIn(a["toml"].get("delegate", {}).get("kind"), {"tool", "hook", "none"}, a["name"])
                    if a["toml"]["delegate"]["kind"] == "hook" and a["layer"] == "home":
                        self.assertTrue(os.access(a["hook_path"], os.X_OK), a["name"])

    def hook(self, d, cap, stdin, state, env=None):
        hook = next((d / "home/ades").glob("*.hook"))
        return subprocess.run([str(hook), cap], input=json.dumps(stdin), capture_output=True, text=True,
                              cwd=self.root, env={**os.environ, "SSTACK_HOOK_STATE": str(state), **(env or {})},
                              timeout=10)

    def test_hooks_behave_as_expected(self):
        """The fake hooks follow the lifecycle in docs/spec/ade.md, so B2 can test against them."""
        stdin = {"role": "scout", "readonly": True, "member": "fake/echo", "brief": "b.md",
                 "report": "r.md", "cwd": str(self.root), "title": "sstack scout"}
        for name in HOOK_CASES:
            with self.subTest(name):
                d, want = self.case(name)
                state = self.home / name
                state.mkdir()
                h = lambda cap, body, **kw: self.hook(d, cap, body, state, **kw)
                self.assertEqual(h("detect", {}).returncode, 0)
                r = h("delegate", stdin)
                self.assertEqual(r.returncode, want["delegate_exit"])
                if "delegate" in want:
                    self.assertEqual(json.loads(r.stdout), want["delegate"])
                if "delegate_stdout" in want:
                    self.assertEqual(r.stdout, want["delegate_stdout"])
                    self.assertRaises(ValueError, json.loads, r.stdout)
                if "wait" in want:
                    self.assertEqual([h("wait", {"id": "job-1"}).returncode for _ in want["wait"]], want["wait"])
                if "collect_exit" in want:
                    r = h("collect", {"id": "job-1"})
                    self.assertEqual((r.returncode, r.stdout), (want["collect_exit"], want["report"]))
                if "cancel_marker" in want:
                    self.assertEqual(h("cancel", {"id": "job-1"}).returncode, 0)
                    self.assertTrue((state / want["cancel_marker"]).is_file())
                if name == "hook-missing-creds":
                    r = h("delegate", stdin, env={"FAKE_API_KEY": "k"})
                    self.assertEqual(json.loads(r.stdout)["action"], "run")
                self.assertEqual(sorted(p.name for p in self.root.iterdir()), [".git"])  # nothing in cwd


class PayloadAndRunCases(TempEnv):
    def test_payloads(self):
        for name, role, ro, models in (("t3-scout", "scout", True, ["claude-haiku-5-5"]),
                                       ("t3-review-panel", "review", True, ["gpt-6.1-sol", "claude-opus-5-5"]),
                                       ("t3-implement", "implement", False, ["opencode-go/deepseek-v4.1-flash"])):
            with self.subTest(name):
                p = json.loads((FIXTURES / "payloads" / f"{name}.json").read_text())
                self.assertEqual(set(p), {"ade", "role", "readonly", "run_dir", "max_parallel", "calls"})
                self.assertEqual((p["ade"], p["role"], p["readonly"]), ("t3", role, ro))
                self.assertEqual([c["args"]["target"]["model"] for c in p["calls"]], models)
                for c in p["calls"]:
                    self.assertLessEqual({"member", "tool", "load_hint", "args", "record"}, set(c))
                    self.assertLessEqual(set(c), {"member", "tool", "load_hint", "args", "record", "note"})
                    self.assertEqual(set(c["args"]["target"]), {"providerInstanceId", "model", "options"})
                    self.assertEqual(c["tool"], "delegate_task")
                    if ro:  # read-only: plan mode, never a worktree
                        self.assertEqual(c["args"]["interactionMode"], "plan")
                        self.assertNotIn("isolation", c["args"])
                    else:
                        self.assertEqual(c["args"]["isolation"], "worktree")
                        self.assertNotIn("interactionMode", c["args"])
                    self.assertTrue(c["record"].startswith(f"sstack-dispatch record {role} --report "))
                    self.assertIn(f"--member {c['member']}", c["record"])

    def test_runs(self):
        """One global index.jsonl; run dirs beside it; paths relative to the repo root."""
        lines = [json.loads(l) for l in (RUNS / "index.jsonl").read_text().splitlines()]
        at = lambda rel: RUNS / Path(rel).relative_to(".sstack/runs")
        for rec in lines:
            self.assertEqual(set(rec), INDEX_KEYS)
            self.assertTrue(at(rec["report"]).is_file(), rec["report"])
            self.assertTrue(Path(rec["report"]).is_relative_to(rec["run_dir"]))
            self.assertRegex(rec["run_dir"], rf"^\.sstack/runs/[^/]+/dispatch/\d{{4}}-{rec['role']}$")
        self.assertTrue(any(r["readonly_warning"] for r in lines))
        dirs = {r["run_dir"] for r in lines}
        self.assertEqual({(Path(".sstack/runs") / p.parent.relative_to(RUNS)).as_posix()
                          for p in RUNS.rglob("run.json")}, dirs)
        self.assertEqual({p.name for p in RUNS.iterdir() if p.is_dir()},
                         {Path(r["run_dir"]).parts[2] for r in lines})
        for rd in dirs:
            run = json.loads((at(rd) / "run.json").read_text())
            self.assertEqual(set(run), RUN_KEYS)
            self.assertEqual(run["members"], [f"{r['harness']}/{r['model']}" for r in lines if r["run_dir"] == rd])
            if run["readonly"]:
                base = json.loads((at(rd) / "baseline.json").read_text())
                self.assertEqual(set(base), {"head", "status", "files"})
            if run["panel_report"]:
                panel = at(run["panel_report"]).read_text()
                self.assertTrue(panel.startswith("# review panel"))
                self.assertEqual(len(PANEL_OK.findall(panel)), len(run["members"]))


class NoExampleConfig(TempEnv):
    def test_example_config_deleted(self):
        # spelled so neither this file nor its .pyc matches the grep below
        self.assertFalse((REPO / ("config" + chr(46) + "example.toml")).exists())
        r = subprocess.run(["grep", "-rn", "config[.]example", "lib", "bin", "tests"], cwd=REPO,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, r.stdout)
