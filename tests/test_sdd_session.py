from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sdd_session  # noqa: E402
from sdd_session import SessionError  # noqa: E402


DEAD_PID = 2**22  # above every plausible live pid, and never pid 1


class SessionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.git("init", "-b", "main")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "SDD Test")
        (self.root / "sdd").mkdir()
        (self.root / "sdd" / "roadmap.md").write_text("# Roadmap\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "fixture")
        self.set_session("session-a", os.getpid())

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        )

    def set_session(self, session_id: str, pid: int) -> None:
        for key, value in ((sdd_session.SESSION_ENV, session_id), (sdd_session.PID_ENV, str(pid))):
            previous = os.environ.get(key)
            os.environ[key] = value
            self.addCleanup(self._restore, key, previous)

    @staticmethod
    def _restore(key: str, previous: str | None) -> None:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous

    def registry(self) -> dict:
        return sdd_session.read_registry(sdd_session.registry_path(self.root))

    def write_registry(self, data: dict) -> None:
        sdd_session.write_registry(sdd_session.registry_path(self.root), data)

    def change(self, feature: str) -> None:
        (self.root / "sdd" / "changes" / feature).mkdir(parents=True)


class RegistryLocationTests(SessionTestCase):
    def test_registry_lives_in_the_shared_git_directory(self) -> None:
        """Shared by every worktree, never committed, invisible to git status."""
        path = sdd_session.registry_path(self.root)
        self.assertEqual(self.root / ".git" / "sdd" / "sessions.json", path)
        sdd_session.claim(self.root, "alpha")
        self.assertEqual("", self.git("status", "--porcelain").stdout.strip())

    def test_a_linked_worktree_shares_the_same_registry(self) -> None:
        linked = self.root / ".claude" / "worktrees" / "alpha"
        self.git("worktree", "add", "-b", "sdd/alpha", str(linked))
        self.assertEqual(
            sdd_session.registry_path(self.root),
            sdd_session.registry_path(linked),
        )

    def test_outside_a_repository_is_an_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SessionError) as caught:
                sdd_session.registry_path(Path(directory))
            self.assertIn("not inside a git repository", str(caught.exception))

    def test_a_corrupted_registry_is_rebuilt_not_fatal(self) -> None:
        path = sdd_session.registry_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        self.assertEqual({}, self.registry()["sessions"])


class LivenessTests(SessionTestCase):
    def test_a_live_pid_is_alive_and_a_dead_one_is_not(self) -> None:
        self.assertTrue(sdd_session.is_alive(os.getpid()))
        self.assertFalse(sdd_session.is_alive(DEAD_PID))

    def test_a_missing_or_bogus_pid_is_not_alive(self) -> None:
        for value in (None, "", "abc", 0, -1):
            self.assertFalse(sdd_session.is_alive(value), value)

    def test_prune_drops_dead_sessions_and_keeps_worktree_bindings(self) -> None:
        """A session dies at the end of every conversation; its worktree does not."""
        self.write_registry(
            {
                "schema": 1,
                "sessions": {"gone": {"pid": DEAD_PID, "feature": "alpha"}},
                "worktrees": {"alpha": {"path": str(self.root)}},
            }
        )
        data = self.registry()
        self.assertEqual(["gone"], sdd_session.prune(data))
        self.assertEqual({}, data["sessions"])
        self.assertIn("alpha", data["worktrees"])


