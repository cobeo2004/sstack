import re, unittest
from pathlib import Path

from helpers import REPO

SKILLS = REPO / "skills"
FORBIDDEN = ["Agent(", "Task(", "AskUserQuestion", "EnterPlanMode", "ExitPlanMode", "TodoWrite"]
TWELVE = {"sstack", "setup", "work", "swarm", "review", "unslop", "babysit", "how", "why",
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

    def test_twelve_skills(self):
        self.assertEqual({f.parent.name for f in skill_files()}, TWELVE)
