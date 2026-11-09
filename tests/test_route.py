import json, sys
from pathlib import Path

from helpers import TempEnv, REPO
from test_dispatch import DispatchBase, FAKE
import sstack_route as R

TIERS = FAKE + ('[tier.strong]\nharness="fake"\nmodel="strong"\n'
                '[tier.standard]\nharness="fake"\nmodel="standard"\n'
                '[tier.cheap]\nharness="fake"\nmodel="cheap"\n')


class ClassifyTests(TempEnv):
    def test_kinds(self):
        c = R.classify
        self.assertEqual(c(["web/src/components/Button.tsx", "web/src/app.css"]), "frontend")
        self.assertEqual(c(["server/handlers/user.go"]), "backend")
        self.assertEqual(c(["ios/App/View.swift"]), "mobile")
        self.assertEqual(c(["README.md", "docs/setup.md"]), "docs")
        self.assertEqual(c(["api/auth/session.py", "README.md"]), "security")
        self.assertEqual(c(["web/Button.tsx", "server/user.go"]), "complex")
        self.assertEqual(c([f"server/m{i}.go" for i in range(25)]), "complex")
        self.assertIsNone(c(["Makefile"]))
        self.assertIsNone(c([]))


class RouteTests(DispatchBase):
    def dry(self, role, *extra):
        return self.run_main(role, "--brief", self.brief(), "--report", str(self.report()), "--dry-run", *extra)

    def test_implement_auto_kind_picks_tier(self):
        self.glob_cfg(TIERS + '[role.implement]\nharness="fake"\nmodel="default"\n')
        code, out, _ = self.dry("implement", "--files", "web/components/Nav.tsx")
        self.assertEqual(code, 0)
        self.assertIn("route: auto frontend → tier.standard", out)
        self.assertIn("fake_agent.py standard", out)

    def test_implement_no_files_uses_role_default(self):
        self.glob_cfg(TIERS + '[role.implement]\nharness="fake"\nmodel="default"\n')
        _, out, _ = self.dry("implement")
        self.assertIn("route: role default", out)
        self.assertIn("fake_agent.py default", out)

    def test_hint_names_builtin_kind(self):
        self.glob_cfg(TIERS + '[role.implement]\nharness="fake"\nmodel="default"\n')
        _, out, _ = self.dry("implement", "--hint", "mechanical", "--files", "server/x.go")
        self.assertIn("fake_agent.py cheap", out)

    def test_kinds_ignored_without_tiers(self):
        self.glob_cfg(FAKE + '[role.implement]\nharness="fake"\nmodel="default"\n')
        _, out, _ = self.dry("implement", "--files", "web/components/Nav.tsx")
        self.assertIn("fake_agent.py default", out)

    def test_config_hint_by_paths_beats_builtin(self):
        self.glob_cfg(TIERS + '[role.implement]\nharness="fake"\nmodel="default"\n'
                      '[role.implement.hint.ui]\nwhen="our web app"\npaths=["web/*"]\nharness="fake"\nmodel="ui"\n')
        _, out, _ = self.dry("implement", "--files", "web/components/Nav.tsx")
        self.assertIn("route: hint ui (paths)", out)
        self.assertIn("fake_agent.py ui", out)

    def test_config_hint_by_name_and_tier(self):
        self.glob_cfg(TIERS + '[role.implement]\nharness="fake"\nmodel="default"\n'
                      '[role.implement.hint.risky]\ntier="strong"\n')
        _, out, _ = self.dry("implement", "--hint", "risky")
        self.assertIn("fake_agent.py strong", out)

    def test_unknown_hint_falls_back(self):
        self.glob_cfg(TIERS + '[role.implement]\nharness="fake"\nmodel="default"\n')
        code, out, _ = self.dry("implement", "--hint", "nope")
        self.assertEqual(code, 0)
        self.assertIn("fake_agent.py default", out)
        self.assertIn("unknown hint 'nope'", out)

    PANEL = '[role.review]\npanel=[{harness="fake",model="p1"},{harness="fake",model="p2"}]\n'

    def test_review_defaults_to_one_reviewer(self):
        self.glob_cfg(TIERS + self.PANEL)
        _, out, _ = self.dry("review", "--files", "server/x.go")
        self.assertEqual(out.count("headless:"), 1, out)
        self.assertIn("route: single", out)

    def test_review_risky_files_get_panel(self):
        self.glob_cfg(TIERS + self.PANEL)
        _, out, _ = self.dry("review", "--files", "server/auth/token.go")
        self.assertEqual(out.count("headless:"), 2, out)
        self.assertIn("route: panel (security)", out)

    def test_review_panel_flag_and_untracked_detection(self):
        self.glob_cfg(TIERS + self.PANEL)
        self.assertEqual(self.dry("review", "--panel")[1].count("headless:"), 2)
        self.write(self.root, "payments/charge.py", "x\n")  # picked up from git, no --files
        _, out, _ = self.dry("review")
        self.assertIn("route: panel (security)", out)

    def test_review_big_diff_gets_panel(self):
        self.glob_cfg(TIERS + self.PANEL + '[rules]\npanel_diff_lines=5\n')
        f = self.write(self.root, "server/x.go", "a\n")
        R.subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        R.subprocess.run(["git", "-C", str(self.root), "-c", "user.email=t@t", "-c", "user.name=t",
                          "commit", "-qm", "i"], check=True)
        f.write_text("b\n" * 10)
        _, out, _ = self.dry("review")
        self.assertIn("route: panel (diff 11 lines)", out)

    def test_single_reviewer_is_not_the_implementer(self):
        self.glob_cfg(TIERS + '[role.implement]\nharness="fake"\nmodel="strong"\n'
                      '[role.review]\nharness="fake"\nmodel="strong"\n'
                      'panel=[{harness="fake",model="p1"}]\n')
        _, out, _ = self.dry("review", "--files", "Makefile")  # no kind: implement uses its role default
        self.assertIn("fake_agent.py p1", out)
        self.assertNotIn("fake_agent.py strong", out)

    def test_failure_escalates_one_tier_once(self):
        self.glob_cfg(FAKE + '[tier.cheap]\nharness="fake"\nmodel="fail"\n'
                      '[tier.standard]\nharness="fake"\nmodel="echo"\n')
        code, _, err = self.run_main("implement", "--brief", self.brief("the brief"),
                                     "--report", str(self.report()), "--hint", "docs")
        self.assertEqual(code, 0, err)
        text = self.report().read_text()
        self.assertIn("the brief", text)
        self.assertIn("previous attempt", text)  # the escalated child is told
        self.assertTrue((self.root / "out/r.failed.md").exists())
        recs = [json.loads(l) for l in (self.root / ".sstack/runs/index.jsonl").read_text().splitlines()]
        self.assertEqual([(r["model"], r["exit"]) for r in recs], [("fail", 1), ("echo", 0)])
        self.assertIn("escalated", recs[1]["route"])

    def test_escalation_can_be_turned_off(self):
        self.glob_cfg(FAKE + '[tier.cheap]\nharness="fake"\nmodel="fail"\n'
                      '[tier.standard]\nharness="fake"\nmodel="echo"\n[rules]\nauto_escalate=false\n')
        code, _, _ = self.run_main("implement", "--brief", self.brief(), "--report", str(self.report()),
                                   "--hint", "docs")
        self.assertEqual(code, 1)

    def test_routes_lists_kinds_and_hints(self):
        self.glob_cfg(TIERS + '[role.implement.hint.ui]\nwhen="our web app"\nharness="fake"\nmodel="ui"\n')
        code, out, _ = self.run_main("routes")
        self.assertEqual(code, 0)
        self.assertIn("frontend", out); self.assertIn("tier.standard → fake/standard", out)
        self.assertIn("implement.ui: our web app → fake/ui", out)

    def test_example_config_routes(self):
        self.example()
        _, out, _ = self.dry("implement", "--files", "web/components/Nav.tsx")
        self.assertIn("route: auto frontend → tier.standard", out)
        _, out, _ = self.dry("review", "--files", "server/x.go")
        self.assertEqual(out.count("headless:"), 1, out)



