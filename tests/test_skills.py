import re, unittest
from pathlib import Path

from helpers import REPO

SKILLS = REPO / "skills"
ADES = REPO / "defaults" / "ades"
ROUTER = SKILLS / "sstack" / "SKILL.md"
FORBIDDEN = ["Agent(", "Task(", "AskUserQuestion", "EnterPlanMode", "ExitPlanMode", "TodoWrite"]
ADE_ONLY = re.compile(r"delegate_task|preview_\w*|device_\w*|\bt3\s+thread\b|"
                       r"\borca\s+[a-z]+|conductor\s+workspace", re.I)
# one per known bypass of an earlier, narrower regex
ADE_BYPASSES = ["the `preview_*` tools", "`device_*` tools", "t3 thread start --wait",
                "orca goto --url", "Conductor workspace create", "mcp__t3-code__delegate_task",
                "t3  thread start", "orca\tgoto", "Conductor  workspace create"]
SKILLS_SET = {"sstack", "setup", "work", "grill", "swarm", "review", "unslop", "babysit", "how", "why",
          "diagram", "code-graph", "reflect", "practices"}


def skill_files():
    return sorted(SKILLS.glob("*/SKILL.md"))


def skill_text_files():
    return sorted(p for p in SKILLS.rglob("*") if p.is_file())


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
        for f in ADES.glob("*.md"):
            self.assertLessEqual(len(f.read_text().splitlines()), 120, f)

    def test_testing_surfaces_wired(self):
        t = (SKILLS / "work" / "testing.md").read_text()
        for surface in ("## Code", "## Browser", "## Mobile"):
            self.assertIn(surface, t)
        for f in (SKILLS / "work" / "SKILL.md", SKILLS / "setup" / "SKILL.md"):
            self.assertIn("testing.md", f.read_text(), f)
        self.assertIn("active ADE's note", t)
        self.assertFalse((SKILLS / "sstack" / "harness-notes" / "ade.md").exists())
        for f in (SKILLS / "sstack" / "harness-notes").glob("*.md"):
            text = f.read_text()
            for verb in ("| drive a browser |", "| drive a device |"):
                self.assertIn(verb, text, f"{f}: {verb}")
            self.assertIn("the active ADE's note", text, f)

    def test_no_claude_only_tools(self):
        for f in SKILLS.rglob("*.md"):
            if "harness-notes" in f.parts:
                continue
            text = f.read_text()
            for tok in FORBIDDEN:
                self.assertNotIn(tok, text, f"{f}: {tok}")

    def test_ade_tools_only_in_notes(self):
        for f in skill_text_files():
            self.assertNotRegex(f.read_text(errors="replace"), ADE_ONLY, f)

    def test_ade_lint_catches_bypasses(self):
        for text in ADE_BYPASSES:
            self.assertRegex(text, ADE_ONLY)

    def test_router_owns_dispatch(self):
        router = ROUTER.read_text()
        self.assertIn("sstack-dispatch ade", router)
        delegation = router.split("## Delegation", 1)[1].split("\n## ", 1)[0]
        self.assertIn("`record`", delegation)
        self.assertIn("`4`", delegation)
        for f in SKILLS.rglob("*.md"):
            if f == ROUTER:
                continue
            self.assertNotIn("sstack-dispatch", f.read_text(), f)

    def test_ade_notes(self):
        for toml in ADES.glob("*.toml"):
            note = toml.with_suffix(".md")
            self.assertTrue(note.exists(), f"missing note for {toml.name}")
            text = note.read_text()
            self.assertNotIn("PLACEHOLDER", text, note)
            for heading in ("## Delegation", "## Browser", "## Device", "## Capture"):
                self.assertIn(heading, text, note)

    def test_relative_links_resolve(self):
        for f in list(SKILLS.rglob("*.md")) + list(ADES.glob("*.md")):
            for target in re.findall(r"\]\(([^)\s]+)\)", strip_code(f.read_text())):
                if re.match(r"[a-z]+:", target) or target.startswith("#"):
                    continue
                path = target.split("#")[0]
                self.assertTrue((f.parent / path).exists(), f"{f}: broken link {target}")

    def test_skill_set(self):
        self.assertEqual({f.parent.name for f in skill_files()}, SKILLS_SET)

    def test_work_traceability_reference(self):
        trace = SKILLS / "work" / "traceability.md"
        self.assertTrue(trace.exists(), trace)
        self.assertIn("traceability.md", (SKILLS / "work" / "SKILL.md").read_text())

HOOK_ROWS = ["| post-edit hook |", "| end-of-session hook |"]  # one per sstack hook (docs/spec/hooks.md)


class HookRows(unittest.TestCase):
    def test_every_harness_note_has_every_hook_row(self):
        for f in (SKILLS / "sstack" / "harness-notes").glob("*.md"):
            text = f.read_text()
            for row in HOOK_ROWS:
                self.assertIn(row, text, f"{f}: add a row (snippet, or `none: <reason>`)")
