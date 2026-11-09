"""bin/sstack-hook: payload normalization per harness (docs/spec/hooks.md), the post-edit check,
and session-end handing the transcript to the reflect hook."""
import contextlib, io, json, os, runpy, shutil, subprocess, sys
from unittest import mock
from pathlib import Path

from helpers import TempEnv, REPO, FIXTURES

HOOK = REPO / "bin" / "sstack-hook"
PAYLOADS = FIXTURES / "payloads"
T = "/home/transcripts/session.jsonl"


def payload(name: str, root: Path) -> str:
    return (PAYLOADS / f"hook-{name}.json").read_text().replace("/repo", str(root))


class HookTests(TempEnv):
    def hook(self, event, harness, stdin, *extra, bin_=HOOK):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("T3CODE", "SSTACK_"))}
        e["HOME"] = str(self.home)
        return subprocess.run([sys.executable, str(bin_), event, "--harness", harness, *extra],
                              input=stdin, capture_output=True, text=True, env=e, cwd=self.root, timeout=60)

    def normalized(self, event, harness, name):
        r = self.hook(event, harness, payload(name, self.root), "--print-normalized")
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_normalizes_every_harness(self):
        a = str(self.root / "a.txt")
        cases = [("post-edit", "claude", "claude-post-edit", T, [a]),
                 ("post-edit", "codex", "codex-post-edit-add", T, [a]),
                 ("post-edit", "codex", "codex-post-edit-update", T, [a]),
                 ("post-edit", "cursor", "cursor-post-edit", T, [a]),
                 ("post-edit", "pi", "pi-post-edit", T, [a]),
                 ("session-end", "claude", "claude-session-end", T, []),
                 ("session-end", "codex", "codex-session-end", T, []),
                 ("session-end", "cursor", "cursor-session-end", T, []),
                 ("session-end", "cursor", "cursor-session-end-no-transcript", None, []),
                 ("session-end", "pi", "pi-session-end", T, [])]
        for event, harness, name, transcript, files in cases:
            with self.subTest(name):
                self.assertEqual(self.normalized(event, harness, name),
                                 {"harness": harness, "event": event, "cwd": str(self.root),
                                  "transcript": transcript, "files": files})

    def test_codex_patch_lists_every_written_file(self):
        patch = ("*** Begin Patch\n*** Add File: new.py\n+x\n*** Update File: src/old.py\n@@\n-a\n+b\n"
                 "*** Update File: mv.py\n*** Move to: moved.py\n*** Delete File: gone.py\n*** End Patch")
        p = {"cwd": str(self.root), "tool_name": "apply_patch", "tool_input": {"command": patch}}
        r = self.hook("post-edit", "codex", json.dumps(p), "--print-normalized")
        self.assertEqual(json.loads(r.stdout)["files"],
                         [str(self.root / f) for f in ("new.py", "src/old.py", "mv.py", "moved.py")])

    def project(self, check):
        self.write(self.root, ".sstack/project.toml", f"check = {json.dumps(check)}\n")
        (self.root / "a.txt").write_text("hello\n")
        self.write(self.home, ".sstack/repos.txt", f"{self.root}\n")

    def test_unregistered_repo_never_runs_check(self):
        self.project("touch ran")
        (self.home / ".sstack/repos.txt").unlink()
        r = self.hook("post-edit", "claude", payload("claude-post-edit", self.root))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("check skipped", r.stderr)
        self.assertFalse((self.root / "ran").exists())

    def test_check_failure_feeds_back(self):
        self.project("false {path}")
        for harness, name in (("claude", "claude-post-edit"), ("codex", "codex-post-edit-update"),
                              ("pi", "pi-post-edit")):
            with self.subTest(harness):
                r = self.hook("post-edit", harness, payload(name, self.root))
                self.assertEqual(r.returncode, 2)
                self.assertIn("a.txt", r.stderr)

    def test_cursor_failure_does_not_block(self):
        self.project("false {path}")
        r = self.hook("post-edit", "cursor", payload("cursor-post-edit", self.root))
        self.assertEqual(r.returncode, 0)
        self.assertIn("a.txt", r.stderr)

    def test_check_gets_repo_relative_quoted_path(self):
        self.project("echo {path} >> seen.txt")
        (self.root / "a b.txt").write_text("")
        p = {"cwd": str(self.root), "tool_input": {"file_path": str(self.root / "a b.txt")}}
        r = self.hook("post-edit", "claude", json.dumps(p))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.root / "seen.txt").read_text(), "a b.txt\n")

    def test_path_is_never_parsed_as_shell(self):
        self.project('printf "%s\\n" "{path}" >> seen.txt')
        name = "$(touch pwned).txt"
        (self.root / name).write_text("")
        p = {"cwd": str(self.root), "tool_input": {"file_path": str(self.root / name)}}
        r = self.hook("post-edit", "claude", json.dumps(p))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.root / "pwned").exists())
        self.assertEqual((self.root / "seen.txt").read_text(), name + "\n")

    def test_slow_check_times_out_as_a_failure(self):
        self.project("sleep 5")
        (self.root / "a.txt").write_text("")
        f = runpy.run_path(str(HOOK))["post_edit"]
        with mock.patch.dict(f.__globals__, TIMEOUT=0.2), contextlib.redirect_stderr(io.StringIO()) as err:
            code = f({"cwd": str(self.root), "harness": "claude", "files": [str(self.root / "a.txt")]})
        self.assertEqual(code, 2)
        self.assertIn("timed out", err.getvalue())

    def test_no_check_or_missing_file_passes(self):
        r = self.hook("post-edit", "claude", payload("claude-post-edit", self.root))
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.write(self.root, ".sstack/project.toml", 'check = "false {path}"\n')
        self.write(self.home, ".sstack/repos.txt", f"{self.root}\n")
        r = self.hook("post-edit", "claude", payload("claude-post-edit", self.root))  # a.txt not on disk
        self.assertEqual(r.returncode, 0, r.stderr)

    def stub_reflect(self):
        """A copy of sstack-hook next to a stub sstack-reflect-hook that saves what it was given."""
        src = self.home / "sstack"
        (src / "bin").mkdir(parents=True)
        shutil.copy(HOOK, src / "bin")
        (src / "lib").symlink_to(REPO / "lib")
        got = self.home / "reflect-got.json"
        (src / "bin" / "sstack-reflect-hook").write_text(
            f"import sys, pathlib\npathlib.Path({str(got)!r}).write_text(sys.stdin.read())\n")
        return src / "bin" / "sstack-hook", got

    def test_session_end_starts_reflect_with_transcript(self):
        bin_, got = self.stub_reflect()
        for harness in ("claude", "codex", "cursor", "pi"):
            with self.subTest(harness):
                got.unlink(missing_ok=True)
                r = self.hook("session-end", harness, payload(f"{harness}-session-end", self.root), bin_=bin_)
                self.assertEqual(r.returncode, 0, r.stderr)
                sent = json.loads(got.read_text())
                self.assertEqual((sent["cwd"], sent["transcript_path"]), (str(self.root), T))
                self.assertTrue(sent["session_id"])

    def test_session_end_without_transcript_skips(self):
        bin_, got = self.stub_reflect()
        r = self.hook("session-end", "cursor", payload("cursor-session-end-no-transcript", self.root), bin_=bin_)
        self.assertEqual(r.returncode, 0)
        self.assertIn("reflect: skipped (no transcript)", r.stderr)
        self.assertFalse(got.exists())

    def test_bad_input_never_fails_the_session(self):
        for stdin in ("not json", "[]", ""):
            r = self.hook("post-edit", "claude", stdin)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_pi_extension_calls_the_hook(self):
        ts = (REPO / "defaults" / "hooks" / "pi-sstack.ts").read_text()
        for needle in ("tool_result", "session_shutdown", "sstack-hook", "post-edit", "session-end",
                       "isError"):
            self.assertIn(needle, ts)
