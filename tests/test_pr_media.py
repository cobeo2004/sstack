import os, subprocess, sys
from pathlib import Path

from helpers import TempEnv, REPO


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout


class PrMediaTests(TempEnv):
    def setUp(self):
        super().setUp()
        self.origin = self.root.parent / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.origin)], check=True)
        git(self.root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init")
        git(self.root, "remote", "add", "origin", str(self.origin))
        (self.root / ".git/info/exclude").write_text(".sstack/\n")  # as setup does
        self.media = self.root / ".sstack/runs/r1/media"
        self.media.mkdir(parents=True)
        for name in ("before-home.png", "after-home.png", "after-flow.mp4"):
            (self.media / name).write_bytes(b"x")

    def publish(self, *args):
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t", PATH="/usr/bin:/bin")  # no ffmpeg
        r = subprocess.run([sys.executable, str(REPO / "bin/sstack-pr-media"), *args],
                           cwd=self.root, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_pushes_to_media_branch_and_prints_table(self):
        head = git(self.root, "rev-parse", "HEAD")
        branch = git(self.root, "branch", "--show-current")
        out = self.publish("42", *map(str, sorted(self.media.iterdir())), "--repo", "me/app")
        files = git(self.origin, "ls-tree", "-r", "--name-only", "sstack-media").split()
        self.assertEqual(sorted(files), ["pr-42/after-flow.mp4", "pr-42/after-home.png", "pr-42/before-home.png"])
        base = "https://github.com/me/app/blob/sstack-media/pr-42/"
        self.assertIn(f"| home | ![before]({base}before-home.png?raw=true) | ![after]({base}after-home.png?raw=true) |", out)
        self.assertIn(f"[after-flow.mp4]({base}after-flow.mp4?raw=true)", out)
        # the user's checkout is untouched
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), head)
        self.assertEqual(git(self.root, "status", "--porcelain"), "")
        self.assertEqual(git(self.root, "branch", "--show-current"), branch)

    def test_second_publish_keeps_earlier_files(self):
        self.publish("1", str(self.media / "before-home.png"), "--repo", "me/app")
        self.publish("2", str(self.media / "after-home.png"), "--repo", "me/app")
        files = git(self.origin, "ls-tree", "-r", "--name-only", "sstack-media").split()
        self.assertEqual(sorted(files), ["pr-1/before-home.png", "pr-2/after-home.png"])

    def test_dry_run_pushes_nothing(self):
        out = self.publish("42", str(self.media / "after-home.png"), "--repo", "me/app", "--dry-run")
        self.assertIn("would push", out)
        self.assertEqual(git(self.origin, "branch", "--list", "sstack-media"), "")
