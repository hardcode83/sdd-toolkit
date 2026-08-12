from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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


class IsolationPolicyTests(SessionTestCase):
    """`sdd/project.md` decides what a CLEAR verdict means.

    Evidence alone answers the wrong question: an empty clone is always CLEAR,
    so the first feature stayed in the main clone and manufactured the very
    evidence the second one is then told about (ADR 0002).
    """

    def project(self, body: str) -> None:
        (self.root / "sdd" / "project.md").write_text(body, encoding="utf-8")

    def test_a_project_that_declares_nothing_keeps_todays_behaviour(self) -> None:
        policy = sdd_session.read_isolation_policy(self.root)
        self.assertEqual("on-conflict", policy.policy)
        self.assertEqual("", policy.source)
        self.assertTrue(policy.valid)

    def test_a_missing_project_file_is_not_an_error(self) -> None:
        """The policy is read on the hot path of every phase, before /sdd:init."""
        self.assertEqual(
            "on-conflict", sdd_session.read_isolation_policy(self.root).policy
        )

    def test_every_markdown_shape_of_the_same_line_is_read(self) -> None:
        for line in (
            "isolation: always",
            "- isolation: always",
            "* isolation: always",
            "**isolation**: always",
            "isolation: `always`",
            "Isolation:  ALWAYS",
        ):
            with self.subTest(line=line):
                self.project(f"# Project\n\n## Worktree bootstrap\n\n{line}\n")
                policy = sdd_session.read_isolation_policy(self.root)
                self.assertEqual("always", policy.policy)
                self.assertEqual("sdd/project.md", policy.source)

    def test_a_declaration_inside_an_html_comment_is_documentation(self) -> None:
        """The scaffold template explains both values in a comment; reading that
        as active would enable a policy nobody chose."""
        self.project(
            "# Project\n\n<!-- isolation: always — o `on-conflict` -->\n"
        )
        policy = sdd_session.read_isolation_policy(self.root)
        self.assertEqual("on-conflict", policy.policy)
        self.assertEqual("", policy.source)

    def test_an_unrecognised_value_degrades_loudly_not_silently(self) -> None:
        self.project("# Project\n\nisolation: alway\n")
        policy = sdd_session.read_isolation_policy(self.root)
        self.assertEqual("on-conflict", policy.policy)
        self.assertFalse(policy.valid)
        self.assertEqual("alway", policy.declared)

    def test_always_isolates_a_clone_with_no_evidence_at_all(self) -> None:
        self.project("# Project\n\nisolation: always\n")
        report = sdd_session.check(self.root, "alpha")
        self.assertFalse(report["conflict"], "the check must not invent evidence")
        self.assertTrue(report["isolate"])
        self.assertEqual([], report["reasons"])

    def test_on_conflict_still_works_in_place_when_clear(self) -> None:
        self.project("# Project\n\nisolation: on-conflict\n")
        report = sdd_session.check(self.root, "alpha")
        self.assertFalse(report["conflict"])
        self.assertFalse(report["isolate"])

    def test_a_conflict_isolates_whatever_the_policy_says(self) -> None:
        self.project("# Project\n\nisolation: on-conflict\n")
        self.change("beta")
        report = sdd_session.check(self.root, "alpha")
        self.assertTrue(report["conflict"])
        self.assertTrue(report["isolate"])

    def test_the_verdict_keeps_its_exit_code_under_always(self) -> None:
        """A policy that turned CLEAR into exit 1 would make every later reading
        of the verdict a lie — the policy decides the action, not the evidence."""
        self.project("# Project\n\nisolation: always\n")
        self.assertEqual(
            0,
            sdd_session.main(["--root", str(self.root), "check", "--feature", "alpha"]),
        )

    def test_the_rendered_action_line_says_which_one_applies(self) -> None:
        self.project("# Project\n\nisolation: always\n")
        rendered = sdd_session.render_check(sdd_session.check(self.root, "alpha"))
        self.assertIn("CLEAR", rendered)
        self.assertIn("ISOLATE", rendered)
        self.assertIn("isolation: always", rendered)

        self.project("# Project\n")
        rendered = sdd_session.render_check(sdd_session.check(self.root, "alpha"))
        self.assertIn("WORK HERE", rendered)
        self.assertNotIn("ISOLATE", rendered)

    def test_the_policy_command_reports_and_flags_a_typo(self) -> None:
        self.assertEqual(0, sdd_session.main(["--root", str(self.root), "policy"]))
        self.project("# Project\n\nisolation: siempre\n")
        self.assertEqual(2, sdd_session.main(["--root", str(self.root), "policy"]))

    def test_check_reports_where_a_worktree_would_have_to_be_created(self) -> None:
        """A session already inside a linked worktree must not nest another."""
        linked = self.root / ".claude" / "worktrees" / "sdd+alpha"
        self.git("worktree", "add", "-q", "-b", "sdd/alpha", str(linked))
        report = sdd_session.check(linked, "alpha")
        self.assertTrue(report["in_linked_worktree"])
        self.assertEqual(str(self.root), report["main_worktree"])


