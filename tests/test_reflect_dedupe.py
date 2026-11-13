"""Issue #9: reflect sees known lessons, bumps them with SEEN, and reads only new transcript lines."""
import json, os, subprocess, sys
from pathlib import Path

from helpers import TempEnv, REPO
import sstack_lessons as L


class ReflectDedupeTests(TempEnv):
    def setup_agent(self, out: str, code: int = 0, extra: str = ""):
        """A scout that saves the brief it got (and the transcript it was pointed at) and prints `out`."""
        agent = self.home / "agent.py"
        agent.write_text(
            "import re, sys, pathlib\nb = sys.stdin.read()\n"
            f"d = pathlib.Path({str(self.home)!r})\n"
            "n = len(list(d.glob('brief-*.md'))) + 1\n"
            "(d / f'brief-{n}.md').write_text(b)\n"
            "m = re.search(r'^Transcript: (.+)$', b, re.M)\n"
            "(d / f'transcript-{n}.txt').write_text(pathlib.Path(m.group(1)).read_text())\n"
            f"print({out!r})\n{extra}import sys as _s; _s.exit({code})\n")
        self.glob_cfg(f'[harness.fake]\nheadless_readonly = ["{sys.executable}", "{agent}", "{{model}}"]\n'
                      '[role.scout]\nharness = "fake"\nmodel = "x"\n[reflect]\nauto = true\n')

    def hook(self, transcript: Path, session="s1", env=None):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("T3CODE", "SSTACK_"))}
        e["HOME"] = str(self.home)
        e.update(env or {})
        payload = {"transcript_path": str(transcript), "cwd": str(self.root), "session_id": session,
                   "hook_event_name": "SessionEnd"}
        r = subprocess.run([sys.executable, str(REPO / "bin/sstack-reflect-hook"), "--foreground"],
                           input=json.dumps(payload), capture_output=True, text=True, env=e, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)

    def briefs(self):
        return sorted(self.home.glob("brief-*.md"))

    def test_bump_by_id(self):
        p = self.root / ".sstack/wiki/lessons.md"
        L.add(p, "run pnpm, not npm", "s1")
        l = L.bump(p, "L1", "s2")
        self.assertEqual((l.seen, l.fields["evidence"]), (2, "s1; s2"))
        with self.assertRaises(KeyError):
            L.bump(p, "L9", None)

    def test_brief_lists_known_lessons_from_both_scopes(self):
        L.add(self.root / ".sstack/wiki/lessons.md", "run pnpm, not npm", None)
        L.add(self.home / ".sstack/wiki/lessons.md", "keep personal config out of GitHub", None)
        self.setup_agent("NONE\nPASS")
        t = self.root / "t.jsonl"; t.write_text("{}\n")
        self.hook(t)
        b = self.briefs()[0].read_text()
        self.assertIn("repo:L1", b); self.assertIn("run pnpm, not npm", b)
        self.assertIn("global:L1", b); self.assertIn("keep personal config out of GitHub", b)
        self.assertIn("SEEN:", b)

    def test_seen_line_bumps_and_adds_nothing(self):
        p = self.root / ".sstack/wiki/lessons.md"
        L.add(p, "run pnpm, not npm", None)
        self.setup_agent("SEEN: repo:L1 | user said pnpm again\nSEEN: global:L7 | no such lesson\nPASS")
        t = self.root / "t.jsonl"; t.write_text("{}\n")
        self.hook(t)
        les = [i for i in L.parse(p.read_text()) if isinstance(i, L.Lesson)]
        self.assertEqual([(l.id, l.seen) for l in les], [("L1", 2)])
        self.assertFalse((self.home / ".sstack/wiki/lessons.md").exists())

    def test_reflects_only_new_transcript_lines_per_session(self):
        self.setup_agent("NONE\nPASS")
        t = self.root / "t.jsonl"; t.write_text('{"n":1}\n{"n":2}\n')
        self.hook(t)
        self.hook(t)  # resumed session ended again, nothing new: no dispatch
        self.assertEqual(len(self.briefs()), 1)
        with t.open("a") as f:
            f.write('{"n":3}\n')
        self.hook(t)
        self.assertEqual(len(self.briefs()), 2)
        seen = (self.home / "transcript-2.txt").read_text()
        self.assertIn('{"n":3}', seen)
        self.assertNotIn('{"n":1}', seen)
        self.hook(t, session="s2")  # another session id starts from the top
        self.assertIn('{"n":1}', (self.home / "transcript-3.txt").read_text())

    def test_shorter_transcript_resets_offset(self):
        self.setup_agent("NONE\nPASS")
        t = self.root / "t.jsonl"; t.write_text('{"n":1}\n{"n":2}\n')
        self.hook(t)
        t.write_text('{"n":9}\n')  # rewritten (compacted) shorter than what we read
        self.hook(t)
        self.assertIn('{"n":9}', (self.home / "transcript-2.txt").read_text())

    def test_scope_rule_in_capture_brief(self):
        text = (REPO / "skills/reflect/SKILL.md").read_text()
        self.assertIn("even when it is a preference", text)

    def test_failed_scout_does_not_consume_lines(self):
        self.setup_agent("", code=1)
        t = self.root / "t.jsonl"; t.write_text('{"n":1}\n')
        self.hook(t)
        self.hook(t)  # retried: the failed pass read nothing
        self.assertEqual(len(self.briefs()), 2)

    def test_overlapping_session_offsets_survive(self):
        state = self.root / ".sstack/runs/reflect/state.json"
        # while this hook's scout runs, another session's hook saves its offset
        self.setup_agent("NONE\nPASS", extra=f"pathlib.Path({str(state)!r}).write_text('{{\"other\": 5}}')\n")
        t = self.root / "t.jsonl"; t.write_text('{"n":1}\n')
        self.hook(t)
        self.assertEqual(json.loads(state.read_text()), {"other": 5, "s1": 1})

    def test_hook_in_t3_runs_headless(self):
        # a SessionEnd hook has no agent to call delegate_task: it passes --via headless (no exit 4)
        self.setup_agent("NONE\nPASS")
        t = self.root / "t.jsonl"; t.write_text("{}\n")
        self.hook(t, env={"T3CODE_THREAD_ID": "x"})
        self.assertEqual(len(self.briefs()), 1)
        [report] = self.root.glob(".sstack/runs/reflect/*/scout.report.md")
        self.assertIn("NONE", report.read_text())
        self.assertEqual(json.loads((self.root / ".sstack/runs/reflect/state.json").read_text()), {"s1": 1})

    def test_auto_lesson_records_head_commit(self):
        g = ["git", "-C", str(self.root), "-c", "user.email=t@t", "-c", "user.name=t"]
        subprocess.run(g + ["init", "-q"], check=True)
        subprocess.run(g + ["commit", "-q", "--allow-empty", "-m", "i"], check=True)
        sha = subprocess.run(g + ["rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.setup_agent("LESSON: repo | use the api client | t.jsonl\nPASS")
        t = self.root / "t.jsonl"; t.write_text("{}\n")
        self.hook(t)
        les = [i for i in L.parse((self.root / ".sstack/wiki/lessons.md").read_text()) if isinstance(i, L.Lesson)]
        self.assertEqual(les[0].fields.get("commit"), sha)
