import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from unittest import mock

from helpers import REPO, TempEnv
import sstack_config as C
import sstack_configcli as M
import sstack_route as R

DATA = REPO / "tests" / "configcli_data"
CLI = REPO / "bin" / "sstack-config"
WHOLE = {"role", "harness", "tier"}
SPLIT_TABLES = ("harness", "role", "tier")


def merge(base: dict, over: dict, path: tuple = ()) -> dict:
    """The loader's merge: config key by key, role/harness/tier/project whole."""
    out = dict(base)
    for k, v in over.items():
        whole = (len(path) == 1 and path[0] in WHOLE) or (not path and k == "project")
        if isinstance(v, dict) and isinstance(out.get(k), dict) and not whole:
            out[k] = merge(out[k], v, path + (k,))
        else:
            out[k] = v
    return out


def legacy_map(data: dict, layer: str = "repo") -> dict:
    """One legacy file's tables after the documented migrate mapping."""
    out = {k: v for k, v in data.items() if k not in (*SPLIT_TABLES, "project", "transport")}
    for table in SPLIT_TABLES:
        if table in data:
            out[table] = data[table]
    if "project" in data and layer != "home":
        out["project"] = data["project"]
    transport = data.get("transport") or {}
    dispatch = dict(out.get("dispatch") or {})
    if "mode" in transport:
        dispatch["via"] = {"thread": "ade-cli"}.get(transport["mode"], transport["mode"])
    if "timeout_min" in transport and "timeout_min" not in dispatch:
        dispatch["timeout_min"] = transport["timeout_min"]
    if dispatch:
        out["dispatch"] = dispatch
    if "harness" in out:
        out["harness"] = {name: {k: v for k, v in h.items() if k != "t3_provider"}
                          for name, h in out["harness"].items()}
    return out


def legacy_effective(home: Path, root: Path) -> dict:
    """The pre-split loader's whole effective config: defaults + every legacy file, mapped."""
    cfg = C._layer_data("defaults", C.DEFAULTS)
    for layer, p in (("home", home / ".sstack/config.toml"),
                     ("repo", root / ".sstack/config.toml"),
                     ("repo", root / ".sstack/config.local.toml")):
        if p.is_file():
            cfg = merge(cfg, legacy_map(tomllib.loads(p.read_text()), layer))
    return cfg


