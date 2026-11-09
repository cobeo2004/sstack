"""Skills per role, kind and path (docs/spec/dispatch.md#skills, R19-R22): resolve, brief, warnings."""
import json
from pathlib import Path

from helpers import REPO
from test_dispatch import FAKE, T3, DispatchBase, FakeCliBase
from test_doctor import DoctorBase, roles
import sstack_config as C
import sstack_skills as S

# role skill, kind skill (backend: *.py), practices skill for web/*, a doc link, one missing skill
CFG = (FAKE + '[role.implement]\nharness="fake"\nmodel="echo"\nskills=["tdd", "ghost"]\n'
       '[skills.kinds]\nbackend=["py-style", "tdd"]\n')
PROJECT = '[practices]\n"web/*" = ["react-way", "docs/web.md"]\n"api/*" = ["never"]\n'


class SkillBase(DispatchBase):
    def setUp(self):
        super().setUp()
        self.glob_cfg(CFG)
        self.write(self.root, ".sstack/project.toml", PROJECT)
        for n in ("tdd", "py-style"):
            self.write(self.root, f".agents/skills/{n}/SKILL.md", f"# {n}\n")
        self.write(self.home, ".claude/skills/react-way/SKILL.md", "# react\n")  # claude's harness dir
        self.write(self.root, ".claude/skills/tdd/SKILL.md", "# shadowed\n")  # .agents/skills comes first


class ResolveTests(SkillBase):
    def test_relative_skill_dir_is_absolute_under_repo(self):
        import os
        self.write(self.root, "vendor/skills/local-one/SKILL.md", "# l\n")
        cfg = {"harness": {"custom": {"skill_dirs": ["vendor/skills"]}},
               "role": {"implement": {"skills": ["local-one"]}}}
        old = os.getcwd()
        os.chdir(self.home)  # dispatch run from somewhere else
        try:
            found, missing = S.resolve(cfg, self.root, "implement", None, [], ["custom"])
        finally:
            os.chdir(old)
        self.assertEqual(missing, [])
        self.assertEqual(found[0][1], str((self.root / "vendor/skills/local-one/SKILL.md").resolve()))

    def test_union_order_dedupe_and_missing(self):
        cfg = C.load(self.root)
        cfg["harness"]["claude"] = {}
        found, missing = S.resolve(cfg, self.root, "implement", "backend", ["web/a.py"], ["claude"])
        self.assertEqual([n for n, _ in found], ["tdd", "py-style", "react-way", "docs/web.md"])
        self.assertEqual(dict(found)["tdd"], str(self.root / ".agents/skills/tdd/SKILL.md"))
        self.assertEqual(dict(found)["react-way"], str(self.home / ".claude/skills/react-way/SKILL.md"))
        self.assertEqual(dict(found)["docs/web.md"], str(self.root / "docs/web.md"))  # doc: passed through
        self.assertEqual(missing, ["ghost"])

    def test_sstack_skills_last_and_harness_skill_dirs_key(self):
        cfg = C.load(self.root)
        cfg["role"]["implement"]["skills"] = ["work", "mine"]
        cfg["harness"]["fake"]["skill_dirs"] = [str(self.root / "elsewhere")]
        self.write(self.root, "elsewhere/mine/SKILL.md", "x")
        found, missing = S.resolve(cfg, self.root, "implement", None, [], ["fake"])
        self.assertEqual(found, [("work", str(REPO / "skills/work/SKILL.md")),
                                 ("mine", str(self.root / "elsewhere/mine/SKILL.md"))])
        self.assertEqual(missing, [])

    def test_none_configured(self):
        self.assertEqual(S.resolve(C.load(self.root), self.root, "scout", "docs", ["a.md"], []), ([], []))