class CheckTests(SessionTestCase):
    def test_a_lone_session_is_clear(self) -> None:
        report = sdd_session.check(self.root, "alpha")
        self.assertFalse(report["conflict"])
        self.assertEqual([], report["reasons"])

    def test_another_live_session_is_a_conflict(self) -> None:
        self.write_registry(
            {
                "schema": 1,
                "sessions": {
                    "session-b": {
                        "pid": os.getpid(),
                        "feature": "beta",
                        "worktree": "/somewhere/beta",
                    }
                },
                "worktrees": {},
            }
        )
        report = sdd_session.check(self.root, "alpha")
        self.assertTrue(report["conflict"])
        self.assertIn("another live session", report["reasons"][0])

    def test_a_dead_session_is_not_a_conflict(self) -> None:
        self.write_registry(
            {
                "schema": 1,
                "sessions": {"gone": {"pid": DEAD_PID, "feature": "beta"}},
                "worktrees": {},
            }
        )
        self.assertFalse(sdd_session.check(self.root, "alpha")["conflict"])

    def test_check_never_writes_the_registry(self) -> None:
        """It is called by read-only phases, whose contract is to change nothing."""
        self.write_registry(
            {
                "schema": 1,
                "sessions": {"gone": {"pid": DEAD_PID, "feature": "beta"}},
                "worktrees": {},
            }
        )
        before = sdd_session.registry_path(self.root).read_bytes()
        sdd_session.check(self.root, "alpha")
        self.assertEqual(before, sdd_session.registry_path(self.root).read_bytes())

    def test_head_on_another_feature_branch_is_a_conflict(self) -> None:
        self.git("checkout", "-b", "sdd/beta")
        report = sdd_session.check(self.root, "alpha")
        self.assertTrue(report["conflict"])
        self.assertIn("HEAD is on sdd/beta", report["reasons"][0])

    def test_head_on_the_same_feature_branch_is_not_a_conflict(self) -> None:
        self.git("checkout", "-b", "sdd/alpha")
        self.assertFalse(sdd_session.check(self.root, "alpha")["conflict"])

    def test_an_in_flight_change_for_another_feature_is_a_conflict(self) -> None:
        """Evidence survives the session that produced it: it is on disk."""
        self.change("beta")
        report = sdd_session.check(self.root, "alpha")
        self.assertTrue(report["conflict"])
        self.assertIn("in-flight changes for beta", report["reasons"][0])

    def test_our_own_change_directory_is_not_a_conflict(self) -> None:
        self.change("alpha")
        self.assertFalse(sdd_session.check(self.root, "alpha")["conflict"])

    def test_dirtiness_is_reported_with_the_branch_mismatch(self) -> None:
        self.git("checkout", "-b", "sdd/beta")
        (self.root / "sdd" / "roadmap.md").write_text("# Roadmap\n\n- [ ] x\n", encoding="utf-8")
        report = sdd_session.check(self.root, "alpha")
        self.assertTrue(report["dirty"])
        self.assertIn("the tree is dirty", report["reasons"][0])

    def test_check_reports_whether_it_is_in_a_linked_worktree(self) -> None:
        linked = self.root / ".claude" / "worktrees" / "alpha"
        self.git("worktree", "add", "-b", "sdd/alpha", str(linked))
        self.assertFalse(sdd_session.check(self.root, "alpha")["in_linked_worktree"])
        self.assertTrue(sdd_session.check(linked, "alpha")["in_linked_worktree"])


class ClaimTests(SessionTestCase):
    def test_claim_registers_the_session_and_binds_the_feature(self) -> None:
        sdd_session.claim(self.root, "alpha")
        data = self.registry()
        self.assertEqual("alpha", data["sessions"]["session-a"]["feature"])
        self.assertEqual(str(self.root), data["worktrees"]["alpha"]["path"])

    def test_claim_is_idempotent_and_preserves_the_start_time(self) -> None:
        sdd_session.claim(self.root, "alpha")
        started = self.registry()["sessions"]["session-a"]["started"]
        sdd_session.claim(self.root, "alpha")
        self.assertEqual(started, self.registry()["sessions"]["session-a"]["started"])

    def test_a_feature_held_by_a_live_session_cannot_be_claimed(self) -> None:
        self.write_registry(
            {
                "schema": 1,
                "sessions": {
                    "session-b": {
                        "pid": os.getpid(),
                        "feature": "alpha",
                        "worktree": "/somewhere",
                    }
                },
                "worktrees": {},
            }
        )
        with self.assertRaises(SessionError) as caught:
            sdd_session.claim(self.root, "alpha")
        self.assertIn("claimed by live session session-b", str(caught.exception))

    def test_a_feature_held_by_a_dead_session_can_be_taken_over(self) -> None:
        self.write_registry(
            {
                "schema": 1,
                "sessions": {"gone": {"pid": DEAD_PID, "feature": "alpha"}},
                "worktrees": {},
            }
        )
        sdd_session.claim(self.root, "alpha")
        self.assertEqual("alpha", self.registry()["sessions"]["session-a"]["feature"])

    def test_a_feature_cannot_be_rebound_to_a_second_existing_worktree(self) -> None:
        """Half the work in one tree and half in another is the failure to prevent."""
        other = self.root / ".claude" / "worktrees" / "alpha"
        self.git("worktree", "add", "-b", "sdd/alpha", str(other))
        sdd_session.claim(self.root, "alpha", worktree=other)
        with self.assertRaises(SessionError) as caught:
            sdd_session.claim(self.root, "alpha", worktree=self.root)
        self.assertIn("already bound to", str(caught.exception))

    def test_a_binding_whose_worktree_vanished_is_replaced(self) -> None:
        self.write_registry(
            {
                "schema": 1,
                "sessions": {},
                "worktrees": {"alpha": {"path": str(self.root / "gone")}},
            }
        )
        sdd_session.claim(self.root, "alpha")
        self.assertEqual(str(self.root), self.registry()["worktrees"]["alpha"]["path"])

    def test_without_a_session_id_it_binds_but_registers_nothing(self) -> None:
        self.set_session("", os.getpid())
        message = sdd_session.claim(self.root, "alpha")
        self.assertIn("no session was registered", message)
        self.assertEqual({}, self.registry()["sessions"])
        self.assertIn("alpha", self.registry()["worktrees"])


