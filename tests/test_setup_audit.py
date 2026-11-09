"""setup audits first, then recommends, then the user chooses (skills/setup/SKILL.md); doctor's
read-only `entry pointers` check warns when an agent's instruction file lacks the sstack pointer
or has a competing precedence rule above it (docs/spec/doctor.md). Temp HOME only."""
import re, unittest

from helpers import REPO
from test_doctor import DoctorBase, roles

SETUP = REPO / "skills" / "setup" / "SKILL.md"
POINTER = "For engineering tasks, start with the sstack skill. <!-- sstack -->"


class EntryPointerTests(DoctorBase):
    def put(self, rel, text):
        p = self.home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def line(self, out):
        hits = [l for l in out.splitlines() if " entry pointers" in l]
        self.assertEqual(len(hits), 1, out)
        return hits[0]

    def test_no_instruction_files(self):
        self.glob_cfg(roles())
        code, out, _ = self.doctor()
        self.assertEqual(code, 0, out)
        self.assertTrue(self.line(out).startswith("PASS entry pointers"), out)

    def test_pointer_first_passes(self):
        self.glob_cfg(roles())
        self.put(".claude/CLAUDE.md", f"{POINTER}\n\n# Orchestration\n1. superpowers first.\n")
        code, out, _ = self.doctor()
        self.assertEqual(code, 0, out)
        self.assertTrue(self.line(out).startswith("PASS entry pointers"), out)

    def test_competing_rule_above_pointer_warns(self):
        self.glob_cfg(roles())
        self.put(".claude/CLAUDE.md", f"# Orchestration\n1. **superpowers first.** Check skills.\n\n{POINTER}\n")
        code, out, _ = self.doctor()
        self.assertEqual(code, 0, out)  # advice, not failure
        l = self.line(out)
        self.assertTrue(l.startswith("WARN entry pointers"), out)
        self.assertIn(".claude/CLAUDE.md", l)
        self.assertIn("late", l)

    def test_autonomy_directive_above_pointer_warns(self):
        self.glob_cfg(roles())
        self.put(".codex/AGENTS.md", f"EXECUTE TASKS WITHOUT ASKING FOR PERMISSION.\n\n{POINTER}\n")
        _, out, _ = self.doctor()
        l = self.line(out)
        self.assertTrue(l.startswith("WARN entry pointers"), out)
        self.assertIn(".codex/AGENTS.md", l)
        self.assertIn("late", l)

    def test_missing_pointer_warns(self):
        self.glob_cfg(roles())
        self.put(".claude/CLAUDE.md", f"{POINTER}\n")
        self.put(".codex/AGENTS.md", "# Codex\nBe nice.\n")
        code, out, _ = self.doctor()
        self.assertEqual(code, 0, out)
        l = self.line(out)
        self.assertTrue(l.startswith("WARN entry pointers"), out)
        self.assertIn(".codex/AGENTS.md", l)
        self.assertIn("missing", l)
        self.assertNotIn(".claude/CLAUDE.md", l)

    def test_cursor_file_checked(self):
        self.glob_cfg(roles())
        self.put(".cursor/AGENTS.md", "# Cursor\n")
        _, out, _ = self.doctor()
        self.assertIn(".cursor/AGENTS.md", self.line(out))

    def test_warn_does_not_mask_fail(self):
        self.glob_cfg(roles() + '[role.plan]\nharness="nope"\n')
        self.put(".codex/AGENTS.md", "# Codex\n")
        code, out, _ = self.doctor()
        self.assertEqual(code, 1, out)
        self.assertIn("WARN entry pointers", out)


class SetupSkillTests(unittest.TestCase):
    def test_audit_recommend_choose_apply_order(self):
        text = SETUP.read_text()
        heads = [text.find(h) for h in ("## 1. Audit", "## 2. Recommend", "## 3. Choose", "## 4. Apply")]
        self.assertTrue(all(h >= 0 for h in heads), heads)
        self.assertEqual(heads, sorted(heads))

    def test_nothing_written_before_choice(self):
        text = SETUP.read_text()
        self.assertRegex(text, re.compile(r"nothing is written before", re.I))
        self.assertIn("sstack-doctor", text)
        self.assertIn("sstack-config show", text)
