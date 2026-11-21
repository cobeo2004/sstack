"""Write-lock regressions from the PR A review: mutex unlink race, panel release on the last record."""
import contextlib, io, os, sys, threading, time, unittest
from unittest import mock

from helpers import TempEnv
import sstack_dispatch as D


class WriteLockRaceTests(TempEnv):
    def test_concurrent_index_appends_keep_every_line_whole(self):
        # panel members append from parallel threads; Windows' emulated append mode tore lines
        big = "x" * 20000
        ts = [threading.Thread(target=lambda n=n: [D.append_index(self.root, {"n": n, "pad": big}) for _ in range(20)])
              for n in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        lines = (self.root / D.INDEX).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 160)
        self.assertTrue(all(__import__("json").loads(l)["pad"] == big for l in lines))

    def test_flock_windows_retries_after_oserror(self):
        f = mock.Mock()
        f.fileno.return_value = 7
        fake = mock.Mock()
        fake.LK_LOCK = 2
        fake.locking.side_effect = [OSError("busy"), None]
        with mock.patch.object(D, "_WINDOWS", True), mock.patch.dict(sys.modules, {"msvcrt": fake}):
            D._flock(f)
        f.seek.assert_called_once_with(D.LOCK_BYTE)
        self.assertEqual([c.args for c in fake.locking.call_args_list], [(7, 2, 1), (7, 2, 1)])

    @unittest.skipIf(os.name == "nt", "Windows can't unlink an open file; lock_release leaves the mutex there")
    def test_unlinked_mutex_does_not_admit_two_holders(self):
        D.lock_acquire(self.root, "A", "A", "implement", ["x"], 1, False, 1800)
        held, got = [], []
        m0 = D._mutex(self.root)
        t1 = threading.Thread(target=lambda: held.append(D._mutex(self.root)))
        t1.start()
        time.sleep(0.2)  # t1 waits on m0's inode
        (self.root / D.RUNS / f"{D.LOCK}.mutex").unlink()  # what lock_release does on the last holder
        m0.close()
        t1.join(2)
        t2 = threading.Thread(target=lambda: got.append(D._mutex(self.root)))
        t2.start()
        t2.join(0.5)
        try:
            self.assertEqual((len(held), len(got)), (1, 0))
        finally:
            for f in held:
                f.close()
            t2.join(2)
            for f in got:
                f.close()

    def test_panel_keeps_the_lock_until_its_last_record(self):
        report = self.root / D.RUNS / "task" / "r.md"
        report.parent.mkdir(parents=True)
        report.write_text("ok")
        members = [{"harness": "fake", "model": "one"}, {"harness": "fake", "model": "two"}]
        run = D.new_run(self.root, "implement", members, report, False, {"title": "t", "via": "auto"})
        D.lock_acquire(self.root, D.lock_owner(self.root, report), str(run), "implement", ["x"], 1, False, 1800)

        def record(m):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                D.record(["implement", "--report", str(report), "--member", m, "--exit", "0", "--run-dir", str(run)])

        record("fake/one")
        self.assertIsNotNone(D.lock_acquire(self.root, "B", "B", "implement", ["x"], 1, False, 1800))
        record("fake/two")
        self.assertIsNone(D.lock_acquire(self.root, "B", "B", "implement", ["x"], 1, False, 1800))
