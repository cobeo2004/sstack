---
summary: What keeps sstack running on native Windows (locks, processes, launchers, encoding) and the test-suite traps behind it
paths: lib/sstack_ade.py, lib/sstack_dispatch.py, lib/sstack_gate.py, lib/sstack_workflow.py
updated: 0b25716
---
# Windows portability

The windows-latest CI job is the only Windows proof; a Mac or Linux run can't show these.

## Product code
- Process control lives in `sstack_ade`: spawn with `**NEW_GROUP`, stop with `kill_group`,
  run a hook or `run.sh` through `launch(path)`, a shell command through `sh()`, a harness CLI
  through `resolve(argv)`. Windows' CreateProcess ignores shebangs and PATHEXT, so a bare
  `codex` misses `codex.cmd` until `shutil.which` resolves it. A full path to a `.cmd` runs fine.
- `_flock` locks one byte at `LOCK_BYTE` (2**30) with `msvcrt.locking` on Windows. msvcrt locks are
  mandatory: a lock on byte 0 made `snapshot()` fail reading run.lock (Errno 13). Windows won't delete an open file, so
  `lock_release` leaves `implement.lock.mutex` behind there; `_mutex`'s inode check copes.
- Lock owners are POSIX strings on both sides (`lock_owner` and `sstack_workflow.release`).
  Native separators made release miss on Windows, so the lock was never dropped.
- `rel()` returns POSIX paths: readonly skips, index lines and prune output compare with git's `/`.
- Built-in hooks and `sstack-gate` find CLIs through `shutil.which` (`gh.cmd`, `orca.cmd`).
- Every text read, write and subprocess call passes `encoding="utf-8"`.
  `tests/test_encoding.py` fails on a new call that doesn't.
- Python 3.12+ allows the same quote inside an f-string; 3.11, the floor, doesn't.
  `ast.parse(feature_version=(3, 11))` still accepts it, so `test_encoding` compiles with a real
  `python3.11` when one is on PATH (the CI 3.11 jobs catch it anyway).

## Repo and tests
- `.gitattributes` is `* -text`: Windows checkouts default to autocrlf and would rewrite
  byte-compared fixtures. `bin/*.cmd` are stored with CRLF. A local `core.autocrlf=input` had
  quietly committed them as LF before the attribute existed.
- Tests set `USERPROFILE` beside `HOME` (Windows' `Path.home()` reads it). `TempEnv` fails if
  `home_dir()` escapes its temp dir.
- On Windows, `tests/fakes/*` are git symlinks that check out as plain files. `helpers.FAKES` then
  points at a temp dir of `<name>.cmd` wrappers around `fake_cli.py`.
- Tests: write fixtures with `newline=""` (TempEnv.write) and read with `encoding="utf-8"`; Windows'
  default is CRLF and cp1252. A printed command shlex-quotes backslash paths: parse it with `shlex.split`.
- Symlink tests skip through `can_symlink()`, and `link_or_copy` copies where a symlink stood in
  for a copy. Run bin/ scripts in tests as `[sys.executable, path]`.

## Running the suite inside an Orca session
`ORCA_AGENT_SESSION_ID` leaks into two `test_ui` ADE-detection tests. Run with
`env -u TMPDIR -u ORCA_AGENT_SESSION_ID python3 -m unittest discover -s tests`.
