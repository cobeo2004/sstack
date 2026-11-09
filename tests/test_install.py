import os, shutil, subprocess, sys, tomllib
from pathlib import Path

from helpers import TempEnv, REPO

MARK = "For engineering tasks, start with the sstack skill. <!-- sstack -->"


class InstallTests(TempEnv):
    def setUp(self):
        super().setUp()
        self.src = self.root / "sstack"
        (self.src / "bin").mkdir(parents=True)
        shutil.copy(REPO / "bin/sstack-install", self.src / "bin")
        for s in ("sstack", "work"):
            (self.src / "skills" / s).mkdir(parents=True)
            (self.src / "skills" / s / "SKILL.md").write_text(f"---\nname: {s}\n---\n")
        h = self.home
        (h / ".claude/skills/work").mkdir(parents=True)
        (h / ".claude/skills/work/SKILL.md").write_text("old work")
        (h / ".claude/CLAUDE.md").write_text("# mine\n")
        (h / ".codex/skills").mkdir(parents=True)

    def install(self, *args):
        r = subprocess.run([sys.executable, str(self.src / "bin/sstack-install"), *args],
                           env=dict(os.environ, HOME=str(self.home)), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def snapshot(self):
        return sorted((str(p.relative_to(self.home)), p.is_symlink()) for p in self.home.rglob("*"))

    def test_links_created_in_existing_dirs_only(self):
        self.install()
        for d in (".claude/skills", ".codex/skills"):
            link = self.home / d / "sstack"
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), (self.src / "skills/sstack").resolve())
        self.assertFalse((self.home / ".agents").exists())
        self.assertFalse((self.home / ".cursor").exists())
        self.assertTrue((self.home / ".sstack").is_dir())
        self.assertFalse((self.home / ".sstack/config.toml").exists())

    def test_clash_backed_up(self):
        out = self.install()
        self.assertEqual((self.home / ".claude/skills/work.bak/SKILL.md").read_text(), "old work")
        self.assertTrue((self.home / ".claude/skills/work").is_symlink())
        self.assertIn("SessionEnd", out)

    def test_hook_snippets_for_detected_harnesses_only(self):
        settings = self.home / ".claude/settings.json"
        out = self.install()
        hook = str(self.src / "bin/sstack-hook")
        self.assertIn(f"{hook} post-edit --harness claude", out)
        self.assertIn(f"{hook} post-edit --harness codex", out)
        self.assertIn(f"{hook} session-end --harness codex", out)
        self.assertNotIn("--harness cursor", out)
        self.assertNotIn("pi-sstack.ts", out)
        self.assertFalse(settings.exists())
        self.assertFalse((self.home / ".codex/hooks.json").exists())

    def test_shared_agents_dir_gets_codex_snippet(self):
        shutil.rmtree(self.home / ".codex")
        (self.home / ".agents/skills").mkdir(parents=True)
        out = self.install()
        self.assertEqual(out.count("--harness codex"), 2)  # post-edit + session-end, printed once

    def test_pi_snippet_points_at_extension(self):
        (self.home / ".pi/agent/skills").mkdir(parents=True)
        self.assertIn(str(self.src / "defaults/hooks/pi-sstack.ts"), self.install())
        self.assertFalse((self.home / ".pi/agent/extensions").exists())

    def test_rerun_idempotent(self):
        self.install(); self.install()
        names = sorted(p.name for p in (self.home / ".claude/skills").iterdir())
        self.assertEqual(names, ["sstack", "work", "work.bak"])
        self.assertEqual((self.home / ".claude/CLAUDE.md").read_text().count(MARK), 1)

    def test_marked_line_added_once(self):
        self.install()
        self.assertEqual((self.home / ".claude/CLAUDE.md").read_text(), f"# mine\n\n{MARK}\n")
        self.assertFalse((self.home / ".codex/AGENTS.md").exists())

    def test_uninstall_removes_only_ours(self):
        foreign = self.root / "foreign"; foreign.mkdir()
        (self.home / ".claude/skills/other").symlink_to(foreign)
        self.install()
        out = self.install("--uninstall")
        names = sorted(p.name for p in (self.home / ".claude/skills").iterdir())
        self.assertEqual(names, ["other", "work.bak"])
        self.assertEqual((self.home / ".claude/CLAUDE.md").read_text(), "# mine\n")
        self.assertIn("work.bak", out)

    def test_dry_run_changes_nothing(self):
        before = self.snapshot()
        out = self.install("--dry-run")
        self.assertEqual(self.snapshot(), before)
        self.assertIn("link", out)
        self.assertIn("work.bak", out)

    def test_setup_templates_are_split(self):
        templates = REPO / "skills/setup/templates"
        config = (templates / "config.toml").read_text()
        project = tomllib.loads((templates / "project.toml").read_text())
        self.assertNotIn("[project]", config)
        self.assertIn(".sstack/local/", config)
        self.assertIn("verify", project)
        self.assertIn("test", project)
