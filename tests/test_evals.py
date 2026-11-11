"""The eval suite's scaffolds (evals/, run by `claude plugin eval`): each builds its fixture without a model."""
import json, os, re, subprocess, sys, tempfile, unittest
from pathlib import Path

from helpers import REPO

EVALS = REPO / "evals"
CASES = sorted(p.parent for p in EVALS.glob("*/case.yaml"))
NEXT = {"review": "review"}  # the step each scaffold leaves the run at; the rest stop at implement


class EvalScaffoldTests(unittest.TestCase):
    def test_there_are_cases(self):
        self.assertGreaterEqual(len(CASES), 5)

    def test_each_scaffold_builds_its_fixture(self):
        for case in CASES:
            with self.subTest(case.name), tempfile.TemporaryDirectory() as home:
                cwd = Path(home) / "cwd"
                cwd.mkdir()
                env = {"PATH": os.environ["PATH"], "HOME": home}
                r = subprocess.run(["bash", str(case / "fixture.sh")], cwd=cwd, env=env, capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                run = cwd / ".sstack" / "runs" / "subtract-1"
                st = json.loads((run / "workflow.json").read_text())
                step = next((v for k, v in NEXT.items() if k in case.name), "implement")
                self.assertEqual(st["current"], step)
                self.assertNotIn("no dispatch", (run / "progress.md").read_text())  # it would teach the shortcut
                if "worktree" in case.name:
                    common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=cwd, env=env,
                                            capture_output=True, text=True).stdout.strip()
                    self.assertNotEqual(common, ".git")

    def test_each_case_has_graders_and_a_quoted_description(self):
        for case in CASES:
            with self.subTest(case.name):
                self.assertTrue(list((case / "graders").glob("*.md")))
                self.assertRegex((case / "prompt.md").read_text(), re.compile(r'^description: ".*"$', re.M))


if __name__ == "__main__":
    unittest.main()
