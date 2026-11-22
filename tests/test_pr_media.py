import os, subprocess, sys, unittest
from pathlib import Path

from helpers import TempEnv, REPO

# Preserve Windows PATH for Git; POSIX uses system directories.
BASE_PATH = os.environ["PATH"] if os.name == "nt" else "/usr/bin:/bin"


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, encoding="utf-8").stdout


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
        prelude = """import runpy, shutil, sys
which = shutil.which
shutil.which = lambda cmd, *args, **kwargs: None if cmd == 'ffmpeg' else which(cmd, *args, **kwargs)
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
"""
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t", PATH=os.environ.get("SSTACK_TEST_PATH", BASE_PATH))
        r = subprocess.run([sys.executable, "-c", prelude, str(REPO / "bin/sstack-pr-media"), *args],
                           cwd=self.root, env=env, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_pushes_to_media_branch_and_prints_table(self):
        head = git(self.root, "rev-parse", "HEAD")
        branch = git(self.root, "branch", "--show-current")
        out = self.publish("42", *map(str, sorted(self.media.iterdir())), "--repo", "me/app")
        files = git(self.origin, "ls-tree", "-r", "--name-only", "sstack-media").split()
        self.assertEqual(sorted(files), ["pr-42/after-flow.mp4", "pr-42/after-home.png", "pr-42/before-home.png"])
        base = "https://github.com/me/app/blob/sstack-media/pr-42/"
        self.assertIn("<tr><th>Before</th><th>After</th></tr>", out)
        self.assertIn('<tr><td colspan="2"><b>home</b></td></tr>', out)
        self.assertIn(f'<tr><td><img src="{base}before-home.png?raw=true" alt="before-home.png"></td>'
                      f'<td><img src="{base}after-home.png?raw=true" alt="after-home.png"></td></tr>', out)
        self.assertTrue(out.startswith("<!-- sstack-media -->\n") and out.rstrip().endswith("<!-- /sstack-media -->"))
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

    def test_mermaid_diagrams_render_inline(self):
        (self.media / "before-checkout.mmd").write_text("sequenceDiagram\n  A->>B: charge\n")
        (self.media / "after-checkout.mmd").write_text("sequenceDiagram\n  A->>Q: enqueue\n  Q->>B: charge\n")
        out = self.publish("42", str(self.media / "before-checkout.mmd"), str(self.media / "after-checkout.mmd"),
                           "--repo", "me/app", "--dry-run")
        # side by side in one row; blank lines around each fence so GitHub renders it inside the <td>
        self.assertIn('<tr><td colspan="2"><b>checkout</b></td></tr>\n'
                      "<tr><td>\n\n```mermaid\nsequenceDiagram\n  A->>B: charge\n```\n\n</td>"
                      "<td>\n\n```mermaid\nsequenceDiagram\n  A->>Q: enqueue\n  Q->>B: charge\n```\n\n</td></tr>", out)
        self.assertNotIn("Other:", out)

    def test_new_flow_has_empty_before(self):
        (self.media / "after-sync.mmd").write_text("flowchart LR\n  A-->B\n")
        out = self.publish("42", str(self.media / "after-sync.mmd"), "--repo", "me/app", "--dry-run")
        self.assertIn("<tr><td>—</td><td>\n\n```mermaid\nflowchart LR", out)

    @unittest.skipIf(os.name == "nt", "fake gh is a sh script Windows cannot run as `gh`")
    def test_edit_body_appends_then_replaces(self):
        # fake gh: `pr view` prints the stored body, `pr edit --body-file -` stores stdin
        bin_dir = self.root.parent / "bin"; bin_dir.mkdir()
        store = self.root.parent / "body.md"; store.write_text("## Summary\nDoes a thing.\n")
        gh = bin_dir / "gh"
        gh.write_text(f"""#!/bin/sh
case "$2" in
  view) cat '{store}' ;;
  edit) cat > '{store}' ;;
esac
""")
        gh.chmod(0o755)
        os.environ["SSTACK_TEST_PATH"] = f"{bin_dir}{os.pathsep}{BASE_PATH}"
        try:
            self.publish("42", str(self.media / "after-home.png"), "--repo", "me/app", "--edit-body")
            first = store.read_text(encoding="utf-8")
            self.assertTrue(first.startswith("## Summary\nDoes a thing.\n\n<!-- sstack-media -->"))
            self.publish("42", str(self.media / "before-home.png"), "--repo", "me/app", "--edit-body")
            second = store.read_text(encoding="utf-8")
        finally:
            del os.environ["SSTACK_TEST_PATH"]
        self.assertEqual(second.count("<!-- sstack-media -->"), 1)
        self.assertIn("before-home.png", second)
        self.assertNotIn("after-home.png", second)
        self.assertTrue(second.startswith("## Summary\nDoes a thing.\n"))

    def test_unprefixed_diagram_kept_and_no_empty_table(self):
        (self.media / "queue.mmd").write_text("flowchart LR\n  A-->B\n")
        out = self.publish("42", str(self.media / "queue.mmd"), "--repo", "me/app", "--dry-run")
        self.assertIn("<b>queue</b>", out)
        out = self.publish("42", str(self.media / "after-flow.mp4"), "--repo", "me/app", "--dry-run")
        self.assertNotIn("<table>", out)

    def test_stray_start_marker_never_eats_user_text(self):
        import runpy
        m = runpy.run_path(str(REPO / "bin/sstack-pr-media"))
        body, s = "Summary\n<!-- sstack-media -->\nKEEP\n", m["table"]("", [])
        twice = m["replace_section"](m["replace_section"](body, s), s)
        self.assertIn("KEEP", twice)
        self.assertEqual(twice.count("<!-- /sstack-media -->"), 1)

    def test_names_are_escaped(self):
        import runpy
        out = runpy.run_path(str(REPO / "bin/sstack-pr-media"))["table"]("https://e/", ['after-a"b<c>.png'])
        self.assertIn('src="https://e/after-a%22b%3Cc%3E.png?raw=true"', out)
        self.assertIn('alt="after-a&quot;b&lt;c&gt;.png"', out)
        self.assertIn("<b>a&quot;b&lt;c&gt;</b>", out)