class DispatchSkillTests(SkillBase):
    def go(self, *extra, env=None):
        return self.run_main("implement", "--brief", self.brief("hello brief"), "--report", str(self.report()),
                             "--files", "web/a.py", *extra, env=env)

    def test_dry_run_lists_skills_and_missing(self):
        code, out, _ = self.go("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn(f"skills: tdd {self.root / '.agents/skills/tdd/SKILL.md'}", out)
        self.assertIn(f"skills: read {self.root / 'docs/web.md'}", out)
        self.assertIn("missing skill: ghost", out)
        self.assertNotIn("never", out)
        self.assertFalse((self.root / ".sstack/runs").exists())

    def test_headless_brief_stderr_index(self):
        code, _, err = self.go()
        self.assertEqual(code, 0, err)
        text = self.report().read_text()
        self.assertIn("hello brief", text)
        self.assertIn("## Skills to use", text)
        self.assertIn(f"- `py-style`: {self.root / '.agents/skills/py-style/SKILL.md'}", text)
        self.assertIn("`ghost` not installed — carry on without it", text)
        self.assertIn("sstack-dispatch: skill ghost not found", err)
        rec = json.loads((self.root / ".sstack/runs/index.jsonl").read_text().splitlines()[0])
        self.assertEqual(rec["skills"], ["tdd", "py-style", "docs/web.md"])  # react-way: fake has no claude dir
        self.assertEqual(rec["skills_missing"], ["ghost", "react-way"])
        run = json.loads((self.root / rec["run_dir"] / "run.json").read_text())
        self.assertEqual(run["brief"], f"{rec['run_dir']}/brief.skills.md")
        self.assertIn("hello brief", (self.root / "b.md").read_text())
        self.assertNotIn("Skills", (self.root / "b.md").read_text())  # the original brief is untouched

    def test_no_skills_brief_untouched(self):
        self.glob_cfg(FAKE + '[role.implement]\nharness="fake"\nmodel="echo"\n')
        (self.root / ".sstack/project.toml").unlink()
        code, _, err = self.go()
        self.assertEqual(code, 0, err)
        rec = json.loads((self.root / ".sstack/runs/index.jsonl").read_text().splitlines()[0])
        self.assertNotIn("skills", rec)
        self.assertEqual(json.loads((self.root / rec["run_dir"] / "run.json").read_text())["brief"], "b.md")

    def test_local_exit_3_prints_skills(self):
        code, out, _ = self.go("--via", "local")
        self.assertEqual(code, 3)
        lines = out.splitlines()
        self.assertEqual(lines[0], "local")
        self.assertIn(f"skills: tdd {self.root / '.agents/skills/tdd/SKILL.md'}", lines)
        self.assertIn(f"skills: react-way {self.home / '.claude/skills/react-way/SKILL.md'}", lines)  # every harness
        self.assertIn("missing skill: ghost", lines)


class ToolSkillTests(FakeCliBase):
    def test_payload_points_at_derived_brief_and_escalation_keeps_it(self):
        self.example()
        self.write(self.home, ".sstack/roles/scout.toml", 'harness="claude"\nmodel="haiku"\nskills=["how"]\n')
        code, out, err = self.dispatch("scout", env=T3)
        self.assertEqual(code, 4, err)
        p = json.loads(out)
        derived = Path(p["run_dir"]) / "brief.skills.md"
        self.assertIn(f"Read the brief at {derived} ", p["calls"][0]["args"]["task"])
        self.assertIn(f"- `how`: {REPO / 'skills/how/SKILL.md'}", derived.read_text())
        code, out2, err = self.record(p["calls"][0], 1, env=T3)
        self.assertEqual(code, 4, err)
        esc = (Path(p["run_dir"]) / "brief.escalated.md").read_text()
        self.assertIn("## Skills to use", esc)
        rec = json.loads((self.root / ".sstack/runs/index.jsonl").read_text().splitlines()[0])
        self.assertEqual((rec["skills"], rec["skills_missing"]), (["how"], []))


class DoctorSkillTests(DoctorBase):
    def test_warn_not_fail(self):
        self.glob_cfg(roles() + '[skills.kinds]\nbackend=["ghost-skill"]\n')
        code, out, _ = self.doctor()
        self.assertEqual(code, 0, out)
        self.assertIn("WARN skills resolve: ghost-skill", out)

    def test_pass(self):
        self.glob_cfg(roles() + '[skills.kinds]\nbackend=["how"]\n')
        code, out, _ = self.doctor()
        self.assertEqual(code, 0, out)
        self.assertIn("PASS skills resolve", out)
