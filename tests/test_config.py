import os, shutil, subprocess, sys, tempfile
from pathlib import Path
from unittest import mock

from helpers import TempEnv, REPO
import sstack_config as C

HARN = '[harness.pi]\nheadless=["pi"]\n[harness.codex]\nheadless=["codex"]\n'


class ConfigTests(TempEnv):
    def test_empty_layer_dir_keeps_worktree_fallback(self):
        import subprocess
        self.glob_cfg(HARN)
        self.repo_cfg('[role.implement]\nharness="codex"\nmodel="m2"\n')
        g = lambda *a: subprocess.run(["git", "-C", str(self.root), *a], check=True, capture_output=True)
        g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "i")
        wt = self.root.parent / "wt"
        g("worktree", "add", "-q", str(wt))
        (wt / ".sstack" / "roles").mkdir(parents=True)  # empty: holds no config
        self.assertEqual(C.load(wt)["role"]["implement"]["model"], "m2")

    def test_role_file_replaced_whole(self):
        self.glob_cfg(HARN + '[role.implement]\nharness="pi"\nmodel="m1"\neffort="high"\n')
        self.repo_cfg('[role.implement]\nharness="codex"\nmodel="m2"\n')
        self.assertEqual(C.load(self.root)["role"]["implement"], {"harness": "codex", "model": "m2"})

    def test_config_toml_merges_key_by_key(self):
        self.glob_cfg('[dispatch]\ntimeout_min=30\nvia="auto"\n')
        self.local_cfg('[dispatch]\nvia="headless"\n')
        d = C.load(self.root)["dispatch"]
        self.assertEqual((d["via"], d["timeout_min"]), ("headless", 30))

    def test_local_overrides_repo(self):
        self.glob_cfg(HARN)
        self.repo_cfg('[role.implement]\nharness="codex"\n')
        self.local_cfg('[role.implement]\nharness="pi"\n')
        self.assertEqual(C.resolve(C.load(self.root), "implement")[0]["harness"], "pi")

    def test_split_files_on_disk(self):
        self.glob_cfg(HARN + '[role.implement]\nharness="pi"\n[rules]\nmax_parallel=2\n')
        s = self.home / ".sstack"
        self.assertTrue((s / "harnesses/pi.toml").is_file())
        self.assertTrue((s / "roles/implement.toml").is_file())
        self.assertNotIn("[role", (s / "config.toml").read_text())

    def test_template_is_not_a_layer(self):
        cfg = C.load(None)  # a synced profile: the template's values, read from home
        self.assertEqual(sorted(cfg["harness"]), ["claude", "codex", "cursor", "pi"])
        self.assertNotIn("t3_provider", cfg["harness"]["pi"])
        self.assertEqual(cfg["dispatch"]["via"], "auto")
        self.assertNotIn("tier", cfg)  # no tiers: kind routing stays off
        self.assertEqual(C.layers(None), [("home", self.home / ".sstack")])
        self.assertNotIn(REPO / "defaults", [d for _, d in C.layers(self.root)])

    def test_no_profile_is_an_error_with_the_fix(self):
        shutil.rmtree(self.home / ".sstack")
        with self.assertRaises(C.ConfigError) as cm:
            C.load(self.root)
        self.assertIn("no sstack profile at", str(cm.exception))
        self.assertIn("sstack-config sync", str(cm.exception))
        env = {**os.environ, "HOME": str(self.home)}
        for cmd in (["sstack-config", "show"], ["sstack-dispatch", "routes"]):
            with self.subTest(cmd=cmd[0]):
                r = subprocess.run([sys.executable, str(REPO / "bin" / cmd[0]), *cmd[1:]], cwd=self.root,
                                   env=env, capture_output=True, text=True)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("sstack-config sync", r.stderr)

    def test_deleted_home_harness_is_gone_not_the_templates(self):
        (self.home / ".sstack/harnesses/claude.toml").unlink()
        cfg = C.load(self.root)
        self.assertNotIn("claude", cfg["harness"])
        with self.assertRaises(C.ConfigError) as cm:
            C.resolve(cfg, "scout")
        self.assertIn("unknown harness 'claude'", str(cm.exception))
        self.assertIn("sstack-config sync", str(cm.exception))

    def test_code_files_come_from_the_template_until_a_layer_has_one(self):
        tpl = REPO / "defaults/steps/gate/run.sh"
        self.assertFalse((self.home / ".sstack/steps/gate/run.sh").exists())
        self.assertEqual(C.source(self.root, "steps", "gate/run.sh"), ("template", tpl))
        gate = C.steps(self.root)["gate"]
        self.assertEqual((gate["run"], gate["source"]["run"]), (tpl, "template"))
        self.assertEqual(C.source(self.root, "ades", "orca.hook"), ("template", REPO / "defaults/ades/orca.hook"))
        self.assertIsNone(C.source(self.root, "steps", "gate/step.toml.bak"))
        mine = self.write(self.home, ".sstack/steps/gate/run.sh", "#!/bin/sh\n")
        self.assertEqual(C.source(self.root, "steps", "gate/run.sh"), ("home", mine))
        self.assertEqual(C.steps(self.root)["gate"]["source"]["run"], "home")

    def test_sstack_home_env(self):
        other = self.profile(self.home / "elsewhere")
        self.write(other, "roles/scout.toml", 'harness="codex"\nmodel="x"\n')
        with mock.patch.dict(os.environ, {"SSTACK_HOME": str(other)}):
            self.assertEqual(C.layers(None)[0], ("home", other))
            self.assertEqual(C.load(None)["role"]["scout"]["model"], "x")

    def test_template_routes_investigate_and_plan(self):
        cfg = C.load(self.root)
        self.assertEqual(C.resolve(cfg, "investigate"), [{"harness": "claude", "model": "sonnet", "effort": None}])
        self.assertEqual(C.resolve(cfg, "plan"), [{"harness": "claude", "model": "opus", "effort": None}])

    def test_unlisted_role_is_local(self):
        self.glob_cfg(HARN)
        (self.home / ".sstack/roles/investigate.toml").unlink()
        self.assertIsNone(C.resolve(C.load(self.root), "investigate"))

    def test_harness_local_is_local(self):
        self.glob_cfg(HARN + '[role.implement]\nharness="local"\n')
        self.assertIsNone(C.resolve(C.load(self.root), "implement"))

    def test_via_local_is_local(self):
        self.glob_cfg(HARN + '[role.implement]\nharness="pi"\n[dispatch]\nvia="local"\n')
        self.assertIsNone(C.resolve(C.load(self.root), "implement"))

    def test_panel_drops_implementer(self):
        self.glob_cfg(HARN + '[role.implement]\nharness="pi"\nmodel="m1"\n'
                      '[role.review]\npanel=[{harness="pi",model="m1"},{harness="codex",model="x"}]\n'
                      '[rules]\nreview_not_implementer=true\n')
        self.assertEqual(C.resolve(C.load(self.root), "review"),
                         [{"harness": "codex", "model": "x", "effort": None}])

    def test_unknown_harness_raises(self):
        self.glob_cfg(HARN + '[role.implement]\nharness="nope"\n')
        with self.assertRaises(C.ConfigError):
            C.resolve(C.load(self.root), "implement")

    def test_bad_toml_names_file(self):
        self.repo_cfg('[role.implement]\nharness = [')
        with self.assertRaises(C.ConfigError) as cm:
            C.load(self.root)
        self.assertIn(".sstack/roles/implement.toml", str(cm.exception))

    def test_no_git_root_uses_home(self):
        self.glob_cfg('[reflect]\nauto=true\n')
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(C.git_root(Path(d)))
        self.assertTrue(C.load(None)["reflect"]["auto"])
        self.assertEqual([n for n, _ in C.layers(None)], ["home"])

    def test_layers_order(self):
        self.assertEqual([n for n, _ in C.layers(self.root)], ["home", "repo", "local"])

    def test_source(self):
        self.glob_cfg(HARN + '[role.implement]\nharness="pi"\n')
        self.local_cfg('[role.implement]\nharness="codex"\n')
        self.assertEqual(C.source(self.root, "roles", "implement"),
                         ("local", self.root / ".sstack/local/roles/implement.toml"))
        self.assertEqual(C.source(self.root, "harnesses", "pi")[0], "home")
        self.assertEqual(C.source(self.root, "harnesses", "claude")[0], "home")
        self.assertEqual(C.source(self.root, "config", None)[0], "home")
        (self.home / ".sstack/roles/plan.toml").unlink()
        self.assertIsNone(C.source(self.root, "roles", "plan"))

    def test_project_is_repo_only_and_whole(self):
        self.write(self.home, ".sstack/project.toml", 'verify="home"\n')
        self.repo_cfg('[project]\nverify="make test"\nbrief="b.md"\n')
        self.local_cfg('[project]\nverify="mine"\n')
        self.assertEqual(C.load(self.root)["project"], {"verify": "mine"})

    def test_legacy_only_raises_with_migrate(self):
        self.write(self.home, ".sstack/config.toml", HARN + '[role.implement]\nharness="pi"\n')
        self.write(self.root, ".sstack/config.local.toml", '[role.implement]\nharness="codex"\n')
        self.assertEqual(C.legacy(self.root), [self.home / ".sstack/config.toml",
                                                self.root / ".sstack/config.local.toml"])
        with self.assertRaises(C.ConfigError) as cm:
            C.load(self.root)
        self.assertIn("sstack-config migrate", str(cm.exception))

    def test_legacy_deduped_when_home_is_repo(self):
        p = self.write(self.root, ".sstack/config.toml", '[transport]\nmode="auto"\n')
        with mock.patch.dict(os.environ, {"SSTACK_HOME": str(self.root / ".sstack")}):
            self.assertEqual(C.legacy(self.root), [p])
            self.assertRaises(C.ConfigError, C.load, self.root)

    def test_source_dotted_names_and_traversal(self):
        self.write(self.home, ".sstack/roles/ui.fast.toml", 'harness="pi"\n')
        self.assertEqual(C.source(self.root, "roles", "ui.fast"), ("home", self.home / ".sstack/roles/ui.fast.toml"))
        self.assertEqual(C.source(self.root, "ades", "t3.md"), ("home", self.home / ".sstack/ades/t3.md"))
        self.assertIsNone(C.source(self.root, "roles", "../config"))
        self.assertIsNone(C.source(self.root, "ades", "../config.toml"))

    def test_split_config_is_not_legacy(self):
        self.glob_cfg(HARN + '[rules]\nmax_parallel=2\n')
        self.assertEqual(C.legacy(self.root), [])

    def test_ades_detection_order(self):
        self.write(self.home, ".sstack/ades/zed.toml", '[detect]\nenv=["ZED"]\n')
        self.write(self.home, ".sstack/ades/acme.toml", 'auto=false\n[detect]\nenv=["ACME"]\n')
        self.write(self.home, ".sstack/ades/acme.hook", '#!/bin/sh\n')
        self.write(self.root, ".sstack/ades/t3.toml", '[detect]\nenv=["MY_T3"]\n')
        a = C.ades(self.root)
        self.assertEqual([(x["name"], x["layer"]) for x in a],
                         [("t3", "repo"), ("acme", "home"), ("zed", "home"),
                          ("conductor", "home"), ("cursor", "home"), ("orca", "home")])
        t3 = a[0]
        self.assertEqual(t3["toml"]["detect"]["env"], ["MY_T3"])
        self.assertEqual(t3["note_path"], self.home / ".sstack/ades/t3.md")  # per-file fallback
        self.assertEqual(a[1]["hook_path"], self.home / ".sstack/ades/acme.hook")
        self.assertIsNone(a[2]["hook_path"])
        self.assertEqual((a[1]["auto"], a[2]["auto"]), (False, True))
        self.assertFalse(next(x for x in a if x["name"] == "cursor")["auto"])