class ResolveReleaseTests(SessionTestCase):
    def test_resolve_returns_the_bound_worktree(self) -> None:
        sdd_session.claim(self.root, "alpha")
        self.assertEqual(str(self.root), sdd_session.resolve(self.root, "alpha"))

    def test_resolve_is_empty_for_an_unbound_feature(self) -> None:
        self.assertEqual("", sdd_session.resolve(self.root, "nope"))

    def test_resolve_treats_a_vanished_worktree_as_unbound(self) -> None:
        """A stale path would send the next phase into a directory that is gone."""
        self.write_registry(
            {
                "schema": 1,
                "sessions": {},
                "worktrees": {"alpha": {"path": str(self.root / "gone")}},
            }
        )
        self.assertEqual("", sdd_session.resolve(self.root, "alpha"))

    def test_release_drops_the_binding_and_clears_the_session_feature(self) -> None:
        sdd_session.claim(self.root, "alpha")
        self.assertIn("Released 'alpha'", sdd_session.release(self.root, "alpha"))
        data = self.registry()
        self.assertNotIn("alpha", data["worktrees"])
        self.assertEqual("", data["sessions"]["session-a"]["feature"])

    def test_releasing_an_unknown_feature_says_so(self) -> None:
        self.assertIn("No worktree binding", sdd_session.release(self.root, "nope"))


class OrphanTests(SessionTestCase):
    def test_a_binding_without_a_worktree_is_an_orphan(self) -> None:
        self.write_registry(
            {
                "schema": 1,
                "sessions": {},
                "worktrees": {"alpha": {"path": str(self.root / "gone")}},
            }
        )
        orphans = sdd_session.orphan_bindings(self.root)
        self.assertEqual([("alpha", "missing")], [(o["feature"], o["reason"]) for o in orphans])

    def test_a_worktree_for_an_archived_change_is_an_orphan(self) -> None:
        (self.root / "sdd" / "changes" / "archive" / "2026-01-01-alpha").mkdir(parents=True)
        sdd_session.claim(self.root, "alpha")
        orphans = sdd_session.orphan_bindings(self.root)
        self.assertEqual([("alpha", "archived")], [(o["feature"], o["reason"]) for o in orphans])

    def test_a_live_binding_is_not_an_orphan(self) -> None:
        sdd_session.claim(self.root, "alpha")
        self.assertEqual([], sdd_session.orphan_bindings(self.root))


class CommandLineTests(SessionTestCase):
    def test_check_exits_one_on_conflict_and_zero_when_clear(self) -> None:
        self.assertEqual(
            0, sdd_session.main(["--root", str(self.root), "check", "--feature", "alpha"])
        )
        self.change("beta")
        self.assertEqual(
            1, sdd_session.main(["--root", str(self.root), "check", "--feature", "alpha"])
        )

    def test_resolve_exits_one_when_unbound(self) -> None:
        self.assertEqual(1, sdd_session.main(["--root", str(self.root), "resolve", "alpha"]))
        sdd_session.claim(self.root, "alpha")
        self.assertEqual(0, sdd_session.main(["--root", str(self.root), "resolve", "alpha"]))

    def test_a_refused_claim_exits_two(self) -> None:
        """Distinct from a conflict verdict: this one is an error, not an answer."""
        self.write_registry(
            {
                "schema": 1,
                "sessions": {"session-b": {"pid": os.getpid(), "feature": "alpha"}},
                "worktrees": {},
            }
        )
        self.assertEqual(2, sdd_session.main(["--root", str(self.root), "claim", "alpha"]))

    def test_json_output_is_parseable(self) -> None:
        report = sdd_session.check(self.root, "alpha")
        self.assertEqual(report, json.loads(json.dumps(report)))


if __name__ == "__main__":
    unittest.main()
