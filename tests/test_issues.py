"""Acceptance checks for GitHub issues #2-#6 (answer key; protected)."""
import json, subprocess, sys
from pathlib import Path

from helpers import TempEnv, REPO
from test_dispatch import DispatchBase, FAKE
import sstack_config as C
import sstack_lessons as L
import sstack_route as R

SCOUT_PANEL = '[role.scout]\npanel=[{harness="fake",model="a"},{harness="fake",model="b"}]\n'
TIERS = FAKE + ''.join(f'[tier.{t}]\nharness="fake"\nmodel="{t}"\n' for t in ("cheap", "standard", "strong"))


class Issue2PanelRoles(DispatchBase):
    def test_scout_panel_runs_every_member(self):
        self.glob_cfg(FAKE + SCOUT_PANEL)
        code, out, _ = self.run_main("scout", "--brief", self.brief(), "--report", str(self.report()), "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count("headless:"), 2)

    def test_scout_panel_writes_member_reports(self):
        self.glob_cfg(FAKE + SCOUT_PANEL.replace('"a"', '"echo"').replace('"b"', '"env"'))
        code, _, err = self.run_main("scout", "--brief", self.brief(), "--report", str(self.report()))
        self.assertEqual(code, 0, err)
        self.assertEqual(len(list(self.report().parent.glob("r.fake-*.md"))), 2)

    def test_panel_on_write_role_is_config_error(self):
        self.glob_cfg(FAKE + '[role.implement]\npanel=[{harness="fake",model="a"}]\n')
        code, out, err = self.run_main("implement", "--brief", self.brief(), "--report", str(self.report()), "--dry-run")
        self.assertEqual(code, 1, out)
        self.assertIn("hint", err)


class Issue3ReflectPanel(TempEnv):
    def test_hook_reads_every_member_report_and_dedupes(self):
        agent = self.home / "agent.py"
        agent.write_text("import sys; sys.stdin.read()\n"
                         "print('LESSON: repo | shared lesson | why')\n"
                         "print('LESSON: repo | only from ' + sys.argv[1] + ' | why')\n")
        h = f'["{sys.executable}", "{agent}", "{{model}}"]'
        self.glob_cfg(f'[harness.fake]\nheadless = {h}\nheadless_readonly = {h}\n' + SCOUT_PANEL
                      + '[reflect]\nauto = true\n')
        env = {k: v for k, v in __import__("os").environ.items() if not k.startswith(("T3CODE", "SSTACK_"))}
        env["HOME"] = str(self.home)
        t = self.root / "t.jsonl"; t.write_text("{}\n")
        r = subprocess.run([sys.executable, str(REPO / "bin/sstack-reflect-hook"), "--foreground"],
                           input=json.dumps({"cwd": str(self.root), "transcript_path": str(t)}),
                           capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = (self.root / ".sstack/lessons.md").read_text()
        self.assertIn("seen=1 id=L1 | shared lesson", text)  # once, not twice
        self.assertIn("only from a", text)
        self.assertIn("only from b", text)


class Issue4Kinds(TempEnv):
    def test_plain_ts_js_classified(self):
        self.assertEqual(R.classify(["supabase/functions/_shared/foo.ts"]), "backend")
        self.assertEqual(R.classify(["server/x.mjs"]), "backend")
        self.assertEqual(R.classify(["src/lib/foo.ts"]), "frontend")
        self.assertIsNotNone(R.classify(["x.js"]))

    def test_security_beats_path_hint(self):
        cfg = __import__("tomllib").loads(
            TIERS + '[role.implement.hint.edge]\npaths=["supabase/functions/*"]\ntier="standard"\n')
        m, route, _ = R.pick(cfg, "implement", None, ["supabase/functions/_shared/auth.ts"])
        self.assertEqual(m["model"], "strong", route)
        m, route, _ = R.pick(cfg, "implement", None, ["supabase/functions/_shared/foo.ts"])
        self.assertEqual(m["model"], "standard", route)

    def test_override_security_hint_still_wins(self):
        cfg = __import__("tomllib").loads(
            TIERS + '[role.implement.hint.edge]\npaths=["supabase/functions/*"]\ntier="standard"\n'
                    'override_security=true\n')
        m, _, _ = R.pick(cfg, "implement", None, ["supabase/functions/_shared/auth.ts"])
        self.assertEqual(m["model"], "standard")

    def test_untracked_hidden_dirs_ignored(self):
        p = self.root / "supabase/migrations/.omc/state.json"
        p.parent.mkdir(parents=True); p.write_text("{}")
        (self.root / "a.md").write_text("x")
        files, _ = R.changed(self.root)
        self.assertEqual(files, ["a.md"])

    def test_docs_only_never_security(self):
        self.assertEqual(R.classify(["docs/billing.md", "auth.md"]), "docs")
        self.assertEqual(R.classify(["docs/billing.md", "src/auth.ts"]), "security")


class Issue5Worktree(TempEnv):
    def setUp(self):
        super().setUp()
        g = lambda *a: subprocess.run(["git", "-C", str(self.root), *a], check=True, capture_output=True)
        g("commit", "-q", "--allow-empty", "-m", "init")
        self.repo_cfg('[project]\nverify = "make test"\n')
        (self.root / ".git/info/exclude").write_text(".sstack/\n")
        self.wt = self.root.parent / "wt"
        g("worktree", "add", "-q", str(self.wt))

    def test_worktree_falls_back_to_primary_config(self):
        self.assertEqual(C.load(C.git_root(self.wt))["project"]["verify"], "make test")

    def test_worktree_own_config_wins(self):
        self.write(self.wt, ".sstack/project.toml", 'verify = "own"\n')
        self.assertEqual(C.load(C.git_root(self.wt))["project"]["verify"], "own")

    def test_repo_lessons_go_to_primary(self):
        self.assertEqual(L.lessons_path("repo", C.git_root(self.wt)), self.root / ".sstack/lessons.md")


class Issue6Route(DispatchBase):
    def test_route_json(self):
        self.example()
        # --route prints the exit-4 payload shape (docs/spec/dispatch.md); in T3 that carries the ids
        code, out, err = self.run_main("review", "--route", "--panel", "--files", "src/x.ts",
                                       env={"T3CODE_THREAD_ID": "x"})
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertTrue(d["readonly"])
        self.assertIn("panel", d["route"])
        codex = next(c for c in d["calls"] if c["member"] == "codex/gpt-6.1-sol")["args"]["target"]
        self.assertEqual((codex["providerInstanceId"], codex["model"], codex["options"]),
                         ("codex", "gpt-6.1-sol", {"reasoningEffort": "high"}))
        self.assertFalse((self.root / ".sstack").exists())  # --route creates nothing

    def test_route_json_headless(self):
        self.example()
        code, out, _ = self.run_main("scout", "--route")
        self.assertEqual((code, json.loads(out)["calls"]), (0, [{"member": "claude/haiku", "via": "headless"}]))

    def test_route_json_local(self):
        self.glob_cfg(FAKE)
        (self.home / ".sstack/roles/investigate.toml").unlink()  # the template routes it
        code, out, _ = self.run_main("investigate", "--route")
        self.assertEqual((code, json.loads(out)["calls"]), (3, []))

    def test_cursor_has_readonly_command(self):
        import tomllib
        h = tomllib.loads((REPO / "defaults/harnesses/cursor.toml").read_text())
        self.assertIn("plan", h["headless_readonly"])