class ReviewFixTests(DispatchBase):
    PANEL, dry = RouteTests.PANEL, RouteTests.dry
    """Findings from the first real sstack review (codex), plus user-defined tiers."""
    def test_local_transport_wins_for_review(self):
        self.glob_cfg(TIERS + '[transport]\nmode="local"\n')
        code, out, _ = self.dry("review", "--files", "server/x.go")
        self.assertEqual((code, out.strip()), (3, "local"))

    def test_effort_does_not_make_a_different_reviewer(self):
        self.glob_cfg(FAKE + '[role.implement]\nharness="fake"\nmodel="same"\neffort="high"\n'
                      '[role.review]\nharness="fake"\nmodel="same"\neffort="low"\npanel=[{harness="fake",model="other"}]\n')
        _, out, _ = self.dry("review", "--files", "Makefile")
        self.assertIn("fake_agent.py other", out)

    def test_escalation_skips_the_implementer(self):
        import sstack_config as C
        self.glob_cfg(TIERS + '[role.implement]\nharness="fake"\nmodel="strong"\n')
        cfg = C.load(self.root)
        impl = {"harness": "fake", "model": "strong", "effort": None}
        self.assertIsNone(R.escalation(cfg, {"harness": "fake", "model": "standard", "effort": None}, avoid=impl))

    def test_files_flag_still_counts_diff_lines(self):
        self.glob_cfg(TIERS + self.PANEL + '[rules]\npanel_diff_lines=5\n')
        f = self.write(self.root, "server/x.go", "a\n")
        R.subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        R.subprocess.run(["git", "-C", str(self.root), "-c", "user.email=t@t", "-c", "user.name=t",
                          "commit", "-qm", "i"], check=True)
        f.write_text("b\n" * 10)
        _, out, _ = self.dry("review", "--files", "server/x.go")
        self.assertIn("route: panel (diff 11 lines)", out)

    # user-defined tiers
    CUSTOM = FAKE + ('[tier.ui-fast]\nharness="fake"\nmodel="uifast"\n'
                     '[tier.gpu]\nharness="fake"\nmodel="gpu"\n'
                     '[tier.big]\nharness="fake"\nmodel="big"\n'
                     '[routing.kinds]\nfrontend="ui-fast"\nbackend="gpu"\ndata="gpu"\n'
                     '[rules]\ntier_order=["ui-fast","gpu","big"]\n')

    def test_kinds_remap_to_custom_tiers(self):
        self.glob_cfg(self.CUSTOM)
        _, out, _ = self.dry("implement", "--files", "web/components/Nav.tsx")
        self.assertIn("route: auto frontend → tier.ui-fast", out)
        self.assertIn("fake_agent.py uifast", out)

    def test_new_kind_name_via_hint(self):
        self.glob_cfg(self.CUSTOM)
        _, out, _ = self.dry("implement", "--hint", "data")
        self.assertIn("fake_agent.py gpu", out)

    def test_custom_tier_order_escalates(self):
        import sstack_config as C
        self.glob_cfg(self.CUSTOM)
        m, tier = R.escalation(C.load(self.root), {"harness": "fake", "model": "uifast", "effort": None})
        self.assertEqual((m["model"], tier), ("gpu", "gpu"))

    def test_undefined_tier_is_a_config_error(self):
        self.glob_cfg(self.CUSTOM + '[role.implement.hint.x]\ntier="nope"\n')
        code, _, err = self.dry("implement", "--hint", "x")
        self.assertEqual(code, 1)
        self.assertIn("tier 'nope'", err)
        self.glob_cfg(FAKE + '[tier.a]\nharness="fake"\nmodel="a"\n[routing.kinds]\nfrontend="missing"\n')
        code, _, err = self.dry("implement", "--files", "web/Nav.tsx")
        self.assertEqual(code, 1)
        self.assertIn("tier 'missing'", err)

    def test_routes_shows_custom_tiers_and_remaps(self):
        self.glob_cfg(self.CUSTOM)
        _, out, _ = self.run_main("routes")
        self.assertIn("tier.gpu → fake/gpu", out)
        self.assertIn("frontend: tier.ui-fast → fake/uifast", out)
        self.assertIn("data: tier.gpu → fake/gpu", out)