class BaseFactsTests(SessionTestCase):
    """Under `always` the base-ref check runs for every feature, not rarely."""

    def test_without_a_remote_the_fresh_default_has_nothing_to_resolve(self) -> None:
        base = sdd_session.base_facts(self.root)
        self.assertEqual("main", base["default_branch"])
        self.assertFalse(base["has_remote"])
        self.assertFalse(base["published"])
        self.assertEqual("main", base["base_ref"])
        self.assertEqual(0, base["unpushed"])

    def publish(self) -> Path:
        remote = Path(self.directory.name) / "origin.git"
        subprocess.run(
            ["git", "init", "--bare", "-q", str(remote)], check=True, capture_output=True
        )
        self.git("remote", "add", "origin", str(remote))
        self.git("push", "-q", "-u", "origin", "main")
        return remote

    def test_a_published_base_is_what_a_new_worktree_branches_from(self) -> None:
        self.publish()
        base = sdd_session.base_facts(self.root)
        self.assertTrue(base["has_remote"])
        self.assertTrue(base["published"])
        self.assertEqual("origin/main", base["base_ref"])
        self.assertEqual(0, base["unpushed"])

    def test_a_local_base_ahead_of_origin_is_counted(self) -> None:
        """`fresh` would branch from origin/main and leave these behind — and a
        BASE recorded from a commit the worktree never saw is false evidence."""
        self.publish()
        (self.root / "local.txt").write_text("sin pushear\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", "solo local")
        self.assertEqual(1, sdd_session.base_facts(self.root)["unpushed"])

    def test_a_detached_head_never_reports_itself_as_the_base(self) -> None:
        head = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("checkout", "-q", "--detach", head)
        self.assertEqual("", sdd_session.current_branch(self.root))
        self.assertEqual("main", sdd_session.default_branch(self.root))

    def test_a_feature_branch_is_never_mistaken_for_the_base(self) -> None:
        self.git("checkout", "-q", "-b", "sdd/alpha")
        self.assertEqual("main", sdd_session.default_branch(self.root))

    def test_the_rendered_line_names_both_failure_modes(self) -> None:
        rendered = sdd_session.render_base(sdd_session.base_facts(self.root))
        self.assertIn("not published", rendered)
        self.publish()
        (self.root / "local.txt").write_text("sin pushear\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", "solo local")
        rendered = sdd_session.render_base(sdd_session.base_facts(self.root))
        self.assertIn("1 local commit(s) NOT in origin", rendered)


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

    def add_worktree(self, name: str, branch: str) -> Path:
        path = self.root / name
        self.git("worktree", "add", "-q", "-b", branch, str(path))
        return path

    def test_an_unregistered_worktree_is_found_through_git(self) -> None:
        """The registry only knows what was claimed; git knows what exists.

        A worktree made by hand, on another machine, or one whose registry was
        rebuilt after corruption was invisible to `resolve` — and answering ""
        does not degrade to "work here", it degrades to the base branch in the
        main worktree, which is a different change.
        """
        path = self.add_worktree("wt", "sdd/alpha")
        self.assertEqual({}, self.registry()["worktrees"])
        self.assertEqual(str(path), sdd_session.resolve(self.root, "alpha"))

    def test_the_registry_still_answers_first(self) -> None:
        """It records where a session actually bound the feature, which need not
        be the branch's worktree."""
        self.add_worktree("wt", "sdd/alpha")
        sdd_session.claim(self.root, "alpha")
        self.assertEqual(str(self.root), sdd_session.resolve(self.root, "alpha"))

    def test_a_vanished_binding_falls_through_to_git(self) -> None:
        path = self.add_worktree("wt", "sdd/alpha")
        self.write_registry(
            {
                "schema": 1,
                "sessions": {},
                "worktrees": {"alpha": {"path": str(self.root / "gone")}},
            }
        )
        self.assertEqual(str(path), sdd_session.resolve(self.root, "alpha"))

    def test_the_archive_worktree_is_not_where_the_phases_run(self) -> None:
        """`sdd/<feature>-archive` belongs to the feature but is a different job,
        so the branch match is exact rather than by feature name."""
        self.add_worktree("wt-archive", "sdd/alpha-archive")
        self.assertEqual("", sdd_session.resolve(self.root, "alpha"))

    def test_an_unrelated_branch_is_never_mistaken_for_the_feature(self) -> None:
        self.add_worktree("wt", "sdd/alphabet")
        self.assertEqual("", sdd_session.resolve(self.root, "alpha"))
        self.add_worktree("other", "feature/alpha")
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


