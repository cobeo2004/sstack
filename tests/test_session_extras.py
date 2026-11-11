"""The session harness beside test_session_harness: escalation after a failed child, and doctor's check."""
import json
from pathlib import Path

from helpers import REPO  # noqa: F401  (puts lib/ on sys.path)
from test_dispatch import FakeCliBase
from test_doctor import DoctorBase
from test_session_harness import CLAUDE


class SessionEscalationTests(FakeCliBase):
    def test_failed_shell_child_escalates_to_a_native_agent_with_the_session_kept(self):
        self.example()
        _, out, _ = self.dispatch("implement", "--files", "README.md", env=CLAUDE)  # docs → tier.cheap → pi, via Bash
        call = json.loads(out)["calls"][0]
        self.assertEqual(call["tool"], "Bash")
        self.report().parent.mkdir(exist_ok=True)
        self.report().write_text("half done\n")
        code, out2, err = self.record(call, 1, env=CLAUDE)
        self.assertEqual(code, 4, err)
        d = json.loads(out2)
        self.assertEqual((d["ade"], d["session"]), (None, "claude"))
        self.assertEqual((d["calls"][0]["tool"], d["calls"][0]["member"]), ("Agent", "claude/sonnet"))
        run = json.loads((Path(d["run_dir"]) / "run.json").read_text())
        self.assertEqual((run["ade"], run["session"]), (None, "claude"))


class SessionDoctorTests(DoctorBase):
    def check(self):
        _, out, _ = self.doctor()
        return next(l for l in out.splitlines() if "session harness" in l)

    def test_template_session_passes(self):
        self.assertEqual(self.check(), "PASS session harness: claude")

    def test_a_harness_file_without_the_table_warns(self):
        (self.home / ".sstack/harnesses/claude.toml").write_text('headless = ["claude", "-p"]\n')
        self.assertTrue(self.check().startswith("WARN session harness: harnesses/claude.toml has no [session]"))

    def test_a_malformed_table_fails(self):
        p = self.home / ".sstack/harnesses/claude.toml"
        p.write_text(p.read_text().replace('detect = ["CLAUDECODE"]', 'detect = []'))
        self.assertIn("FAIL session harness: claude: session.detect", self.check())

    def test_a_non_table_session_fails_without_crashing(self):
        """Review 4: `session = false` crashed doctor with AttributeError."""
        (self.home / ".sstack/harnesses/claude.toml").write_text('headless = ["claude", "-p"]\nsession = false\n')
        self.assertIn("FAIL session harness: claude: session must be a table", self.check())


class SessionDispatchTests(FakeCliBase):
    def test_a_non_table_session_is_ignored_by_dispatch(self):
        self.example()
        p = self.home / ".sstack/harnesses/claude.toml"
        p.write_text(p.read_text().split("[session]")[0] + "session = false\n")
        code, _, err = self.dispatch("scout", env=CLAUDE)
        self.assertNotEqual(code, 4, err)
        self.assertNotIn("Traceback", err)
