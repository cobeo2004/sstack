"""End to end through the bins: split config → T3 env → plain dispatch exits 4 (nothing started) →
`record` → index line with "ade": "t3"."""
import json, os, subprocess, sys, tempfile
from pathlib import Path

from helpers import TempEnv, REPO
from test_dispatch import NO_T3

FAKES = REPO / "tests" / "fakes"


class IntegrationTests(TempEnv):
    def test_t3_dispatch_exit4_record_index(self):
        self.example()  # split home layer
        self.assertTrue((self.home / ".sstack" / "roles" / "scout.toml").is_file())
        with tempfile.TemporaryDirectory() as t:
            log = Path(t) / "calls.log"
            env = dict(NO_T3, HOME=str(self.home), T3CODE_THREAD_ID="x", T3CODE_CLI_PATH=str(FAKES / "t3"),
                       FAKE_CALLS_LOG=str(log), PATH=f"{FAKES}:{REPO / 'bin'}:{os.environ['PATH']}")
            run = lambda *a: subprocess.run([sys.executable, str(REPO / "bin" / "sstack-dispatch"), *a],
                                            cwd=self.root, env=env, capture_output=True, text=True)
            (self.root / "b.md").write_text("look around\n")
            r = run("scout", "--brief", "b.md", "--report", "r.md")
            self.assertEqual(r.returncode, 4, r.stderr)
            self.assertFalse(log.exists())  # no t3 thread, no headless child
            call = json.loads(r.stdout)["calls"][0]
            self.assertEqual((call["tool"], call["args"]["target"]["model"]), ("delegate_task", "claude-haiku-5-5"))
            (self.root / "r.md").write_text("REPORT\n")  # the delegate_task child's report
            r = run(*call["record"].replace("{exit}", "0").replace("'<CHILD_THREAD_ID>'", "thread-1").split()[1:])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(log.exists())
        lines = (self.root / ".sstack" / "runs" / "index.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 1)
        line = json.loads(lines[0])
        self.assertEqual((line["ade"], line["role"], line["exit"], line["report"], line["readonly_warning"]),
                         ("t3", "scout", 0, "r.md", []))
