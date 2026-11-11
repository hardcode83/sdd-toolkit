"""The design-review write guard, exercised against real git worktrees."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from worktree_fingerprint import main  # noqa: E402


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


class WriteGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        git(self.root, "init", "-q")
        (self.root / ".gitignore").write_text("build/\n")
        (self.root / "tracked.md").write_text("one\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "base")
        change = self.root / "sdd/changes/f"
        change.mkdir(parents=True)
        (change / "design.md").write_text("draft\n")  # untracked, as during review
        self.assertEqual(0, self.run_guard("snapshot")[0])

    def run_guard(self, command: str) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main([command, "--root", str(self.root)])
        return code, out.getvalue()

    def assertChanged(self, path: str) -> None:
        code, out = self.run_guard("compare")
        self.assertEqual(1, code)
        self.assertIn(path, out.splitlines())

    def test_no_change_is_clean_and_the_snapshot_does_not_dirty_the_tree(self) -> None:
        self.assertEqual((0, ""), self.run_guard("compare"))

    def test_rewriting_an_untracked_design_is_caught(self) -> None:
        (self.root / "sdd/changes/f/design.md").write_text("tampered\n")
        self.assertChanged("sdd/changes/f/design.md")

    def test_a_new_untracked_file_is_caught(self) -> None:
        (self.root / "new.py").write_text("x = 1\n")
        self.assertChanged("new.py")

    def test_editing_or_deleting_a_tracked_file_is_caught(self) -> None:
        (self.root / "tracked.md").write_text("two\n")
        self.assertChanged("tracked.md")
        self.assertEqual(0, self.run_guard("snapshot")[0])  # compare consumed the last one
        (self.root / "tracked.md").unlink()
        self.assertChanged("tracked.md")

    def test_a_commit_is_caught(self) -> None:
        git(self.root, "commit", "-q", "--allow-empty", "-m", "sneaky")
        self.assertChanged("HEAD")

    def test_a_symlink_is_recorded_by_target_not_followed(self) -> None:
        os.symlink("tracked.md", self.root / "link")
        self.assertChanged("link")

    def test_ignored_paths_are_out_of_scope(self) -> None:
        (self.root / "build").mkdir()
        (self.root / "build/out.bin").write_text("artifact\n")
        self.assertEqual((0, ""), self.run_guard("compare"))

    def test_running_from_a_subdirectory_still_guards_the_whole_repo(self) -> None:
        sub = self.root / "sdd/changes/f"
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(0, main(["snapshot", "--root", str(sub)]))
        (self.root / "tracked.md").write_text("outside the subtree\n")
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["compare", "--root", str(sub)])
        self.assertEqual(1, code)
        self.assertIn("tracked.md", out.getvalue().splitlines())

    def test_an_executable_bit_change_is_caught(self) -> None:
        os.chmod(self.root / "tracked.md", 0o755)
        self.assertChanged("tracked.md")

    def test_compare_consumes_the_snapshot_so_it_is_never_reused(self) -> None:
        self.assertEqual((0, ""), self.run_guard("compare"))
        code, _ = self.run_guard("compare")
        self.assertEqual(2, code)

    def test_a_missing_snapshot_cannot_vouch(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["compare", "--root", str(self.root), "--before", str(self.root / "nope.json")])
        self.assertEqual(2, code)


if __name__ == "__main__":
    unittest.main()
