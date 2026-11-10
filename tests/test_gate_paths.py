"""Review findings on sstack-gate: git-quoted file names and symlinked manifest paths."""
import hashlib, os, unittest

from test_gate import GateTests


class GatePathTests(GateTests):
    def test_non_ascii_protected_file_still_fails(self):
        self.base(verify="true", protected=["tests/*"], files={"tests/café.py": "assert True\n"})
        self.write(self.root, "tests/café.py", "assert False\n")
        self.gated(self.gate())

    def test_non_ascii_backend_file_still_owes_a_diagram(self):
        self.base(verify="true", files={"src/café.py": "x = 1\n"})
        self.write(self.root, "src/café.py", "x = 2\n")
        run = self.run_dir()
        self.gated(self.gate("--run", str(run), "--pr"))
        self.expect(self.verdict(run, "1-pr.md"), "FAIL", "diagram")

    def test_manifest_path_through_a_symlink_out_of_the_repo_fails(self):
        self.base(verify="true")
        outside = self.root.parent / "outside.txt"
        outside.write_text("x\n")
        os.symlink(outside, self.root / "alias")
        run = self.run_dir()
        d = run / "protected"
        d.mkdir()
        (d / "alias").write_text("x\n")
        digest = hashlib.sha256(b"x\n").hexdigest()
        (d / "SHA256SUMS").write_text(f"{digest}  alias\n")
        self.gated(self.gate("--run", str(run)))
        self.expect(self.verdict(run), "FAIL", "alias")


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(GatePathTests(n) for n in sorted(GatePathTests.__dict__) if n.startswith("test_"))
