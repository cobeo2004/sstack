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

    def panel_hook(self, agent_src):
        agent = self.home / "agent.py"
        agent.write_text("import sys; sys.stdin.read(); m = sys.argv[1]\n" + agent_src)
        h = f'["{sys.executable}", "{agent}", "{{model}}"]'
        self.glob_cfg(f'[harness.fake]\nheadless_readonly = {h}\n'
                      '[role.scout]\npanel=[{harness="fake",model="good"},{harness="fake",model="bad"}]\n'
                      '[reflect]\nauto = true\n')
        r = self.hook(self.payload(), "--foreground")
        self.assertEqual(r.returncode, 0, r.stderr)
        return (self.root / ".sstack/lessons.md").read_text()

    def test_reflect_hook_skips_failed_panel_member(self):
        text = self.panel_hook("print('LESSON: repo | from ' + m + ' | why')\nsys.exit(m == 'bad')\n")
        self.assertIn("from good", text)
        self.assertNotIn("from bad", text)  # its report exists but the index marks it a gap

    def test_reflect_hook_dedupes_like_the_store(self):
        text = self.panel_hook("print('LESSON: repo | ' + ('Use pnpm' if m == 'good' else 'use   PNPM') + ' | why')\n")
        self.assertIn("seen=1", text)
        self.assertNotIn("seen=2", text)


class LessonScopeTests(TempEnv):
    """R10: a lesson may be pinned to path globs and records the commit it was learned at."""

    def git(self, *a):
        return subprocess.run(["git", "-C", str(self.root), "-c", "user.email=t@t", "-c", "user.name=t", *a],
                              capture_output=True, text=True, check=True).stdout.strip()

    def commit(self, msg="i"):
        self.git("add", "-A")
        self.git("commit", "-qm", msg, "--allow-empty")
        return self.git("rev-parse", "--short", "HEAD")

    def path(self):
        return self.root / ".sstack/lessons.md"

    def cli(self, *a):
        out = io.StringIO()
        old = os.getcwd(); os.chdir(self.root)
        try:
            with contextlib.redirect_stdout(out):
                code = L.main(list(a))
        finally:
            os.chdir(old)
        return code, out.getvalue()

    def add(self, text, **kw):
        return L.add(self.path(), text, None, **kw)

    def stored(self, lesson_id):
        return next(i for i in L.parse(self.path().read_text())
                    if isinstance(i, L.Lesson) and i.id == lesson_id)

    def test_add_stores_path_globs_and_commit(self):
        sha = self.commit()
        l = self.add("pin it", paths=["web/**", "lib/*.py"], commit=sha)
        self.assertEqual(l.fields, {"path": "web/**, lib/*.py", "commit": sha})
        self.assertEqual(self.stored("L1").fields, l.fields)  # round-trips through the file

    def test_stale_with_non_ascii_name(self):
        (self.root / "café.py").write_text("a")
        sha = self.commit()
        l = self.add("accents", paths=["café.py"], commit=sha)
        (self.root / "café.py").write_text("b")
        self.commit("c2")
        self.assertIn("café.py", L.changed_since(self.root, sha))
        self.assertTrue(L.is_stale(self.stored(l.id), self.root))

    def test_glob_with_comma_survives(self):
        l = self.add("bracket", paths=["src/[a,b].py"])
        self.assertTrue(L.applies(self.stored(l.id), ["src/a.py"]))

    def test_resighting_never_narrows_a_repo_wide_lesson(self):
        l = self.add("everywhere")
        self.add("everywhere", paths=["web/**"], commit="1234567")
        s = self.stored(l.id)
        self.assertNotIn("path", s.fields)
        self.assertTrue(L.applies(s, ["api/x.py"]))

    def test_cli_add_records_head_commit(self):
        sha = self.commit()
        code, _ = self.cli("add", "use pnpm", "--path", "web/**")
        self.assertEqual(code, 0)
        self.assertEqual(self.stored("L1").fields, {"path": "web/**", "commit": sha})

    def test_cli_add_without_a_commit_records_no_commit(self):
        code, _ = self.cli("add", "use pnpm")  # a repo with no HEAD yet
        self.assertEqual(code, 0)
        self.assertEqual(self.stored("L1").fields, {})

    def test_add_again_keeps_existing_scope(self):
        sha = self.commit()
        self.add("pin it", paths=["web/**"], commit=sha)
        l = self.add("pin  it", paths=["api/**"], commit="f00baa1")
        self.assertEqual((l.id, l.seen), ("L1", 2))
        self.assertEqual(l.fields, {"path": "web/**", "commit": sha})

    def test_applies_without_path_matches_anything(self):
        l = L.Lesson("L1", "accepted", 1, "x")
        self.assertTrue(L.applies(l, ["web/a.tsx"]))
        self.assertTrue(L.applies(l, []))

    def test_applies_matches_any_glob_or_file(self):
        l = L.Lesson("L1", "accepted", 1, "x", {"path": "web/**, *.py"})
        self.assertTrue(L.applies(l, ["web/deep/a.tsx"]))
        self.assertTrue(L.applies(l, ["api/x.py"]))
        self.assertFalse(L.applies(l, ["README.md"]))
        self.assertFalse(L.applies(l, []))

    def test_list_paths_keeps_unscoped_and_matching(self):
        self.add("always")
        self.add("web only", paths=["web/**"])
        self.add("api only", paths=["api/**"])
        code, out = self.cli("list", "--paths", "web/a.tsx", "README.md")
        self.assertEqual(code, 0)
        self.assertIn("always", out)
        self.assertIn("web only", out)
        self.assertNotIn("api only", out)

    def test_list_without_paths_shows_every_lesson(self):
        self.add("web only", paths=["web/**"])
        _, out = self.cli("list")
        self.assertIn("web only", out)

    def test_list_marks_stale_when_its_path_changed(self):
        sha = self.commit()
        self.add("pin it", paths=["web/**"], commit=sha)
        self.write(self.root, "web/a.tsx", "a\n")
        self.commit("touch web")
        _, out = self.cli("list", "--paths", "web/a.tsx")
        self.assertIn("[stale]", out)

    def test_list_not_stale_when_other_files_changed(self):
        sha = self.commit()
        self.add("pin it", paths=["api/**"], commit=sha)
        self.write(self.root, "web/a.tsx", "a\n")
        self.commit("touch web")
        _, out = self.cli("list")
        self.assertNotIn("[stale]", out)

    def test_list_unknown_commit_is_not_stale(self):
        self.add("pin it", paths=["web/**"], commit="f00baa1")
        self.write(self.root, "web/a.tsx", "a\n")
        self.commit("touch web")
        _, out = self.cli("list")
        self.assertIn("pin it", out)
        self.assertNotIn("[stale]", out)
