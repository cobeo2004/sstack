"""Answer key for unattended mode (decisions R14; docs/spec/config.md § `[unattended]`, docs/spec/workflow.md § Unattended)."""
import os, subprocess, sys
from unittest import mock

from helpers import REPO
from test_workflow import WorkflowBase, WF
from test_dispatch import NO_T3
import sstack_config as C
import sstack_doctor as D

ON = '[unattended]\nenabled = true\nplan_gate = "auto"\n'


class ResolveTests(WorkflowBase):
    def resolve(self, env=None):
        return C.unattended(C.load(self.root), env or {})

    def test_defaults_are_off_and_inbox(self):
        self.assertEqual(self.resolve(), {"enabled": False, "plan_gate": "inbox"})
        self.assertEqual(C.unattended({}, {}), {"enabled": False, "plan_gate": "inbox"})

    def test_config_beats_default(self):
        self.repo_cfg('[unattended]\nplan_gate = "auto"\n')
        self.assertEqual(self.resolve(), {"enabled": False, "plan_gate": "auto"})

    def test_local_layer_turns_it_on(self):
        self.local_cfg(ON)  # what Hive writes to the job worktree's .sstack/local/config.toml
        self.assertEqual(self.resolve(), {"enabled": True, "plan_gate": "auto"})

    def test_env_turns_it_on_and_beats_config_plan_gate(self):
        self.repo_cfg('[unattended]\nplan_gate = "auto"\n')
        self.assertEqual(self.resolve({"SSTACK_UNATTENDED": "1", "SSTACK_PLAN_GATE": "inbox"}),
                         {"enabled": True, "plan_gate": "inbox"})
        self.assertFalse(self.resolve({"SSTACK_UNATTENDED": "0"})["enabled"])

    def test_invalid_values_name_the_allowed_ones(self):
        with self.assertRaisesRegex(C.ConfigError, r"SSTACK_PLAN_GATE 'yes' is not one of: auto, inbox"):
            self.resolve({"SSTACK_PLAN_GATE": "yes"})
        self.repo_cfg('[unattended]\nplan_gate = "maybe"\n')
        with self.assertRaisesRegex(C.ConfigError, r"\[unattended\] plan_gate 'maybe' is not one of: auto, inbox"):
            self.resolve()
        self.repo_cfg('[unattended]\nenabled = "yes"\n')
        with self.assertRaisesRegex(C.ConfigError, "enabled 'yes' is not true or false"):
            self.resolve()

    def test_doctor_fails_a_bad_plan_gate_and_passes_a_good_one(self):
        self.assertEqual(D._unattended(self.root), "off, plan_gate inbox")
        self.local_cfg('[unattended]\nplan_gate = "maybe"\n')
        with self.assertRaises(C.ConfigError):
            D._unattended(self.root)


class GateLineTests(WorkflowBase):
    def wf(self, *args, cwd=None, **env):
        e = {k: v for k, v in dict(NO_T3, HOME=str(self.home)).items() if not k.startswith("SSTACK_U")}
        r = subprocess.run([sys.executable, str(WF), *args], cwd=cwd or self.root, env={**e, **env},
                           capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr

    def lines(self, step, **env):
        self.record_dispatch(step)
        code, out, err = self.wf("done", step, "--run", str(self.run_dir), **env)
        self.assertEqual(code, 0, err)
        return out.splitlines()

    def test_off_is_the_old_gate_line(self):
        self.assertEqual(self.lines("recon")[0], "GATE: wait for the user's yes")

    def test_on_gates_resolve(self):
        self.local_cfg(ON)
        self.assertEqual(self.lines("recon")[0], "GATE: unattended, passes (recon)")
        self.assertIn("plan_gate auto", self.lines("plan")[0])

    def test_inbox_plan_waits_and_env_overrides_config(self):
        self.local_cfg('[unattended]\nenabled = true\nplan_gate = "auto"\n')
        self.assertEqual(self.lines("plan", SSTACK_PLAN_GATE="inbox")[0], "WAITING: plan_approval")

    def test_env_on_with_default_inbox(self):
        self.assertEqual(self.lines("plan", SSTACK_UNATTENDED="1")[0], "WAITING: plan_approval")

    def test_unattended_command_and_bad_value(self):
        self.local_cfg(ON)
        self.assertEqual(self.wf("unattended")[1].splitlines(), ["unattended: on", "plan_gate: auto"])
        code, _, err = self.wf("unattended", SSTACK_PLAN_GATE="x")
        self.assertEqual(code, 1)
        self.assertIn("auto, inbox", err)