class ConfigCliTests(TempEnv):
    def run_cli(self, *args, cwd=None, code=0):
        """Run the CLI; returns stdout on success, stderr on failure."""
        env = dict(os.environ, HOME=str(self.home))
        env.pop("SSTACK_HOME", None)
        r = subprocess.run([sys.executable, str(CLI), *args], cwd=str(cwd or self.root),
                           env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, code, r.stderr or r.stdout)
        return r.stdout if code == 0 else r.stderr

    def copy_global(self):
        p = self.write(self.home, ".sstack/config.toml", "")
        shutil.copy(DATA / "global.toml", p)
        return p

    def copy_unibuz(self):
        p = self.write(self.root, ".sstack/config.toml", "")
        shutil.copy(DATA / "unibuz.toml", p)
        return p

    def test_round_trip_real_configs(self):
        global_cfg = self.copy_global()
        repo_cfg = self.copy_unibuz()
        old = legacy_effective(self.home, self.root)
        out = self.run_cli("migrate")
        self.assertIn("next: sstack-doctor", out)
        self.assertEqual((global_cfg.parent / "config.toml.bak").read_text(), (DATA / "global.toml").read_text())
        self.assertEqual((repo_cfg.parent / "config.toml.bak").read_text(), (DATA / "unibuz.toml").read_text())
        self.assertEqual(C.legacy(self.root), [])

        new = C.load(self.root)
        self.assertEqual(new, old)  # every table, not just role/harness/project
        for role in {*old["role"], *new["role"]}:
            for kind in [*R.KIND_TIER, None]:
                with self.subTest(role=role, kind=kind):
                    self.assertEqual(R.pick(new, role, kind, []), R.pick(old, role, kind, []))

    def test_panel_array_of_tables_stays_array(self):
        self.write(self.home, ".sstack/config.toml", """\
[role.review]
mode = "panel"

[[role.review.panel]]
harness = "codex"
model = "gpt-6.1-sol"
effort = "high"

[[role.review.panel]]
harness = "claude"
model = "opus"
""")
        self.run_cli("migrate", "--global")
        text = (self.home / ".sstack/roles/review.toml").read_text()
        self.assertEqual(text.count("[[panel]]"), 2, text)
        panel = C.load(None)["role"]["review"]["panel"]
        self.assertEqual([(m["harness"], m["model"]) for m in panel],
                         [("codex", "gpt-6.1-sol"), ("claude", "opus")])
        shown = self.run_cli("show", "roles/review")
        self.assertIn("[[panel]]", shown)
        self.assertIn('model = "gpt-6.1-sol"', shown)
        self.assertIn('model = "opus"', shown)

    def test_dotted_tier_name_keeps_its_name(self):
        self.write(self.home, ".sstack/config.toml",
                   '[tier."ui.fast"]\nharness = "claude"\nmodel = "haiku"\n')
        self.run_cli("migrate", "--global")
        self.assertEqual((self.home / ".sstack/tiers/ui.fast.toml").read_text(),
                         'harness = "claude"\nmodel = "haiku"\n')
        self.assertEqual(C.load(None)["tier"]["ui.fast"], {"harness": "claude", "model": "haiku"})

    def test_hint_sub_table_and_comment_survive(self):
        self.write(self.home, ".sstack/config.toml", """\
[role.implement]
harness = "pi"
# keep this
[role.implement.hint.ui]
note = "be brief"
""")
        self.run_cli("migrate", "--global")
        text = (self.home / ".sstack/roles/implement.toml").read_text()
        self.assertIn("# keep this", text)
        self.assertIn("[hint.ui]", text)
        self.assertEqual(C.load(None)["role"]["implement"],
                         {"harness": "pi", "hint": {"ui": {"note": "be brief"}}})

    def test_header_like_lines_inside_values_are_not_headers(self):
        self.write(self.home, ".sstack/config.toml", """\
[harness.pi]
headless = [
  ["pi"]
]
note = '''
[role.scout]
'''
[rules]
max_parallel = 2
""")
        self.run_cli("migrate", "--global")
        cfg = C.load(None)
        self.assertEqual(cfg["harness"]["pi"]["headless"], [["pi"]])
        self.assertIn("[role.scout]", cfg["harness"]["pi"]["note"])
        self.assertEqual(cfg["rules"]["max_parallel"], 2)

    def test_unsafe_split_is_refused_before_any_write(self):
        cfg = self.write(self.home, ".sstack/config.toml",
                         '[role]\nscout = { harness = "claude", model = "haiku" }\n')
        before = cfg.read_bytes()
        err = self.run_cli("migrate", "--global", code=1)
        self.assertIn("cannot split", err)
        self.assertIn("role", err)
        self.assertEqual(cfg.read_bytes(), before)
        self.assertFalse((cfg.parent / "config.toml.bak").exists())
        self.assertFalse((cfg.parent / "roles").exists())
        self.assertFalse((cfg.parent / "harnesses").exists())

    def test_write_failure_before_rename_rolls_back(self):
        cfg = self.write(self.home, ".sstack/config.toml", '[role.scout]\nharness = "claude"\n')
        roles = self.home / ".sstack/roles"
        roles.mkdir()
        roles.chmod(0o555)
        try:
            err = self.run_cli("migrate", "--global", code=1)
        finally:
            roles.chmod(0o755)
        self.assertIn("error:", err)
        self.assertFalse((cfg.parent / "config.toml.bak").exists())
        self.assertEqual(tomllib.loads(cfg.read_text())["role"]["scout"]["harness"], "claude")
        self.run_cli("migrate", "--global")  # a rerun still finds the legacy file
        self.assertEqual(C.load(None)["role"]["scout"]["harness"], "claude")

    def test_failure_after_rename_rolls_back(self):
        self.write(self.root, ".gitignore", "node_modules/\n")
        local = self.write(self.root, ".sstack/config.local.toml",
                           '[role.implement]\nharness = "codex"\n')
        gi = self.root / ".gitignore"
        self.root.chmod(0o555)  # the .gitignore write is the first one in the repo root
        try:
            err = self.run_cli("migrate", "--repo", code=1)
        finally:
            self.root.chmod(0o755)
        self.assertIn("error:", err)
        self.assertTrue(local.is_file())
        self.assertFalse((self.root / ".sstack/config.local.toml.bak").exists())
        self.assertFalse((self.root / ".sstack/local/roles/implement.toml").exists())
        self.assertEqual(gi.read_text(), "node_modules/\n")
        self.assertEqual(C.legacy(self.root), [local])

    def test_load_failure_after_migrate_exits_one(self):
        self.write(self.home, ".sstack/config.toml", '[role.scout]\nharness = "claude"\n')
        self.write(self.root, ".sstack/roles/broken.toml", "[oops\n")
        err = self.run_cli("migrate", "--global", code=1)
        self.assertIn("broken.toml", err)

    def test_scoped_migrate_reports_remaining_legacy(self):
        self.write(self.home, ".sstack/config.toml", '[role.scout]\nharness = "claude"\n')
        repo_cfg = self.write(self.root, ".sstack/config.toml", '[project]\nverify = "make"\n')
        out = self.run_cli("migrate", "--global")
        self.assertIn(f"note: still legacy: {repo_cfg}", out)
        self.assertIn("next: sstack-doctor", out)
        self.assertTrue((self.home / ".sstack/roles/scout.toml").is_file())
        out = self.run_cli("migrate", "--repo")
        self.assertNotIn("still legacy", out)
        self.assertIn("next: sstack-doctor", out)
        self.assertEqual(C.legacy(self.root), [])

    def test_repo_migrate_uses_the_primary_in_a_worktree(self):
        git = lambda *a: subprocess.run(["git", "-C", str(self.root), *a], check=True,
                                        capture_output=True)
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        self.write(self.root, ".git/info/exclude", ".sstack/\n")
        git("commit", "-qm", "init", "--allow-empty")
        wt = self.root.parent / "wt"
        git("worktree", "add", "-q", str(wt))
        self.assertFalse((wt / ".sstack").exists())
        self.write(self.root, ".sstack/config.toml", '[project]\nverify = "make"\n')
        out = self.run_cli("migrate", "--repo", cwd=wt)
        self.assertIn("next: sstack-doctor", out)
        self.assertTrue((self.root / ".sstack/project.toml").is_file())
        self.assertTrue((self.root / ".sstack/config.toml.bak").is_file())
        self.assertEqual(C.load(C.git_root(wt))["project"], {"verify": "make"})

    def test_show_refuses_legacy(self):
        self.write(self.home, ".sstack/config.toml", '[role.review]\nharness = "claude"\n')
        for args in (("show", "roles/review"), ("show",)):
            with self.subTest(args=args):
                err = self.run_cli(*args, code=1)
                self.assertIn("legacy sstack config", err)
                self.assertIn("sstack-config migrate", err)

    def test_unmapped_transport_keys_are_not_silent(self):
        self.write(self.home, ".sstack/config.toml", """\
[transport]
mode = "auto"
command = "legacy-thing"

[transport.orca]
url = "http://x"
""")
        out = self.run_cli("migrate", "--global")
        self.assertIn('note: dropped transport.command = "legacy-thing"', out)
        self.assertIn('note: dropped transport.orca.url = "http://x"', out)

    def test_gitignore_adds_bak_and_is_idempotent(self):
        gi = self.write(self.root, ".gitignore", "/.sstack/local/\n")
        self.write(self.root, ".sstack/config.local.toml", '[role.implement]\nharness = "codex"\n')
        self.run_cli("migrate", "--repo")
        self.assertEqual(gi.read_text().splitlines(),
                         ["/.sstack/local/", ".sstack/config.local.toml.bak"])
        before = gi.read_bytes()
        self.assertEqual(self.run_cli("migrate", "--repo"), "no legacy config\n")
        self.assertEqual(gi.read_bytes(), before)
        self.assertEqual(subprocess.run(["git", "-C", str(self.root), "check-ignore", "-q",
                                         ".sstack/config.local.toml.bak"]).returncode, 0)

    def test_global_dry_run_writes_nothing(self):
        cfg = self.copy_global()
        before = cfg.read_bytes()
        out = self.run_cli("migrate", "--global", "--dry-run")
        self.assertIn("write", out)
        self.assertIn("rename", out)
        self.assertEqual(cfg.read_bytes(), before)
        self.assertFalse((cfg.parent / "config.toml.bak").exists())
        self.assertFalse((cfg.parent / "harnesses").exists())

    def test_mapping_and_notes(self):
        p = self.write(self.home, ".sstack/config.toml", """\
[harness.pi]
headless = ["pi"]
t3_provider = "pi"

[transport]
mode = "thread"
timeout_min = 12

[transport.t3]
detect = "T3CODE_THREAD_ID"

[project]
verify = "make"

[rules]
max_parallel = 2
""")
        out = self.run_cli("migrate", "--global")
        cfg = C.load(None)
        self.assertEqual(cfg["dispatch"], {"via": "ade-cli", "timeout_min": 12})
        self.assertNotIn("t3_provider", cfg["harness"]["pi"])
        self.assertEqual(cfg["rules"]["max_parallel"], 2)
        self.assertFalse((p.parent / "project.toml").exists())
        self.assertIn("provider ids live in ades/t3.toml [providers]", out)
        self.assertIn("defaults/ades/t3.toml", out)
        self.assertIn("project is repo-only", out)

    def test_existing_dispatch_timeout_wins_but_mode_maps(self):
        self.write(self.home, ".sstack/config.toml",
                   '[dispatch]\nvia = "headless"\ntimeout_min = 99\n\n'
                   '[transport]\nmode = "thread"\ntimeout_min = 12\n')
        self.run_cli("migrate", "--global")
        self.assertEqual(C.load(None)["dispatch"], {"via": "ade-cli", "timeout_min": 99})

    def test_local_config_migrates_to_local_dir_and_gitignore(self):
        self.write(self.root, ".sstack/config.toml", '[dispatch]\nvia = "headless"\n')
        local = self.write(self.root, ".sstack/config.local.toml",
                           '[role.implement]\nharness = "codex"\nmodel = "mine"\n'
                           '[project]\nverify = "mine"\n')
        self.run_cli("migrate", "--repo")
        self.assertFalse(local.exists())
        self.assertEqual((self.root / ".sstack/config.local.toml.bak").read_text(),
                         '[role.implement]\nharness = "codex"\nmodel = "mine"\n'
                         '[project]\nverify = "mine"\n')
        self.assertEqual(C.load(self.root)["role"]["implement"],
                         {"harness": "codex", "model": "mine"})
        self.assertEqual(C.source(self.root, "project", None)[0], "local")
        self.assertIn(".sstack/local/", (self.root / ".gitignore").read_text().splitlines())

    def test_all_or_nothing_on_target_collision(self):
        cfg = self.copy_global()
        before = cfg.read_bytes()
        self.write(self.home, ".sstack/roles/implement.toml", 'harness = "codex"\n')
        err = self.run_cli("migrate", "--global", code=1)
        self.assertIn("target exists", err)
        self.assertEqual(cfg.read_bytes(), before)
        self.assertFalse((cfg.parent / "config.toml.bak").exists())
        self.assertFalse((cfg.parent / "harnesses").exists())

    def test_bad_toml_and_no_legacy(self):
        self.write(self.home, ".sstack/config.toml", "[harness.pi\n")
        self.assertIn("config.toml", self.run_cli("migrate", "--global", code=1))
        (self.home / ".sstack/config.toml").unlink()
        self.assertEqual(self.run_cli("migrate", "--global"), "no legacy config\n")

    def test_show(self):
        self.copy_global()
        self.copy_unibuz()
        self.run_cli("migrate")
        roles = self.run_cli("show", "roles/review")
        self.assertTrue(roles.startswith("# home: "), roles)
        self.assertIn("panel = [", roles)
        project = self.run_cli("show", "project")
        self.assertTrue(project.startswith("# repo: "), project)
        self.assertIn('verify = [', project)
        every = self.run_cli("show")
        self.assertIn("roles/review  home  ", every)
        self.assertIn("ades/t3  defaults  ", every)
        config = self.run_cli("show", "config")
        self.assertIn("# defaults: ", config)
        self.assertIn("# home: ", config)
        self.assertIn('[dispatch]\nvia = "auto"', config)

    def test_show_missing_exits_one(self):
        self.assertEqual(self.run_cli("show", "roles/nope", code=1).strip(),
                         "no roles/nope in any layer")

    def test_repo_flag_outside_git(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("not in a git repository", self.run_cli("migrate", "--repo", cwd=d, code=1))

    def test_default_outside_git_migrates_home(self):
        self.copy_global()
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("next: sstack-doctor", self.run_cli("migrate", cwd=d))
        self.assertTrue((self.home / ".sstack/harnesses/pi.toml").is_file())

    def test_home_equal_repo_migrates_config_local(self):
        shutil.copy(DATA / "global.toml", self.write(self.root, ".sstack/config.toml", ""))
        self.write(self.root, ".sstack/config.local.toml", '[role.implement]\nharness = "codex"\n')
        env = dict(os.environ, HOME=str(self.home), SSTACK_HOME=str(self.root / ".sstack"))
        r = subprocess.run([sys.executable, str(CLI), "migrate"], cwd=str(self.root),
                           env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.root / ".sstack/local/roles/implement.toml").is_file())

    def test_names_the_loader_cannot_hold_are_refused_before_any_write(self):
        for name in ("nested/name", "../../escape", "", ".hidden", ".."):
            with self.subTest(name=name):
                cfg = self.write(self.home, ".sstack/config.toml",
                                 f'[role."{name}"]\nharness = "codex"\n')
                before = cfg.read_bytes()
                err = self.run_cli("migrate", "--global", code=1)
                self.assertIn("bad role name", err)
                self.assertEqual(cfg.read_bytes(), before)
                self.assertFalse((cfg.parent / "config.toml.bak").exists())
                self.assertFalse((cfg.parent / "roles").exists())
                self.assertFalse((self.home / "escape.toml").exists())
                self.assertFalse((self.home.parent / "escape.toml").exists())
                cfg.unlink()

    def test_a_planned_path_must_stay_inside_its_layer(self):
        cfg = self.write(self.home, ".sstack/config.toml", '[role.scout]\nharness = "codex"\n')
        escaping = {"roles/../../../escape.toml": 'harness = "codex"\n'}
        with mock.patch.object(M, "_safe_split", lambda *a: (escaping, [])):
            with self.assertRaises(M.MigrationError) as caught:
                M._plan([("home", cfg.parent)])
        self.assertIn("outside", str(caught.exception))
        self.assertFalse((self.home.parent / "escape.toml").exists())

    def test_a_failed_write_never_truncates_the_gitignore(self):
        gi = self.write(self.root, ".gitignore", "valuable-existing-rule\n")
        local = self.write(self.root, ".sstack/config.local.toml",
                           '[role.implement]\nharness = "codex"\n')
        real = os.replace

        def replace(src, dst):
            if str(dst).endswith(".gitignore"):
                Path(src).write_text("TRUNCATED")  # what a half-written file would look like
                raise OSError("disk full")
            real(src, dst)

        err, plan = io.StringIO(), io.StringIO()
        with mock.patch.object(M.os, "replace", replace), contextlib.redirect_stderr(err), \
                contextlib.redirect_stdout(plan):
            self.assertEqual(M.migrate(C.git_root(self.root), "repo"), 1)
        self.assertIn("error: disk full", err.getvalue())
        self.assertEqual(gi.read_text(), "valuable-existing-rule\n")
        self.assertEqual([x.name for x in self.root.iterdir() if ".tmp" in x.name], [])
        self.assertTrue(local.is_file())
        self.assertFalse((self.root / ".sstack/local/roles/implement.toml").exists())

    def test_a_failed_restore_is_reported_with_a_recovery_line(self):
        text = '[role.scout]\nharness = "claude"\n\n[dispatch]\nvia = "local"\n'
        cfg = self.write(self.home, ".sstack/config.toml", text)
        real_replace, real_rename = os.replace, Path.rename

        def replace(src, dst):
            if str(dst) == str(cfg):  # the deferred write of config.toml, after the rename
                raise OSError("write failed")
            real_replace(src, dst)

        def rename(self_, target):
            if str(target).endswith(".bak"):
                return real_rename(self_, target)
            raise OSError("restore denied")

        err, plan = io.StringIO(), io.StringIO()
        with mock.patch.object(M.os, "replace", replace), \
                mock.patch.object(Path, "rename", rename), contextlib.redirect_stderr(err), \
                contextlib.redirect_stdout(plan):
            self.assertEqual(M.migrate(None, "global"), 1)
        out = err.getvalue()
        self.assertIn("error: write failed", out)
        self.assertIn("error: rollback failed", out)
        self.assertIn(f"recover: mv {cfg}.bak {cfg}", out)
        self.assertFalse(cfg.exists())
        self.assertEqual((cfg.parent / "config.toml.bak").read_text(), text)

    def test_first_diff_is_type_aware_and_sees_an_empty_root_key(self):
        self.assertIsNotNone(M._first_diff(True, 1))
        self.assertIsNotNone(M._first_diff(1, 1.0))
        self.assertIsNotNone(M._first_diff({"": 1}, {}))
        self.assertIsNone(M._first_diff({"a": [1, {"b": 2.5}]}, {"a": [1, {"b": 2.5}]}))
        self.assertEqual(M._first_diff({"a": {"b": [1, 2]}}, {"a": {"b": [1, 3]}}), "a.b.1")

    def test_safe_split_refuses_a_changed_type(self):
        src = self.write(self.home, ".sstack/config.toml", "[rules]\nmax_parallel = true\n")
        wrong = {"config.toml": "[rules]\nmax_parallel = 1\n"}
        with mock.patch.object(M, "_split_legacy", lambda *a: (wrong, [])):
            with self.assertRaises(M.MigrationError):
                M._safe_split(src, tomllib.loads(src.read_text()), "home")

    def test_safe_split_refuses_a_lost_empty_root_key(self):
        src = self.home / ".sstack/config.toml"
        data = {"": 1, "role": {"scout": {"harness": "codex"}}}
        only_role = {"roles/scout.toml": 'harness = "codex"\n'}
        with mock.patch.object(M, "_split_legacy", lambda *a: (only_role, [])):
            with self.assertRaises(M.MigrationError):
                M._safe_split(src, data, "home")

    def test_transport_date_leaves_are_noted_not_crashed(self):
        self.write(self.home, ".sstack/config.toml",
                   "[transport]\ncustom = 2026-01-01\nwhen = 2026-01-01T10:00:00Z\n")
        out = self.run_cli("migrate", "--global")
        self.assertIn("note: dropped transport.custom = 2026-01-01", out)
        self.assertIn("note: dropped transport.when = 2026-01-01 10:00:00+00:00", out)

    def test_an_unexpected_plan_error_exits_one_without_a_traceback(self):
        self.write(self.home, ".sstack/config.toml", '[role.scout]\nharness = "claude"\n')
        err = io.StringIO()
        with mock.patch.object(M, "_plan", side_effect=RuntimeError("boom")), \
                contextlib.redirect_stderr(err):
            self.assertEqual(M.migrate(None, "global"), 1)
        self.assertEqual(err.getvalue().strip(), "error: boom")

    def test_a_comment_block_above_a_header_moves_with_it(self):
        self.write(self.home, ".sstack/config.toml", """\
[reflect]
enabled = true

# strong tier: the big model
[tier.strong]
harness = "claude"
model = "opus"
""")
        self.run_cli("migrate", "--global")
        tier = (self.home / ".sstack/tiers/strong.toml").read_text()
        self.assertTrue(tier.startswith("# strong tier: the big model\n"), tier)
        self.assertNotIn("strong tier", (self.home / ".sstack/config.toml").read_text())
        self.assertEqual(C.load(None)["tier"]["strong"]["model"], "opus")
