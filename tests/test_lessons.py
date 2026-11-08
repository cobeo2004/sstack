import io, os, contextlib, time
from unittest import mock

from helpers import TempEnv
import sstack_lessons as L

THREE = ("# Lessons\n\n"
         "- [pending] seen=1 id=L1 | run pnpm, not npm | evidence: s1\n"
         "- [accepted] seen=2 id=L2 | read .docs first\n"
         "- [encoded] seen=3 id=L3 | no barrel files | encoded: AGENTS.md\n")


class LessonTests(TempEnv):
    def path(self):
        return self.root / ".sstack/lessons.md"

    def test_roundtrip(self):
        items = L.parse(THREE)
        self.assertEqual(L.render(items), THREE)
        les = [i for i in items if isinstance(i, L.Lesson)]
        self.assertEqual([l.id for l in les], ["L1", "L2", "L3"])
        self.assertEqual(les[0].fields, {"evidence": "s1"})
        self.assertEqual((les[2].status, les[2].seen), ("encoded", 3))

    def test_unknown_lines_preserved(self):
        text = "# My heading\n\nrandom note\n- [pending] seen=1 id=L1 | a thing\n  indented free text\n"
        p = self.path(); p.parent.mkdir(parents=True); p.write_text(text)
        L.set_status(p, "L1", "accepted")
        self.assertEqual(p.read_text(), text.replace("[pending]", "[accepted]"))

    def test_add_dedupes_and_counts(self):
        p = self.path()
        L.add(p, "Run pnpm,  not npm", "s1")
        l = L.add(p, "run pnpm, not NPM", "s2")
        self.assertEqual((l.id, l.seen, l.fields["evidence"]), ("L1", 2, "s1; s2"))
        self.assertTrue(p.read_text().startswith("# Lessons\n\n"))
        self.assertEqual(len([i for i in L.parse(p.read_text()) if isinstance(i, L.Lesson)]), 1)

    def test_evidence_pipe_sanitized(self):
        p = self.path()
        L.add(p, "use pnpm", "turn 3 | turn 7")
        L.set_status(p, "L1", "accepted")
        self.assertEqual(L.add(p, "other", None).id, "L2")

    def test_add_with_bad_config_is_one_line(self):
        self.glob_cfg("[reflect\n")
        err = io.StringIO()
        old = os.getcwd(); os.chdir(self.root)
        try:
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = L.main(["add", "x"])
        finally:
            os.chdir(old)
        self.assertEqual(code, 1)
        self.assertIn("config.toml", err.getvalue())
        self.assertEqual(len(err.getvalue().strip().splitlines()), 1)

    def test_ids_increment(self):
        p = self.path()
        self.assertEqual([L.add(p, t, None).id for t in ("a", "b", "c")], ["L1", "L2", "L3"])
        L.forget(p, "L3")
        self.assertEqual(L.add(p, "d", None).id, "L3")  # next after the max present
        L.forget(p, "L1")
        self.assertEqual(L.add(p, "e", None).id, "L4")

    def test_accepted_filters(self):
        p = self.path(); p.parent.mkdir(parents=True); p.write_text(THREE)
        self.assertEqual([l.id for l in L.accepted(p)], ["L2"])
        L.set_status(p, "L1", "encoded", encoded="CLAUDE.md")
        self.assertEqual(L.parse(p.read_text())[2].fields["encoded"], "CLAUDE.md")

    def test_cli_add_prints_encode_at_threshold(self):
        self.glob_cfg("[reflect]\nencode_at = 2\n")
        def cli(*a):
            out = io.StringIO()
            old = os.getcwd(); os.chdir(self.root)
            try:
                with contextlib.redirect_stdout(out):
                    code = L.main(list(a))
            finally:
                os.chdir(old)
            return code, out.getvalue()
        c1, o1 = cli("add", "--scope", "repo", "use pnpm")
        c2, o2 = cli("add", "--scope", "repo", "use pnpm", "--evidence", "x")
        self.assertEqual((c1, o1), (0, "L1 seen=1\n"))
        self.assertEqual((c2, o2), (0, "L1 seen=2\nENCODE\n"))
        self.assertTrue(self.path().exists())


import json, subprocess, sys
from helpers import REPO

FAKE_SCOUT = (f'[harness.fake]\nheadless_readonly = ["{sys.executable}", "{REPO}/tests/fakes/fake_agent.py", "{{model}}"]\n'
              '[role.scout]\nharness = "fake"\nmodel = "lesson"\n')


class ReflectHookTests(TempEnv):
    def hook(self, payload, *args, env=None):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("T3CODE", "SSTACK_"))}
        e.update(HOME=str(self.home), **(env or {}))
        return subprocess.run([sys.executable, str(REPO / "bin/sstack-reflect-hook"), *args],
                              input=json.dumps(payload), capture_output=True, text=True, env=e, timeout=60)

    def payload(self):
        t = self.root / "transcript.jsonl"; t.write_text("{}\n")
        return {"transcript_path": str(t), "cwd": str(self.root), "hook_event_name": "SessionEnd"}

    def test_reflect_hook_noop_when_disabled(self):
        self.glob_cfg(FAKE_SCOUT + "[reflect]\nauto = false\n")
        r = self.hook(self.payload(), "--foreground")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.root / ".sstack").exists())

    def test_reflect_hook_adds_pending(self):
        self.glob_cfg(FAKE_SCOUT + "[reflect]\nauto = true\n")
        r = self.hook(self.payload(), "--foreground")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = (self.root / ".sstack/lessons.md").read_text()
        self.assertIn("- [pending] seen=1 id=L1 | run pnpm, not npm | evidence: user said so at turn 4", text)
        self.assertNotIn("accepted", text)
        self.assertFalse((self.home / ".sstack/lessons.md").exists())  # placeholder + bad scope skipped
        brief = next((self.root / ".sstack/runs").glob("reflect-*/scout.brief.md")).read_text()
        self.assertIn("transcript.jsonl", brief)
        self.assertIn("LESSON:", brief)

    def test_reflect_hook_skips_nested_session(self):
        self.glob_cfg(FAKE_SCOUT + "[reflect]\nauto = true\n")
        r = self.hook(self.payload(), "--foreground", env={"SSTACK_REFLECT": "1"})
        self.assertEqual(r.returncode, 0)
        self.assertFalse((self.root / ".sstack").exists())

    def test_reflect_hook_detaches(self):
        self.glob_cfg(FAKE_SCOUT + "[reflect]\nauto = true\n")
        r = self.hook(self.payload())
        self.assertEqual(r.returncode, 0, r.stderr)
        p = self.root / ".sstack/lessons.md"
        for _ in range(100):
            if p.exists() and "L1" in p.read_text():
                break
            time.sleep(0.1)
        self.assertIn("run pnpm", p.read_text())
