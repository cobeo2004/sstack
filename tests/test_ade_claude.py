"""Answer key: bare Claude Code dispatches through its own subagents (workflow-adherence R7-R9).

The active environment decides how a child starts: T3 → delegate_task, bare Claude Code → the
native `Agent` tool for Claude members and a backgrounded `Bash` call for members Claude can't host."""
import json

from test_dispatch import FakeCliBase, T3

CLAUDE = {"CLAUDECODE": "1"}


class ClaudeAdeTests(FakeCliBase):
    def setUp(self):
        super().setUp()
        self.example()

    def ade(self, env):
        code, out, err = self.run_main("ade", env=env)
        self.assertEqual(code, 0, err)
        return json.loads(out)["name"]

    def call(self, *args):
        code, out, err = self.dispatch(*args, env=CLAUDE)
        self.assertEqual(code, 4, out + err)
        d = json.loads(out)
        self.assertEqual(d["ade"], "claude")
        return d["calls"][0]

    def test_bare_claude_code_is_detected(self):
        self.assertEqual(self.ade(CLAUDE), "claude")

    def test_t3_wins_over_claude_code(self):
        """T3 (and Orca, Conductor) run Claude Code too: the outer environment wins."""
        self.assertEqual(self.ade({**CLAUDE, **T3}), "t3")

    def test_no_marker_stays_headless(self):
        self.assertIsNone(self.ade({}))

    def test_readonly_claude_member_is_a_native_agent(self):
        c = self.call("scout")
        self.assertEqual(c["tool"], "Agent")
        self.assertEqual(c["args"]["model"], "haiku")
        self.assertIn(str(self.root / "b.md"), c["args"]["prompt"])
        self.assertIn(str(self.report()), c["args"]["prompt"])
        self.assertNotIn("isolation", c["args"])
        self.assertIn("sstack-dispatch record scout", c["record"])

    def test_write_claude_member_is_an_isolated_agent(self):
        c = self.call("implement", "--files", "a.py")  # backend → tier.standard → claude/sonnet
        self.assertEqual(c["tool"], "Agent")
        self.assertEqual(c["args"]["model"], "sonnet")
        self.assertEqual(c["args"]["isolation"], "worktree")

    def test_non_claude_member_is_a_background_shell_call(self):
        c = self.call("implement", "--files", "README.md")  # docs → tier.cheap → pi
        self.assertEqual(c["tool"], "Bash")
        self.assertIs(c["args"]["run_in_background"], True)
        cmd = c["args"]["command"]
        for part in ("pi -p", "opencode-go/deepseek-v4.1-flash", str(self.root / "b.md"), str(self.report())):
            self.assertIn(part, cmd)
        self.assertIn("sstack-dispatch record implement", c["record"])

    def test_headless_flag_still_beats_the_ade(self):
        """sstack-reflect-hook passes --via headless: a hook has no agent to run a payload."""
        code, _, _ = self.dispatch("scout", "--via", "headless", env=CLAUDE)
        self.assertNotEqual(code, 4)

    def test_shell_children_share_the_tree_so_writers_serialize(self):
        """A Bash child edits this checkout; only Agent(isolation=worktree) children may run beside one."""
        d = self.root / ".sstack" / "steps" / "implement"
        d.mkdir(parents=True, exist_ok=True)
        (d / "step.toml").write_text("max_agents = 2\n")

        def go(task, f):
            p = self.root / ".sstack" / "runs" / task / "r.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            return self.run_main("implement", "--step", "implement", "--brief", self.brief(), "--report", str(p),
                                 "--files", f, env=CLAUDE)[0]

        self.assertEqual(go("a", "x.py"), 4)       # claude/sonnet, own worktree
        self.assertEqual(go("b", "y.py"), 4)       # disjoint, isolated: runs beside it
        self.assertEqual(go("c", "README.md"), 5)  # pi via Bash in this tree: must wait
