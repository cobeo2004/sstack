"""Review findings on stage variants: the routed implementer is never a variant reviewer, and a
variant's brief never overwrites the run's shared brief."""
import unittest

from test_doctor import SmokeTests
from test_variants import REVIEW_SINGLE, VariantBase
import sstack_dispatch as D


class VariantReviewFixes(VariantBase):
    def test_variant_equal_to_the_routed_implementer_is_dropped(self):
        # auth/ routes implement to tier.strong (fake/echo2), not roles/implement.toml (fake/impl)
        self.cfg(review='[role.review]\nharness="fake"\nmodel="other"\nmode="single"\n',
                 extra='[tier.strong]\nharness="fake"\nmodel="echo2"\n')
        self.variant("review", "security", 'harness = "fake"\nmodel = "echo2"\n')
        code, _, err = self.go("review", "--files", "auth/login.py")
        self.assertEqual(code, 0, err)
        self.assertFalse(self.out("r-security.md").exists(), err)

    def test_a_variant_named_skills_does_not_leak_its_lens(self):
        self.cfg(review=REVIEW_SINGLE + 'skills = ["no-such-skill"]\n')  # a missing skill still derives brief.skills.md
        self.variant("review", "skills", 'harness = "fake"\nmodel = "other"\n', lens="SKILLS LENS\n")
        self.variant("review", "zzz", 'harness = "fake"\nmodel = "other2"\n', lens="ZZZ LENS\n")
        code, _, err = self.go()
        self.assertEqual(code, 0, err)
        self.assertNotIn("SKILLS LENS", self.out("r.md").read_text())
        self.assertNotIn("SKILLS LENS", self.out("r-zzz.md").read_text())
        self.assertIn("SKILLS LENS", self.out("r-skills.md").read_text())


class VariantSmokeCheck(SmokeTests):
    def test_variant_canary_matches_its_index_line(self):
        members = ["fake/x", "fake/x#review/security"]
        d = self.crafted([], roles={"review": members})
        for name in ("review.md", "review-security.md"):
            (d / name).write_text("CANARY t\n")
        base = {"harness": "fake", "model": "x", "exit": 0}
        for name, extra in (("review.md", {}), ("review-security.md", {"variant": "review/security"})):
            D.append_index(self.root, {**base, **extra, "report": (d / name).relative_to(self.root).as_posix()})
        code, out, err = self.doctor("--smoke", "--check", str(d))
        self.assertIn("PASS review fake/x#review/security", out, err)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(cls(n) for cls in (VariantReviewFixes, VariantSmokeCheck)
                              for n in sorted(cls.__dict__) if n.startswith("test_"))