LIVE_PID = 1  # launchd/init: always running, and kill(0) raises PermissionError


class RetirementTests(SessionTestCase):
    """Decommissioning a worktree once its work shipped.

    Three failures this closes, all lived in a real repo: a hand-made worktree
    invisible to the cleanup, a retirement that broke a live session, and a
    removal that unregistered the worktree but left 88 MB on disk.
    """

    def setUp(self) -> None:
        super().setUp()
        self.archive("alpha")
        self.linked = self.root / ".claude" / "worktrees" / "sdd+alpha"
        self.git("worktree", "add", "-q", str(self.linked), "-b", "sdd/alpha")
        # Docker is absent unless a test says otherwise: whether the machine
        # running the suite has a daemon must not change what is asserted.
        patch = mock.patch.object(sdd_session, "try_docker", return_value=None)
        patch.start()
        self.addCleanup(patch.stop)

    def archive(self, feature: str, base: str = "main") -> Path:
        path = self.root / "sdd" / "changes" / "archive" / f"2026-01-01-{feature}"
        path.mkdir(parents=True, exist_ok=True)
        (path / "STATE.md").write_text(
            f"---\nschema: 1\nstate: ARCHIVED\nbase_branch: {base}\n---\n",
            encoding="utf-8",
        )
        return path

    def status_for(self, path: Path) -> sdd_session.WorktreeStatus:
        found = [
            s
            for s in sdd_session.worktree_status(self.root)
            if Path(s.path) == path.resolve()
        ]
        self.assertEqual(1, len(found), f"no status for {path}")
        return found[0]

    def test_a_hand_made_worktree_is_seen_without_any_claim(self) -> None:
        """It never registered, so the registry-only cleanup never offered it."""
        status = self.status_for(self.linked)
        self.assertFalse(status.registered)
        self.assertEqual("alpha", status.feature)
        self.assertTrue(status.retirable, status.blockers)

    def test_the_feature_is_recovered_from_an_archive_branch_name(self) -> None:
        """Archive work happens on sdd/<feature>-archive; it still belongs to
        <feature>, and a naive lookup finds nothing."""
        other = self.root / ".claude" / "worktrees" / "sdd+beta-archive"
        self.git("worktree", "add", "-q", str(other), "-b", "sdd/beta-archive")
        self.assertEqual("beta", self.status_for(other).feature)

    def test_the_main_worktree_is_never_retirable(self) -> None:
        status = self.status_for(self.root)
        self.assertTrue(status.is_main)
        self.assertFalse(status.retirable)

    def test_a_live_session_blocks_retirement(self) -> None:
        self.write_registry(
            {
                "schema": 1,
                "sessions": {
                    "sess": {"pid": LIVE_PID, "feature": "alpha", "worktree": str(self.linked)}
                },
                "worktrees": {"alpha": {"path": str(self.linked)}},
            }
        )
        status = self.status_for(self.linked)
        self.assertEqual("sess", status.occupied_by)
        with self.assertRaises(SessionError) as caught:
            sdd_session.retire(self.root, "alpha")
        self.assertIn("live session", str(caught.exception))
        self.assertTrue(self.linked.is_dir(), "the worktree must survive a refusal")

    def test_the_calling_session_does_not_block_itself(self) -> None:
        """/sdd:archive runs from the main worktree while still holding the claim;
        counting itself as an occupant made it refuse to retire its own work."""
        sdd_session.claim(self.root, "alpha", worktree=self.linked)
        status = self.status_for(self.linked)
        self.assertEqual("", status.occupied_by)
        self.assertTrue(status.retirable, status.blockers)

    def test_you_cannot_retire_the_worktree_you_are_standing_in(self) -> None:
        blockers = sdd_session.worktree_status(self.linked)
        mine = [s for s in blockers if Path(s.path) == self.linked.resolve()][0]
        self.assertTrue(any("inside it" in b for b in mine.blockers), mine.blockers)

    def test_a_dead_session_does_not_block(self) -> None:
        self.write_registry(
            {
                "schema": 1,
                "sessions": {
                    "gone": {"pid": DEAD_PID, "feature": "alpha", "worktree": str(self.linked)}
                },
                "worktrees": {"alpha": {"path": str(self.linked)}},
            }
        )
        self.assertTrue(self.status_for(self.linked).retirable)

    def test_an_unarchived_change_blocks(self) -> None:
        other = self.root / ".claude" / "worktrees" / "sdd+gamma"
        self.git("worktree", "add", "-q", str(other), "-b", "sdd/gamma")
        blockers = self.status_for(other).blockers
        self.assertTrue(any("not archived" in b for b in blockers), blockers)

    def test_uncommitted_work_blocks(self) -> None:
        (self.linked / "sdd" / "roadmap.md").write_text("# cambiado\n", encoding="utf-8")
        blockers = self.status_for(self.linked).blockers
        self.assertTrue(any("uncommitted" in b for b in blockers), blockers)

    def test_a_branch_not_contained_in_the_base_blocks(self) -> None:
        (self.linked / "extra.txt").write_text("nuevo\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.linked, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "trabajo sin mergear"],
            cwd=self.linked, check=True, capture_output=True,
        )
        blockers = self.status_for(self.linked).blockers
        self.assertTrue(any("not contained" in b for b in blockers), blockers)

    def test_no_remote_falls_back_to_the_local_base(self) -> None:
        """A repo with no remote is a workflow the merge gate already supports."""
        status = self.status_for(self.linked)
        self.assertTrue(status.merged)
        self.assertTrue(status.retirable, status.blockers)

    def test_retire_removes_worktree_branch_and_binding(self) -> None:
        sdd_session.claim(self.root, "alpha", worktree=self.linked)
        outcome = sdd_session.retire(self.root, "alpha")
        self.assertFalse(self.linked.exists())
        self.assertNotIn("sdd/alpha", self.git("branch").stdout)
        self.assertEqual("", sdd_session.resolve(self.root, "alpha"))
        self.assertTrue(outcome.unregistered)
        self.assertTrue(outcome.directory_gone)
        self.assertTrue(outcome.branch_deleted)
        self.assertTrue(outcome.binding_released)
        self.assertIn("disk:    clean", outcome.render())

    def test_retire_accepts_a_path_when_no_feature_is_known(self) -> None:
        other = self.root / ".claude" / "worktrees" / "loose"
        self.git("worktree", "add", "-q", str(other), "--detach")
        outcome = sdd_session.retire(self.root, path=other, force=True)
        self.assertFalse(other.exists())
        self.assertTrue(outcome.directory_gone)

    def test_retiring_something_unknown_is_an_actionable_error(self) -> None:
        with self.assertRaises(SessionError) as caught:
            sdd_session.retire(self.root, "no-such-feature")
        self.assertIn("No worktree found", str(caught.exception))

    def test_force_overrides_the_blockers(self) -> None:
        (self.linked / "extra.txt").write_text("sin commitear\n", encoding="utf-8")
        self.assertTrue(self.status_for(self.linked).blockers)
        sdd_session.retire(self.root, "alpha", force=True)
        self.assertFalse(self.linked.exists())

    def test_the_cli_lists_and_retires(self) -> None:
        self.assertEqual(0, sdd_session.main(["--root", str(self.root), "worktrees"]))
        self.assertEqual(
            0, sdd_session.main(["--root", str(self.root), "retire", "alpha"])
        )
        self.assertEqual(
            2, sdd_session.main(["--root", str(self.root), "retire"])
        )


