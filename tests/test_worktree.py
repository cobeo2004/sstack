import os, subprocess
from pathlib import Path

from helpers import TempEnv, REPO

BIN = REPO / "bin" / "sstack-worktree"


class WorktreeTests(TempEnv):
    def setUp(self):
        super().setUp()
        g = lambda *a: subprocess.run(["git", "-C", str(self.root), *a], check=True,
                                      capture_output=True)
        g("config", "user.email", "t@t"); g("config", "user.name", "t")
        self.write(self.root, ".gitignore", ".env\nnode_modules/\nsecret.key\n*.local\n")
        g("add", "."); g("commit", "-qm", "init")
        self.write(self.root, ".env", "A=1\n")
        self.write(self.root, "secret.key", "k\n")
        self.write(self.root, "node_modules/x.js", "x\n")
        self.write(self.root, "café.local", "c\n")
        (self.root / "dead.local").symlink_to("/nonexistent")
        self.write(self.root, "notes.md", "wip\n")
        self.write(self.root, ".worktreeinclude", ".env\n*.local\nnode_modules/\nnotes.md\n")
        self.wt = self.root.parent / "wt"
        g("worktree", "add", "-q", "-b", "feat", str(self.wt))

    def run_in(self, cwd, *args):
        return subprocess.run([str(BIN), *args], cwd=cwd, capture_output=True, text=True)

    def test_status_reports_missing_ignored(self):
        out = self.run_in(self.wt).stdout
        self.assertIn("linked: True", out)
        self.assertIn("branch: feat", out)
        self.assertIn("missing_files: .env, café.local, dead.local, secret.key", out)
        self.assertIn("missing_dirs: node_modules/", out)
        self.assertIn("copyable: .env, café.local", out)
        self.assertIn("node_modules/ (directory", out)
        self.assertIn("notes.md (not gitignored)", out)
        self.assertIn("dead.local (symlink", out)

    def test_copy_only_included_and_never_overwrites(self):
        self.assertIn("would copy  .env", self.run_in(self.wt, "copy", "--dry-run").stdout)
        self.assertFalse((self.wt / ".env").exists())
        r = self.run_in(self.wt, "copy")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("copied  .env", r.stdout)
        self.assertEqual((self.wt / ".env").read_text(), "A=1\n")
        self.assertEqual((self.wt / "café.local").read_text(), "c\n")
        for absent in ("notes.md", "dead.local", "node_modules"):
            self.assertFalse(os.path.lexists(self.wt / absent), absent)
        self.assertFalse((self.wt / "secret.key").exists())
        (self.wt / ".env").write_text("LOCAL\n")
        self.assertIn("exists  .env", self.run_in(self.wt, "copy").stdout)
        self.assertEqual((self.wt / ".env").read_text(), "LOCAL\n")
        self.assertIn("copyable: none", self.run_in(self.wt).stdout)

    def test_copy_refuses_in_primary(self):
        r = self.run_in(self.root, "copy")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("primary checkout", r.stderr)
        self.assertIn("linked: False", self.run_in(self.root).stdout)
