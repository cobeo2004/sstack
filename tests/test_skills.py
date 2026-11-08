import re, unittest
from pathlib import Path

from helpers import REPO

SKILLS = REPO / "skills"
FORBIDDEN = ["Agent(", "Task(", "AskUserQuestion", "EnterPlanMode", "ExitPlanMode", "TodoWrite"]
SKILLS_SET = {"sstack", "setup", "work", "grill", "swarm", "review", "unslop", "babysit", "how", "why",
          "diagram", "code-graph", "reflect"}


def skill_files():
    return sorted(SKILLS.glob("*/SKILL.md"))


def frontmatter(text):
    lines = text.split("\n")
    if lines[0] != "---":
        return None
    end = lines.index("---", 1)
    return dict(l.split(": ", 1) for l in lines[1:end] if ": " in l)


def strip_code(text):
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"`[^`\n]*`", "", text)


class SkillLint(unittest.TestCase):
    def test_frontmatter(self):
        self.assertTrue(skill_files())
        for f in skill_files():
            fm = frontmatter(f.read_text())
            self.assertIsNotNone(fm, f)
            self.assertEqual(fm.get("name"), f.parent.name, f)
            self.assertGreater(len(fm.get("description", "")), 20, f)

    def test_length_caps(self):
        for f in skill_files():
            cap = 200 if f.parent.name == "sstack" else 150
            self.assertLessEqual(len(f.read_text().splitlines()), cap, f)
        for f in (SKILLS / "sstack" / "principles").glob("*.md"):
            self.assertLessEqual(len(f.read_text().splitlines()), 30, f)

    def test_testing_surfaces_wired(self):
        t = (SKILLS / "work" / "testing.md").read_text()
        for surface in ("## Code", "## Browser", "## Mobile"):
            self.assertIn(surface, t)
        for f in (SKILLS / "work" / "SKILL.md", SKILLS / "setup" / "SKILL.md"):
            self.assertIn("testing.md", f.read_text(), f)
        self.assertIn("harness-notes/ade.md", t)
        ade = (SKILLS / "sstack" / "harness-notes" / "ade.md").read_text()
        for app in ("## T3 Code", "## Orca", "## Conductor"):
            self.assertIn(app, ade)
        for f in (SKILLS / "sstack" / "harness-notes").glob("*.md"):
            for verb in ("| drive a browser |", "| drive a device |"):
                self.assertIn(verb, f.read_text(), f"{f}: {verb}")

    def test_no_claude_only_tools(self):
        for f in SKILLS.rglob("*.md"):
            if "harness-notes" in f.parts:
                continue
            text = f.read_text()
            for tok in FORBIDDEN:
                self.assertNotIn(tok, text, f"{f}: {tok}")

    def test_relative_links_resolve(self):
        for f in SKILLS.rglob("*.md"):
            for target in re.findall(r"\]\(([^)\s]+)\)", strip_code(f.read_text())):
                if re.match(r"[a-z]+:", target) or target.startswith("#"):
                    continue
                path = target.split("#")[0]
                self.assertTrue((f.parent / path).exists(), f"{f}: broken link {target}")

    def test_skill_set(self):
        self.assertEqual({f.parent.name for f in skill_files()}, SKILLS_SET)