class DockerStub:
    """A daemon that reports exactly the residue a test asks for.

    It answers `docker` itself and delegates everything else — git, chmod — to
    the real subprocess, so ordering assertions are made against real git
    behaviour rather than a second simulation of it.
    """

    def __init__(
        self,
        workdir: Path | None = None,
        *,
        project: str = "sddalpha",
        containers: tuple[str, ...] = (),
        volumes: tuple[str, ...] = (),
        teardown_returncode: int = 0,
        teardown_clears: bool = True,
    ) -> None:
        self.workdir = str(workdir) if workdir else ""
        self.project = project
        self.containers = containers
        self.volumes = volumes
        self.teardown_returncode = teardown_returncode
        self.teardown_clears = teardown_clears
        self.torn_down = False
        self.calls: list[str] = []
        self.teardown_cwd: str = ""

    def _done(self, stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], returncode, stdout, "")

    def __call__(self, args, **kwargs):  # type: ignore[no-untyped-def]
        if isinstance(args, str):
            self.calls.append(f"teardown:{args}")
            self.teardown_cwd = str(kwargs.get("cwd", ""))
            if self.teardown_clears and not self.teardown_returncode:
                self.torn_down = True
            return self._done(returncode=self.teardown_returncode)
        if args and args[0] == "docker":
            return self._docker(list(args[1:]))
        if args and args[0] == "git":
            self.calls.append("git:" + " ".join(args[1:3]))
        return subprocess.run(args, **kwargs)

    def _docker(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append("docker:" + " ".join(args[:2]))
        gone = self.torn_down
        if args[:1] == ["version"]:
            return self._done("27.0.0")
        if args[:2] == ["compose", "ls"]:
            if gone or not self.workdir:
                return self._done("[]")
            return self._done(
                json.dumps(
                    [
                        {
                            "Name": self.project,
                            "Status": "running(1)",
                            "ConfigFiles": f"{self.workdir}/docker-compose.yml",
                        }
                    ]
                )
            )
        if args[:1] == ["ps"]:
            if gone or f"label={sdd_session.COMPOSE_WORKDIR_LABEL}={self.workdir}" not in args:
                return self._done("")
            return self._done(
                "\n".join(f"{name}\trunning\t{self.project}" for name in self.containers)
            )
        if args[:2] == ["volume", "ls"]:
            return self._done("" if gone else "\n".join(self.volumes))
        if args[:1] == ["images"]:
            return self._done("" if gone else f"{self.project}-backend:latest")
        if args[:2] == ["system", "df"]:
            return self._done(
                json.dumps(
                    {
                        "Volumes": [{"Name": name, "Size": "1.5GB"} for name in self.volumes],
                        "Images": [
                            {
                                "Repository": f"{self.project}-backend",
                                "Tag": "latest",
                                "Size": "935MB",
                            }
                        ],
                    }
                )
            )
        return self._done()


class DecommissionTests(SessionTestCase):
    """What retirement owes the machine, not just the repository.

    Every one of these is a measured failure: `retire` only ever spoke git, so
    the compose stack a worktree owned survived it — and its named volumes were
    exactly what made the directory undeletable. Git unregistered the worktree
    first, so the leftover was then invisible to `worktrees` (git no longer knew
    it) and to `orphans` (the binding had just been released). Three changes of
    that left ~30 GB and three orphan directories nobody reported.
    """

    def setUp(self) -> None:
        super().setUp()
        archive = self.root / "sdd" / "changes" / "archive" / "2026-01-01-alpha"
        archive.mkdir(parents=True)
        (archive / "STATE.md").write_text(
            "---\nschema: 1\nstate: ARCHIVED\nbase_branch: main\n---\n", encoding="utf-8"
        )
        self.linked = self.root / ".claude" / "worktrees" / "sdd+alpha"
        self.git("worktree", "add", "-q", str(self.linked), "-b", "sdd/alpha")

    def without_docker(self) -> None:
        """For the tests that are about git and disk, not about containers."""
        patch = mock.patch.object(sdd_session, "try_docker", return_value=None)
        patch.start()
        self.addCleanup(patch.stop)

    def survive_removal(self) -> None:
        """git unregisters the worktree and the directory stays behind.

        The measured failure, in the only order that produces it: `git worktree
        remove` reports success, deletion does not happen (in reality the
        deny-delete ACL on the volume mountpoints), and from that moment git no
        longer knows the path.
        """
        original = sdd_session.try_git

        def unregister_but_keep(args, root, runner=subprocess.run):  # type: ignore[no-untyped-def]
            result = original(args, root, runner)
            if list(args[:2]) == ["worktree", "remove"]:
                (self.linked / "node_modules").mkdir(parents=True, exist_ok=True)
            return result

        for patch in (
            mock.patch.object(sdd_session, "try_git", unregister_but_keep),
            mock.patch.object(
                sdd_session, "remove_directory", return_value=(False, "deny delete ACL")
            ),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def declare_teardown(self, command: str = "make down") -> None:
        (self.root / "sdd" / "project.md").write_text(
            "# Project\n\n## Worktree bootstrap\n\nisolation: always\n\n"
            f"teardown: {command}\n",
            encoding="utf-8",
        )

    def test_residue_is_attributed_by_what_docker_recorded(self) -> None:
        stub = DockerStub(self.linked, containers=("alpha-db-1",), volumes=("sddalpha_data",))
        found = sdd_session.residue_of(self.linked, stub)
        self.assertTrue(found.available)
        self.assertEqual(("sddalpha",), found.projects)
        self.assertEqual(("alpha-db-1",), found.containers)
        self.assertEqual(("sddalpha_data",), found.volumes)
        self.assertEqual(1, found.running)
        self.assertEqual(int(1.5 * 10**9) + 935 * 10**6, found.size)

    def test_another_worktrees_stack_is_never_attributed_to_this_one(self) -> None:
        elsewhere = self.root / ".claude" / "worktrees" / "sdd+beta"
        stub = DockerStub(elsewhere, containers=("beta-db-1",), volumes=("sddbeta_data",))
        self.assertTrue(sdd_session.residue_of(self.linked, stub).empty)

    def test_docker_absent_is_not_an_error(self) -> None:
        found = sdd_session.residue_of(self.linked, lambda *a, **k: (_ for _ in ()).throw(OSError()))
        self.assertFalse(found.available)
        self.assertIn("docker did not answer", found.describe())

    def test_a_stack_nobody_declared_how_to_stop_refuses_and_says_what_to_write(self) -> None:
        stub = DockerStub(self.linked, containers=("alpha-db-1",), volumes=("sddalpha_data",))
        with self.assertRaises(SessionError) as caught:
            sdd_session.retire(self.root, "alpha", runner=stub)
        message = str(caught.exception)
        self.assertIn("teardown: docker compose down --volumes", message)
        self.assertIn("1 volume(s)", message)
        # Nothing was touched: the residue is still attributable, which is the
        # whole reason for refusing instead of continuing.
        self.assertTrue(self.linked.exists())
        self.assertNotIn("git:worktree remove", stub.calls)

    def test_worktrees_reports_the_same_refusal_retire_would_raise(self) -> None:
        """`RETIRABLE` has to mean "retire will do it". Finding the missing
        teardown only inside retire would make the listing a lie."""
        stub = DockerStub(self.linked, containers=("alpha-db-1",), volumes=("sddalpha_data",))
        status = [
            s
            for s in sdd_session.worktree_status(self.root, stub)
            if Path(s.path) == self.linked.resolve()
        ][0]
        self.assertFalse(status.retirable)
        self.assertTrue(
            any("declares no teardown" in b for b in status.blockers), status.blockers
        )

    def test_a_declared_teardown_costs_no_docker_call_in_the_listing(self) -> None:
        """`worktrees` runs on every /sdd:doctor and /sdd:status."""
        self.declare_teardown()
        stub = DockerStub(self.linked, containers=("alpha-db-1",))
        sdd_session.worktree_status(self.root, stub)
        self.assertEqual([], [call for call in stub.calls if call.startswith("docker:")])

    def test_the_teardown_runs_inside_the_worktree_and_before_git(self) -> None:
        self.declare_teardown("docker compose down --volumes")
        stub = DockerStub(self.linked, containers=("alpha-db-1",), volumes=("sddalpha_data",))
        outcome = sdd_session.retire(self.root, "alpha", runner=stub)
        self.assertEqual(str(self.linked), stub.teardown_cwd)
        teardown_at = stub.calls.index("teardown:docker compose down --volumes")
        removal_at = stub.calls.index("git:worktree remove")
        self.assertLess(teardown_at, removal_at, stub.calls)
        self.assertTrue(outcome.teardown_ok)
        self.assertTrue(outcome.residue_after.empty)
        self.assertTrue(outcome.directory_gone)

    def test_a_failing_teardown_stops_before_git_changes_anything(self) -> None:
        self.declare_teardown()
        stub = DockerStub(self.linked, containers=("alpha-db-1",), teardown_returncode=1)
        with self.assertRaises(SessionError) as caught:
            sdd_session.retire(self.root, "alpha", runner=stub)
        self.assertIn("teardown", str(caught.exception))
        self.assertTrue(self.linked.exists())
        self.assertNotIn("git:worktree remove", stub.calls)

    def test_residue_surviving_a_successful_teardown_is_reported(self) -> None:
        """`down` without `--volumes` is the common half-teardown."""
        self.declare_teardown("docker compose down")
        stub = DockerStub(
            self.linked, containers=("alpha-db-1",), volumes=("sddalpha_data",),
            teardown_clears=False,
        )
        outcome = sdd_session.retire(self.root, "alpha", runner=stub)
        self.assertFalse(outcome.residue_after.empty)
        self.assertTrue(any("--volumes" in note for note in outcome.notes), outcome.notes)

    def test_skip_teardown_keeps_the_resources_on_purpose(self) -> None:
        stub = DockerStub(self.linked, containers=("alpha-db-1",), volumes=("sddalpha_data",))
        outcome = sdd_session.retire(self.root, "alpha", skip_teardown=True, runner=stub)
        self.assertEqual("", outcome.teardown)
        self.assertTrue(outcome.directory_gone)
        self.assertNotIn("teardown:", "".join(stub.calls))

    def test_a_one_off_teardown_command_overrides_an_undeclared_project(self) -> None:
        stub = DockerStub(self.linked, containers=("alpha-db-1",))
        outcome = sdd_session.retire(
            self.root, "alpha", teardown="make nuke", runner=stub
        )
        self.assertEqual("make nuke", outcome.teardown)
        self.assertTrue(outcome.teardown_ok)

    def test_the_teardown_is_read_from_project_md_in_its_three_shapes(self) -> None:
        for line in (
            "teardown: make down",
            "- teardown: make down",
            "**teardown**: `make down`",
        ):
            (self.root / "sdd" / "project.md").write_text(
                f"# Project\n\n{line}\n", encoding="utf-8"
            )
            self.assertEqual("make down", sdd_session.read_teardown(self.root), line)

    def test_a_commented_out_teardown_is_not_a_declaration(self) -> None:
        (self.root / "sdd" / "project.md").write_text(
            "# Project\n\n<!-- teardown: make down -->\n", encoding="utf-8"
        )
        self.assertEqual("", sdd_session.read_teardown(self.root))

    def test_a_directory_that_refuses_to_go_is_recorded_and_keeps_reporting(self) -> None:
        """The leak: git forgets the path, the binding is released, and without
        this record nothing would ever mention the directory again."""
        self.without_docker()
        self.survive_removal()
        sdd_session.claim(self.root, "alpha", worktree=self.linked)
        outcome = sdd_session.retire(self.root, "alpha")
        self.assertFalse(outcome.directory_gone)
        self.assertTrue(self.linked.exists())
        self.assertIn("LEFTOVER", outcome.render())
        reported = sdd_session.all_orphans(self.root)
        self.assertIn(
            ("leftover", str(self.linked)),
            [(entry["reason"], entry["path"]) for entry in reported],
        )

    def test_a_recorded_leftover_is_forgotten_once_it_is_gone(self) -> None:
        self.without_docker()
        self.survive_removal()
        sdd_session.retire(self.root, "alpha")
        self.assertTrue(sdd_session.all_orphans(self.root))
        shutil.rmtree(self.linked)
        self.assertEqual([], sdd_session.all_orphans(self.root))

    @unittest.skipUnless(sys.platform == "darwin", "the ACL is a macOS/Docker Desktop fact")
    def test_a_deny_delete_acl_is_stripped_instead_of_being_printed(self) -> None:
        """The real blocker, reproduced: an empty directory that is yours, with
        `rwx`, that neither chmod -R nor sudo can remove — Docker Desktop sets it
        on volume mountpoints and it outlives the volume."""
        tree = self.root / "acl-fixture"
        mountpoint = tree / "node_modules"
        mountpoint.mkdir(parents=True)
        subprocess.run(
            ["chmod", "+a", f"user:{os.getlogin()} deny delete", str(mountpoint)],
            check=True, capture_output=True,
        )
        with self.assertRaises(OSError):
            shutil.rmtree(tree)
        gone, note = sdd_session.remove_directory(tree)
        self.assertTrue(gone, note)
        self.assertIn("ACL", note)

    def test_a_stray_directory_is_reported_without_any_record(self) -> None:
        """A retirement that never recorded anything, a `git worktree remove` by
        hand, a directory from a clone that no longer exists: all the same from
        here, and all invisible to a registry-only check."""
        self.without_docker()
        stray = self.root / ".claude" / "worktrees" / "sdd+ghost"
        (stray / "node_modules").mkdir(parents=True)
        reported = sdd_session.all_orphans(self.root)
        self.assertIn(
            ("stray", str(stray)),
            [(entry["reason"], entry["path"]) for entry in reported],
        )

    def test_a_live_worktree_is_not_a_stray(self) -> None:
        self.assertEqual([], sdd_session.stray_directories(self.root))

    def test_the_cli_exits_nonzero_when_a_leftover_survives(self) -> None:
        self.without_docker()
        self.survive_removal()
        self.assertEqual(
            1, sdd_session.main(["--root", str(self.root), "retire", "alpha"])
        )

    def test_the_cli_reports_residue_read_only(self) -> None:
        self.without_docker()
        sdd_session.claim(self.root, "alpha", worktree=self.linked)
        self.assertEqual(
            0, sdd_session.main(["--root", str(self.root), "residue", "alpha"])
        )
        self.assertTrue(self.linked.exists())


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
