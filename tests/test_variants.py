"""Answer key for stage variants (R19-R26; docs/spec/config.md, dispatch.md, doctor.md).

A user adds `roles/<stage>/<name>.toml` + `.md` (lens) in any layer: the stage gains an extra
member next to its default, matched against `--files`, with its own report, member key and brief.
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import REPO
from test_dispatch import FakeCliBase, T3
from test_doctor import DoctorBase, roles
import sstack_dispatch as D

PY = sys.executable
FAKE_AGENT = REPO / "tests" / "fakes" / "fake_agent.py"
FAKE = (f'[harness.fake]\nheadless = ["{PY}", "{FAKE_AGENT}", "{{model}}"]\n'
        f'headless_readonly = ["{PY}", "{FAKE_AGENT}", "{{model}}"]\n')
REVIEW_SINGLE = '[role.review]\nharness="fake"\nmodel="echo"\nmode="single"\n'


def roles_base(implement: str = "impl") -> str:
    """Every stage a variant can be added to, plus an implementer the review must differ from."""
    return ('[role.scout]\nharness="fake"\nmodel="echo"\n'
            '[role.investigate]\nharness="fake"\nmodel="echo"\n'
            '[role.plan]\nharness="fake"\nmodel="echo"\n'
            f'[role.implement]\nharness="fake"\nmodel="{implement}"\n')


class VariantBase(FakeCliBase):

    def cfg(self, review: str = REVIEW_SINGLE, implement: str = "impl", extra: str = "", harnesses: str = ""):
        self.glob_cfg(harnesses + FAKE + roles_base(implement) + review + extra)

    def variant(self, stage: str, name: str, text: str, lens: str | None = None, layer: Path | None = None):
        base = layer or (self.root / ".sstack")
        self.write(base, f"roles/{stage}/{name}.toml", text)
        if lens is not None:
            self.write(base, f"roles/{stage}/{name}.md", lens)

    def go(self, role: str = "review", *extra, report: Path | None = None, env=None):
        rp = Path(report) if report else self.report()
        return self.run_main(role, "--brief", self.brief(), "--report", str(rp), *extra, env=env)

    def index(self) -> list[dict]:
        p = self.root / D.INDEX
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def out(self, name: str = "r.md", report: Path | None = None) -> Path:
        return (Path(report) if report else self.report()).parent / name

    def last_run(self):
        rd = self.root / self.index()[-1]["run_dir"]
        return rd, json.loads((rd / "run.json").read_text())

    def hook_ade(self):
        """A hook ADE that runs the fake harness synchronously and keeps its delegate stdin."""
        self.write(self.home, ".sstack/ades/fake.toml",
                   'auto = true\n[detect]\nenv = ["FAKE_SESSION"]\n[delegate]\nkind = "hook"\npoll_s = 0\n')
        argv = json.dumps([PY, str(FAKE_AGENT), "echo"])
        h = self.write(self.home, ".sstack/ades/fake.hook",
                       '#!/bin/sh\nS="$SSTACK_HOOK_STATE"\n'
                       '[ "$1" = delegate ] || { cat >/dev/null; exit 1; }\n'
                       'cat > "$S/stdin.json"\n'
                       f"echo '{{\"action\": \"run\", \"argv\": {argv}}}'\n")
        h.chmod(0o755)


class LoadTests(VariantBase):

    def test_t3a_repo_variant_loaded_and_local_enabled_false_drops_it(self):
        self.cfg()
        self.variant("review", "security", 'harness = "fake"\nmodel = "echo"\n', lens="SECURITY LENS\n")
        code, _, err = self.go()
        self.assertEqual(code, 0, err)
        self.assertTrue(self.out("r-security.md").is_file(), err)
        self.write(self.root, ".sstack/local/roles/review/security.toml", "enabled = false\n")
        code, _, err = self.go(report=self.root / "out2/r.md")
        self.assertEqual(code, 0, err)
        self.assertTrue((self.root / "out2/r.md").is_file(), err)
        self.assertFalse((self.root / "out2/r-security.md").exists())

    def test_t3b_nearer_lens_md_wins_independently_of_the_toml(self):
        self.cfg()
        self.write(self.home, ".sstack/roles/review/security.toml", 'harness = "fake"\nmodel = "echo"\n')
        self.write(self.home, ".sstack/roles/review/security.md", "HOME LENS\n")
        self.write(self.root, ".sstack/roles/review/security.md", "REPO LENS\n")
        code, _, err = self.go()
        self.assertEqual(code, 0, err)
        path = self.out("r-security.md")
        self.assertTrue(path.is_file(), err)
        text = path.read_text()
        self.assertIn("REPO LENS", text)
        self.assertNotIn("HOME LENS", text)
        self.assertEqual(self.last_run()[1]["members"], ["fake/echo", "fake/echo#review/security"])


class MemberRulesTests(VariantBase):

    def test_t3c_variant_equal_to_the_implementer_is_dropped(self):
        self.cfg()
        self.variant("review", "twin", 'harness = "fake"\nmodel = "impl"\n')
        self.variant("review", "other", 'harness = "fake"\nmodel = "other"\n')
        code, _, err = self.go()
        self.assertEqual(code, 0, err)
        self.assertTrue(self.out("r-other.md").is_file(), err)  # a distinct variant does run
        self.assertFalse(self.out("r-twin.md").exists())
        self.assertEqual(self.last_run()[1]["members"], ["fake/echo", "fake/echo#review/other"])

    def test_t3c_variant_members_run_read_only(self):
        ro = (f'[harness.ro]\nheadless = ["{PY}", "-c", "print(\'WRITE\')"]\n'
              f'headless_readonly = ["{PY}", "-c", "print(\'READONLY\')"]\n')
        self.glob_cfg(ro + FAKE + roles_base() + '[role.review]\nharness="ro"\nmode="single"\n')
        self.variant("review", "security", 'harness = "ro"\nmodel = "other"\n')
        code, _, err = self.go()
        self.assertEqual(code, 0, err)
        self.assertIn("READONLY", self.out("r.md").read_text())
        variant = self.out("r-security.md")
        self.assertTrue(variant.is_file(), err)
        self.assertIn("READONLY", variant.read_text())
        self.assertNotIn("WRITE", variant.read_text())
        code, out, err = self.run_main("review", "--brief", self.brief(), "--report", str(self.report()), env=T3)
        self.assertEqual(code, 4, err)
        payload = json.loads(out)
        self.assertTrue(payload["readonly"])
        self.assertEqual(len(payload["calls"]), 2)
        for call in payload["calls"]:
            self.assertEqual(call["args"]["interactionMode"], "plan")


class ReportTests(VariantBase):

    def test_t3d_default_report_is_the_report_and_the_variant_gets_its_own(self):
        self.cfg()
        self.variant("review", "security", 'harness = "fake"\nmodel = "echo"\n', lens="SECURITY LENS\n")
        code, _, err = self.go()
        self.assertEqual(code, 0, err)
        default = self.out("r.md").read_text()
        self.assertIn("do the thing", default)
        self.assertNotIn("## Lens", default)
        path = self.out("r-security.md")
        self.assertTrue(path.is_file(), err)
        variant = path.read_text()
        self.assertIn("## Lens: review/security", variant)
        self.assertIn("SECURITY LENS", variant)

    def test_t3d_escalation_is_unchanged_by_a_non_matching_variant_only(self):
        self.cfg(review='[role.review]\nharness="fake"\nmodel="fail"\nmode="single"\n',
                 extra='[tier.strong]\nharness="fake"\nmodel="echo"\n')
        self.variant("review", "security", 'harness = "fake"\nmodel = "echo"\npaths = ["auth/*"]\n')
        code, _, err = self.go("review", "--files", "lib/a.py")  # does not touch auth/: default alone
        self.assertEqual(code, 0, err)
        self.assertIn("escalating once", err)
        self.assertTrue(self.out("r.failed.md").is_file(), err)
        self.assertIn("REPORT", self.out("r.md").read_text())
        self.assertFalse(self.out("r-security.md").exists())
        # a matching variant makes the run a panel: the default's failure is not escalated
        code, _, err = self.go("review", "--files", "auth/login.py", report=self.root / "out2/r.md")
        self.assertEqual(code, 0, err)
        self.assertNotIn("escalating", err)
        self.assertFalse((self.root / "out2/r.failed.md").exists())
        self.assertTrue((self.root / "out2/r-security.md").is_file(), err)


class SameAgentTests(VariantBase):

    def test_t3e_same_harness_model_distinct_identity_reports_and_state_dirs(self):
        self.cfg()
        self.variant("review", "security", 'harness = "fake"\nmodel = "echo"\n', lens="ONLY FOR SECURITY\n")
        self.hook_ade()
        code, _, err = self.go(env={"FAKE_SESSION": "1"})
        self.assertEqual(code, 0, err)
        rd, run = self.last_run()
        self.assertEqual(run["members"], ["fake/echo", "fake/echo#review/security"])
        self.assertEqual({p.name for p in rd.glob("hook.*")}, {"hook.fake-echo", "hook.fake-echo-security"})
        default = self.out("r.md").read_text()
        self.assertIn("do the thing", default)
        self.assertNotIn("ONLY FOR SECURITY", default)
        variant = self.out("r-security.md").read_text()
        self.assertIn("## Lens: review/security", variant)
        self.assertIn("ONLY FOR SECURITY", variant)
        self.assertNotIn("ONLY FOR SECURITY", (rd / "hook.fake-echo" / "stdin.json").read_text())


class MatchingTests(VariantBase):

    def test_t3f_paths_glob_and_no_matchers_always_runs(self):
        self.cfg()
        self.variant("review", "auth", 'harness = "fake"\nmodel = "echo"\npaths = ["auth/*"]\n')
        self.variant("review", "always", 'harness = "fake"\nmodel = "echo"\n')
        report = self.root / "a" / "r.md"
        code, _, err = self.go("review", "--files", "auth/login.py", report=report)
        self.assertEqual(code, 0, err)
        self.assertTrue((report.parent / "r-auth.md").is_file(), err)
        self.assertTrue((report.parent / "r-always.md").is_file())
        report = self.root / "b" / "r.md"
        code, _, err = self.go("review", "--files", "lib/a.py", report=report)
        self.assertEqual(code, 0, err)
        self.assertFalse((report.parent / "r-auth.md").exists())
        self.assertTrue((report.parent / "r-always.md").is_file())


class LensTests(VariantBase):

    def test_t3g_lens_reaches_only_the_variant_brief(self):
        self.cfg()
        self.variant("plan", "ui", 'harness = "fake"\nmodel = "echo"\n', lens="THE UI LENS\n")
        code, _, err = self.go("plan")
        self.assertEqual(code, 0, err)
        path = self.out("r-ui.md")
        self.assertTrue(path.is_file(), err)
        default, variant = self.out("r.md").read_text(), path.read_text()
        self.assertNotIn("## Lens", default)
        self.assertNotIn("THE UI LENS", default)
        self.assertIn("## Lens: plan/ui", variant)
        self.assertIn("THE UI LENS", variant)


SERIAL = '''\
import sys, time
from pathlib import Path
art, name = Path(sys.argv[1]), sys.argv[2]
lock = art / "running"
try:
    lock.mkdir()
except FileExistsError:
    (art / "overlap.txt").write_text("overlap\\n")
with open(art / "starts.log", "a") as f:
    f.write(name + "\\n")
time.sleep(0.2)
print("REPORT " + name)
try:
    lock.rmdir()
except OSError:
    pass
'''


class ParallelTests(VariantBase):

    def test_t3h_max_parallel_one_keeps_every_member_serial(self):
        art = self.root.parent / "serial"
        art.mkdir()
        script = art / "marker.py"
        script.write_text(SERIAL)
        serial = (f'[harness.serial]\nheadless = ["{PY}", "{script}", "{art}", "{{model}}"]\n'
                  f'headless_readonly = ["{PY}", "{script}", "{art}", "{{model}}"]\n')
        self.glob_cfg(serial + '[role.implement]\nharness="serial"\nmodel="impl"\n'
                      '[role.review]\nharness="serial"\nmodel="a"\nmode="single"\n'
                      '[rules]\nmax_parallel = 1\n')
        self.variant("review", "b", 'harness = "serial"\nmodel = "b"\n')
        self.variant("review", "c", 'harness = "serial"\nmodel = "a"\n')
        code, _, err = self.go()
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted((art / "starts.log").read_text().split()), ["a", "a", "b"])
        self.assertFalse((art / "overlap.txt").exists())
        for name in ("r.md", "r-b.md", "r-c.md"):
            self.assertTrue((self.report().parent / name).is_file(), name)


class ToolShapeTests(VariantBase):

    def payload(self):
        code, out, err = self.run_main("review", "--brief", self.brief(), "--report", str(self.report()), env=T3)
        self.assertEqual(code, 4, err)
        return json.loads(out)

    def test_t3h2_payload_lists_every_call_and_carries_max_parallel(self):
        self.example()
        self.variant("review", "security", 'harness = "claude"\nmodel = "opus"\n')
        self.variant("review", "second", 'harness = "codex"\nmodel = "gpt-6.1-sol"\n')
        d = self.payload()
        self.assertIn("max_parallel", d)
        self.assertEqual(d["max_parallel"], 4)
        self.assertEqual(len(d["calls"]), 3)
        self.assertEqual({c["tool"] for c in d["calls"]}, {"delegate_task"})
        self.write(self.root, ".sstack/config.toml", "[rules]\nmax_parallel = 2\n")
        self.assertEqual(self.payload()["max_parallel"], 2)

    def test_t3h2_skill_states_the_cap(self):
        text = (REPO / "skills/sstack/SKILL.md").read_text()
        delegation = text.split("## Delegation", 1)[1].split("\n## ", 1)[0]
        self.assertIn("max_parallel", delegation)


class VariantPanelTests(VariantBase):

    def test_t3i_variant_panel_writes_one_report_per_member(self):
        self.cfg()
        self.variant("review", "vp", 'panel = [{harness="fake",model="p1"},{harness="fake",model="p2"}]\n',
                     lens="PANEL LENS\n")
        code, _, err = self.go()
        self.assertEqual(code, 0, err)
        for name in ("r-vp.fake-p1.md", "r-vp.fake-p2.md"):
            path = self.report().parent / name
            self.assertTrue(path.is_file(), (name, err))
            self.assertIn("PANEL LENS", path.read_text())
        self.assertTrue(self.out("r.md").is_file())
        self.assertEqual(sorted(self.last_run()[1]["members"]),
                         sorted(["fake/echo", "fake/p1#review/vp", "fake/p2#review/vp"]))


class ListingTests(VariantBase):

    def variant_sec(self):
        self.variant("review", "security", 'harness = "fake"\nmodel = "echo"\nwhen = "our auth code"\n'
                                          'paths = ["auth/*"]\n', lens="LENS\n")

    def config_cli(self, *args) -> str:
        env = {k: v for k, v in os.environ.items() if not k.startswith("SSTACK_")}
        env["HOME"] = str(self.home)
        r = subprocess.run([PY, str(REPO / "bin/sstack-config"), *args], cwd=str(self.root), env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_t3j_config_show_prints_the_variant_file_and_its_layer(self):
        self.cfg()
        self.variant_sec()
        out = self.config_cli("show", "roles/review/security")
        self.assertTrue(out.startswith("# repo: "), out)
        self.assertIn("roles/review/security.toml", out.splitlines()[0])
        self.assertIn('harness = "fake"', out)

    def test_t3j_routes_lists_the_variant_with_when_and_layer(self):
        self.cfg()
        self.variant_sec()
        code, out, err = self.run_main("routes")
        self.assertEqual(code, 0, err)
        line = next((l for l in out.splitlines() if "review/security" in l), "")
        self.assertTrue(line, out)
        for bit in ("our auth code", "fake/echo", "repo"):
            self.assertIn(bit, line)


class DoctorVariantTests(DoctorBase):

    def sec(self, lens: bool = True):
        self.write(self.root, ".sstack/roles/review/security.toml", 'harness = "fake"\nmodel = "echo"\n')
        if lens:
            self.write(self.root, ".sstack/roles/review/security.md", "LENS\n")

    def line(self, out: str, prefix: str, needle: str) -> str:
        return next((l for l in out.splitlines() if l.startswith(prefix) and needle in l), "")

    def test_t3l_doctor_lists_the_variant_with_its_layer(self):
        self.glob_cfg(roles())
        self.sec()
        code, out, _ = self.doctor()
        self.assertEqual(code, 0, out)
        line = self.line(out, "PASS roles resolve", "review/security")
        self.assertTrue(line, out)
        self.assertIn("fake/echo", line)
        self.assertIn("repo", line)

    def test_t3l_toml_without_md_is_a_warning(self):
        self.glob_cfg(roles())
        self.sec(lens=False)
        code, out, _ = self.doctor()
        self.assertEqual(code, 0, out)
        line = self.line(out, "WARN ", "review/security")
        self.assertTrue(line, out)
        self.assertIn(".md", line)

    def test_t3l_an_implement_folder_is_a_failure(self):
        self.glob_cfg(roles())
        self.write(self.root, ".sstack/roles/implement/x.toml", 'harness = "fake"\nmodel = "echo"\n')
        code, out, _ = self.doctor()
        self.assertEqual(code, 1, out)
        self.assertTrue(self.line(out, "FAIL ", "roles/implement"), out)


class RecordVariantTests(VariantBase):

    def panel_index(self) -> list[Path]:
        return [p for p in sorted(self.report().parent.glob("*.md"))
                if "fake/echo#review/security" in p.read_text()]

    def test_t3n_record_in_either_order_then_one_panel_index(self):
        for order in (("default", "variant"), ("variant", "default")):
            with self.subTest(order=order):
                self.cfg()
                self.variant("review", "security", 'harness = "fake"\nmodel = "echo"\n')
                report = self.root / ("n-" + "-".join(order)) / "r.md"
                code, out, err = self.run_main("review", "--brief", self.brief(), "--report", str(report), env=T3)
                self.assertEqual(code, 4, err)
                calls = {c["member"]: c for c in json.loads(out)["calls"]}
                self.assertEqual(set(calls), {"fake/echo", "fake/echo#review/security"})
                report.parent.mkdir(parents=True, exist_ok=True)
                (report.parent / "r.md").write_text("# default\nPASS\n")
                (report.parent / "r-security.md").write_text("# variant\nPASS\n")
                codes = []
                for who in order:
                    code, _, err = self.record(calls["fake/echo#review/security" if who == "variant" else "fake/echo"],
                                               0, env=T3)
                    self.assertEqual(code, 0, err)
                    codes.append(self.panel_index())
                self.assertEqual(codes[0], [])  # not before every member recorded
                [index] = codes[1]
                self.assertNotEqual(index, report)
                text = index.read_text()
                self.assertIn("fake/echo#review/security", text)
                self.assertIn("fake/echo", text.replace("fake/echo#review/security", ""))
                self.assertEqual((report.parent / "r.md").read_text(), "# default\nPASS\n")
                code, _, err = self.record(calls["fake/echo"], 0, env=T3)
                self.assertEqual(code, 0, err)
                self.assertEqual([index], self.panel_index())
                self.assertEqual(index.read_text(), text)  # written once


class StageTests(VariantBase):

    def test_t3o_a_matching_variant_runs_alongside_the_default(self):
        for stage in ("investigate", "plan", "review"):
            with self.subTest(stage=stage):
                self.cfg()
                self.variant(stage, "mine", 'harness = "fake"\nmodel = "echo"\n')
                report = self.root / f"o-{stage}" / "r.md"
                code, _, err = self.go(stage, report=report)
                self.assertEqual(code, 0, err)
                self.assertTrue(report.is_file(), stage)
                self.assertTrue((report.parent / "r-mine.md").is_file(), (stage, err))

    def test_t3o_kinds_match_the_route_kind_of_each_file(self):
        for stage in ("investigate", "plan", "review"):
            with self.subTest(stage=stage):
                self.cfg()
                self.variant(stage, "be", 'harness = "fake"\nmodel = "echo"\nkinds = ["backend"]\n')
                hit = self.root / f"k-{stage}-hit" / "r.md"
                code, _, err = self.go(stage, "--files", "lib/a.py", report=hit)
                self.assertEqual(code, 0, err)
                self.assertTrue((hit.parent / "r-be.md").is_file(), (stage, err))
                miss = self.root / f"k-{stage}-miss" / "r.md"
                code, _, err = self.go(stage, "--files", "web/a.tsx", report=miss)
                self.assertEqual(code, 0, err)
                self.assertFalse((miss.parent / "r-be.md").exists(), stage)


class ReviewModeTests(VariantBase):

    def test_t3p_variants_are_added_in_every_mode_including_a_variant_panel(self):
        for mode in ("single", "panel", "auto"):
            with self.subTest(mode=mode):
                review = (f'[role.review]\nmode = "{mode}"\n'
                          'panel = [{harness="fake",model="p1"},{harness="fake",model="p2"}]\n')
                self.cfg(review=review)
                self.variant("review", "v", 'harness = "fake"\nmodel = "echo"\n')
                self.variant("review", "vp", 'panel = [{harness="fake",model="p1"},{harness="fake",model="p2"}]\n')
                report = self.root / f"p-{mode}" / "r.md"
                code, _, err = self.go("review", "--files", "lib/a.py", report=report)
                self.assertEqual(code, 0, err)
                for name in ("r-v.md", "r-vp.fake-p1.md", "r-vp.fake-p2.md"):
                    self.assertTrue((report.parent / name).is_file(), (mode, name, err))
                if mode == "panel":
                    self.assertIn("fake/p1", report.read_text())
                    self.assertIn("fake/p2", report.read_text())
                else:
                    self.assertIn("REPORT", report.read_text())
                rd = self.root / self.index()[-1]["run_dir"]
                members = json.loads((rd / "run.json").read_text())["members"]
                for key in ("fake/echo#review/v", "fake/p1#review/vp", "fake/p2#review/vp"):
                    self.assertIn(key, members)


class IdentityTests(VariantBase):

    def test_t3q_index_line_and_hook_stdin_carry_the_variant(self):
        self.cfg()
        self.variant("review", "security", 'harness = "fake"\nmodel = "echo"\n', lens="LENS\n")
        self.hook_ade()
        code, _, err = self.go(env={"FAKE_SESSION": "1"})
        self.assertEqual(code, 0, err)
        rd, _ = self.last_run()
        run_dir = self.index()[-1]["run_dir"]
        recs = [r for r in self.index() if r["run_dir"] == run_dir]
        self.assertEqual(len(recs), 2)
        variant = next(r for r in recs if r.get("variant"))
        default = next(r for r in recs if not r.get("variant"))
        self.assertEqual((variant["variant"], variant["harness"], variant["model"]),
                         ("review/security", "fake", "echo"))
        self.assertEqual((default["harness"], default["model"]), ("fake", "echo"))
        stdin = json.loads((rd / "hook.fake-echo-security" / "stdin.json").read_text())
        self.assertEqual((stdin["variant"], stdin["member"]), ("review/security", "fake/echo#review/security"))
        self.assertTrue(stdin["readonly"])
        self.assertIsNone(json.loads((rd / "hook.fake-echo" / "stdin.json").read_text()).get("variant"))


if __name__ == "__main__":
    unittest.main()
