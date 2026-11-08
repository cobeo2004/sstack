import tempfile
from pathlib import Path

from helpers import TempEnv
import sstack_config as C

HARN = '[harness.pi]\nheadless=["pi"]\n[harness.codex]\nheadless=["codex"]\n'


class ConfigTests(TempEnv):
    def test_role_table_replaced_whole(self):
        self.glob_cfg(HARN + '[role.implement]\nharness="pi"\nmodel="m1"\neffort="high"\n')
        self.repo_cfg('[role.implement]\nharness="codex"\nmodel="m2"\n')
        self.assertEqual(C.load(self.root)["role"]["implement"], {"harness": "codex", "model": "m2"})

    def test_scalars_merge(self):
        self.glob_cfg('[transport]\ntimeout_min=30\nmode="auto"\n')
        self.local_cfg('[transport]\nmode="headless"\n')
        t = C.load(self.root)["transport"]
        self.assertEqual((t["mode"], t["timeout_min"]), ("headless", 30))

    def test_local_overrides_repo(self):
        self.glob_cfg(HARN)
        self.repo_cfg('[role.implement]\nharness="codex"\n')
        self.local_cfg('[role.implement]\nharness="pi"\n')
        self.assertEqual(C.resolve(C.load(self.root), "implement")[0]["harness"], "pi")

    def test_unlisted_role_is_local(self):
        self.glob_cfg(HARN)
        self.assertIsNone(C.resolve(C.load(self.root), "investigate"))

    def test_harness_local_is_local(self):
        self.glob_cfg(HARN + '[role.implement]\nharness="local"\n')
        self.assertIsNone(C.resolve(C.load(self.root), "implement"))

    def test_panel_drops_implementer(self):
        self.glob_cfg(HARN + '[role.implement]\nharness="pi"\nmodel="m1"\n'
                      '[role.review]\npanel=[{harness="pi",model="m1"},{harness="codex",model="x"}]\n'
                      '[rules]\nreview_not_implementer=true\n')
        self.assertEqual(C.resolve(C.load(self.root), "review"),
                         [{"harness": "codex", "model": "x", "effort": None}])

    def test_unknown_harness_raises(self):
        self.glob_cfg(HARN + '[role.implement]\nharness="nope"\n')
        with self.assertRaises(C.ConfigError):
            C.resolve(C.load(self.root), "implement")

    def test_bad_toml_names_file(self):
        self.repo_cfg("role = [")
        with self.assertRaises(C.ConfigError) as cm:
            C.load(self.root)
        self.assertIn(".sstack/config.toml", str(cm.exception))

    def test_no_git_root_uses_global_only(self):
        self.glob_cfg('[transport]\nmode="auto"\n')
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(C.git_root(Path(d)))
        self.assertEqual(C.load(None), {"transport": {"mode": "auto"}})

    def test_source_layer(self):
        self.glob_cfg(HARN + '[role.implement]\nharness="pi"\n')
        self.local_cfg('[role.implement]\nharness="codex"\n')
        self.assertEqual(C.source_layer(self.root, "role.implement"), "local")
        self.assertEqual(C.source_layer(self.root, "harness.pi"), "global")
        self.assertIsNone(C.source_layer(self.root, "role.plan"))
