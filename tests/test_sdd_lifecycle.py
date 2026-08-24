from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sdd_lifecycle  # noqa: E402
from sdd_lifecycle import (  # noqa: E402
    classify_lifecycle_commit,
    commit_sync,
    duplicate_bookkeeping_keys,
    LifecycleError,
    initial_state,
    finalize_archive,
    mark_local_verified,
    mark_ready,
    publish_archive,
    read_state,
    record_pr,
    require_merge,
    stage_archive_move,
    start_change,
    sync_base,
    update_roadmap,
    validate_feature_slug,
    validate_ship_suffix,
    write_state,
)


FEATURE = "example"
PR_URL = "https://github.com/example/project/pull/17"


class LifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.change = self.root / "sdd" / "changes" / FEATURE
        self.change.mkdir(parents=True)
        (self.change / "proposal.md").write_text(
            "# Proposal\n\n## Requirements\n\n### R1 — Example\n",
            encoding="utf-8",
        )
        (self.change / "tasks.md").write_text(
            "# Tasks\n\n- [x] 1.1 Complete behavior [R1]\n",
            encoding="utf-8",
        )
        (self.root / "sdd" / "specs").mkdir()
        (self.root / "sdd" / "specs" / "example.md").write_text(
            "# Example\n\nOld behavior.\n", encoding="utf-8"
        )
        (self.root / "sdd" / "roadmap.md").write_text(
            "# Roadmap\n\n"
            "- [ ] example — lifecycle fixture → changes/example/\n",
            encoding="utf-8",
        )
        write_state(self.change, initial_state())
        self.git("init", "-b", "sdd/example")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "SDD Test")
        self.git("remote", "add", "origin", "https://github.com/example/project.git")
        self.git("add", ".")
        self.git("commit", "-m", "fixture")
        self.implementation_sha = self.git("rev-parse", "HEAD").stdout.strip()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        )

    def pr_payload(
        self,
        state: str,
        *,
        merged_at: str | None = None,
        merge_sha: str | None = None,
        url: str = PR_URL,
        head: str = "sdd/example",
        base: str = "main",
        commits: list[str] | None = None,
    ) -> dict[str, object]:
        return {
            "number": 17,
            "url": url,
            "state": state,
            "mergedAt": merged_at,
            "mergeCommit": {"oid": merge_sha} if merge_sha else None,
            "baseRefName": base,
            "headRefName": head,
            "headRefOid": self.implementation_sha,
            "commits": [
                {"oid": oid} for oid in (commits or [self.implementation_sha])
            ],
        }

    @staticmethod
    def gh_runner(payload: dict[str, object]):
        def run(
            args: list[str],
            **kwargs: object,
        ) -> subprocess.CompletedProcess[str]:
            if args[0] == "git":
                # Only GitHub is faked. The fixture is a real repository, so git
                # must actually run — staging the archive move depends on it.
                return subprocess.run(args, **kwargs)  # type: ignore[arg-type]
            if args[:3] != ["gh", "pr", "view"]:
                raise AssertionError(f"Unexpected external command: {args}")
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps(payload),
                stderr="",
            )

        return run

    def ready(self) -> None:
        mark_local_verified(self.root, FEATURE)
        mark_ready(self.root, FEATURE, "main")

    def record_open(self) -> None:
        self.ready()
        record_pr(
            self.root,
            FEATURE,
            PR_URL,
            runner=self.gh_runner(self.pr_payload("OPEN")),
        )

    def test_complete_permitted_transition_sequence(self) -> None:
        self.assertEqual(
            "Lifecycle already initialized at state ACTIVE.",
            start_change(self.root, FEATURE),
        )
        self.assertEqual("ACTIVE", read_state(self.change)["state"])
        self.assertEqual("LOCAL_VERIFIED recorded.", mark_local_verified(self.root, FEATURE))
        self.assertEqual("LOCAL_VERIFIED", read_state(self.change)["state"])
        self.assertEqual(
            "READY_FOR_PR recorded.", mark_ready(self.root, FEATURE, "main")
        )
        state = read_state(self.change)
        self.assertEqual("READY_FOR_PR", state["state"])
        self.assertEqual("APPROVED", state["local_review"])
        self.assertEqual(self.implementation_sha, state["implementation_sha"])
        self.assertEqual("", state["pr_url"])
        record_pr(
            self.root,
            FEATURE,
            PR_URL,
            runner=self.gh_runner(self.pr_payload("OPEN")),
        )
        self.assertEqual("PR_OPEN", read_state(self.change)["state"])
        merge_payload = self.pr_payload(
            "MERGED",
            merged_at="2026-07-28T12:00:00Z",
            merge_sha="a" * 40,
        )
        require_merge(self.root, FEATURE, runner=self.gh_runner(merge_payload))
        self.assertEqual("MERGED", read_state(self.change)["state"])
        finalize_archive(
            self.root,
            FEATURE,
            specs_confirmed=True,
            runner=self.gh_runner(merge_payload),
            today=date(2026, 7, 28),
        )
        archive = self.root / "sdd/changes/archive/2026-07-28-example"
        self.assertEqual("ARCHIVED", read_state(archive)["state"])

    def test_start_is_idempotent(self) -> None:
        self.assertEqual(
            "Lifecycle already initialized at state ACTIVE.",
            start_change(self.root, FEATURE),
        )
        first = (self.change / "STATE.md").read_bytes()
        self.assertEqual(
            "Lifecycle already initialized at state ACTIVE.",
            start_change(self.root, FEATURE),
        )
        self.assertEqual(first, (self.change / "STATE.md").read_bytes())

    def test_review_contract_is_idempotent(self) -> None:
        self.ready()
        first = (self.change / "STATE.md").read_bytes()
        self.assertIn("already recorded", mark_local_verified(self.root, FEATURE))
        self.assertEqual(
            "READY_FOR_PR already recorded.",
            mark_ready(self.root, FEATURE, "main"),
        )
        self.assertEqual(first, (self.change / "STATE.md").read_bytes())

    def test_mark_ready_commits_state_only_with_stable_anchor(self) -> None:
        mark_local_verified(self.root, FEATURE)
        anchor = self.implementation_sha
        self.assertEqual("READY_FOR_PR recorded.", mark_ready(self.root, FEATURE, "main"))
        lifecycle = self.git("rev-parse", "HEAD").stdout.strip()
        self.assertEqual(anchor, read_state(self.change)["implementation_sha"])
        self.assertEqual(anchor, self.git("rev-parse", "HEAD^^").stdout.strip())
        self.assertEqual(
            ["sdd/changes/example/STATE.md"],
            self.git("show", "--format=", "--name-only", lifecycle).stdout.splitlines(),
        )
        self.assertEqual(
            "chore(sdd): lifecycle example LOCAL_VERIFIED->READY_FOR_PR",
            self.git("show", "-s", "--format=%s", lifecycle).stdout.strip(),
        )
        self.assertIn(
            "SDD-Lifecycle-Feature: example",
            self.git("show", "-s", "--format=%B", lifecycle).stdout,
        )
        self.assertNotIn(lifecycle, (self.change / "STATE.md").read_text())
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        self.assertEqual(
            [self.git("rev-parse", "HEAD^").stdout.strip(), lifecycle],
            validate_ship_suffix(self.root, FEATURE),
        )

    def test_mark_ready_is_idempotent_without_duplicate_lifecycle_commit(self) -> None:
        self.ready()
        first = self.git("rev-parse", "HEAD").stdout.strip()
        self.assertEqual("READY_FOR_PR already recorded.", mark_ready(self.root, FEATURE, "main"))
        self.assertEqual(first, self.git("rev-parse", "HEAD").stdout.strip())

    def test_mark_ready_rejects_dirty_paths_and_preserves_user_changes(self) -> None:
        mark_local_verified(self.root, FEATURE)
        unrelated = self.root / "unrelated.txt"
        unrelated.write_text("user edit\n", encoding="utf-8")
        before = unrelated.read_bytes()
        with self.assertRaisesRegex(LifecycleError, "outside the lifecycle STATE.md"):
            mark_ready(self.root, FEATURE, "main")
        self.assertEqual(before, unrelated.read_bytes())
        self.git("add", "unrelated.txt")
        with self.assertRaisesRegex(LifecycleError, "outside the lifecycle STATE.md"):
            mark_ready(self.root, FEATURE, "main")
        self.assertIn("unrelated.txt", self.git("diff", "--cached", "--name-only").stdout)

    def test_mark_ready_rejects_preexisting_state_edit_without_overwrite(self) -> None:
        mark_local_verified(self.root, FEATURE)
        state_file = self.change / "STATE.md"
        original = state_file.read_bytes()
        state_file.write_bytes(original + b"manual edit\n")
        before = state_file.read_bytes()
        with self.assertRaisesRegex(LifecycleError, "pre-existing edits"):
            mark_ready(self.root, FEATURE, "main")
        self.assertEqual(before, state_file.read_bytes())

    def test_mark_ready_commit_failure_rolls_back_helper_staging(self) -> None:
        mark_local_verified(self.root, FEATURE)
        state_file = self.change / "STATE.md"
        before = state_file.read_bytes()

        def failing_runner(args: list[str], **kwargs: object):
            if args[:2] == ["git", "commit"]:
                return subprocess.CompletedProcess(args, 1, "", "synthetic commit failure")
            return subprocess.run(args, **kwargs)  # type: ignore[arg-type]

        with self.assertRaisesRegex(LifecycleError, "synthetic commit failure"):
            mark_ready(self.root, FEATURE, "main", runner=failing_runner)
        self.assertEqual(before, state_file.read_bytes())
        self.assertEqual("", self.git("diff", "--cached", "--name-only").stdout)

    def test_record_pr_commits_state_without_invoking_push(self) -> None:
        self.ready()
        anchor = read_state(self.change)["implementation_sha"]
        commands: list[list[str]] = []
        base_runner = self.gh_runner(self.pr_payload("OPEN"))

        def recording_runner(args: list[str], **kwargs: object):
            commands.append(args)
            return base_runner(args, **kwargs)

        self.assertEqual(
            "PR_OPEN recorded.",
            record_pr(self.root, FEATURE, PR_URL, runner=recording_runner),
        )
        lifecycle = self.git("rev-parse", "HEAD").stdout.strip()
        self.assertEqual(anchor, read_state(self.change)["implementation_sha"])
        self.assertEqual(
            "chore(sdd): lifecycle example READY_FOR_PR->PR_OPEN",
            self.git("show", "-s", "--format=%s", lifecycle).stdout.strip(),
        )
        self.assertFalse(any(args[:2] == ["git", "push"] for args in commands))
        self.assertEqual(
            [
                self.git("rev-parse", "HEAD^^").stdout.strip(),
                self.git("rev-parse", "HEAD^").stdout.strip(),
                lifecycle,
            ],
            validate_ship_suffix(self.root, FEATURE),
        )

    def test_ship_pushes_only_after_all_lifecycle_gates_pass(self) -> None:
        self.ready()
        remote_dir = tempfile.TemporaryDirectory()
        self.addCleanup(remote_dir.cleanup)
        remote = Path(remote_dir.name)
        self.git("init", "--bare", str(remote))
        self.git("remote", "set-url", "origin", str(remote))
        # The branch claim/bootstrap is a precondition for PR creation and is
        # not part of ship's final push count.
        self.git("push", "-u", str(remote), "HEAD:sdd/example")

        commands: list[list[str]] = []
        base_runner = self.gh_runner(self.pr_payload("OPEN"))

        def recording_runner(args: list[str], **kwargs: object):
            commands.append(args)
            return base_runner(args, **kwargs)

        record_pr(self.root, FEATURE, PR_URL, runner=recording_runner)
        pr_open_commit = self.git("rev-parse", "HEAD").stdout.strip()
        self.assertFalse(any(args[:2] == ["git", "push"] for args in commands))

        push_calls: list[list[str]] = []

        def push_once(*args: str) -> subprocess.CompletedProcess[str]:
            push_calls.append(list(args))
            return self.git(*args)

        push_once("push", "origin", "sdd/example")
        self.assertEqual(1, len(push_calls))
        self.assertEqual(
            "0", self.git("rev-list", "--count", f"{pr_open_commit}..HEAD").stdout.strip()
        )
        remote_head = subprocess.run(
            ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/sdd/example"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(pr_open_commit, remote_head)

    def test_metrics_path_is_not_lifecycle_allowlisted(self) -> None:
        self.ready()
        metrics = self.root / "sdd" / "metrics.md"
        metrics.write_text("not lifecycle metadata\n", encoding="utf-8")
        self.git("add", "sdd/metrics.md")
        self.git(
            "commit",
            "-m",
            "chore(sdd): lifecycle example READY_FOR_PR->PR_OPEN",
            "-m",
            "SDD-Lifecycle-Feature: example",
        )
        with self.assertRaisesRegex(LifecycleError, "outside the lifecycle allowlist"):
            validate_ship_suffix(self.root, FEATURE)

    def test_lifecycle_parent_without_state_is_rejected(self) -> None:
        self.ready()
        state_file = self.change / "STATE.md"
        state = read_state(self.change)
        self.git("rm", "sdd/changes/example/STATE.md")
        self.git("commit", "-m", "remove lifecycle state")
        state["state"] = "PR_OPEN"
        state["pr_state"] = "OPEN"
        write_state(self.change, state)
        self.git("add", "sdd/changes/example/STATE.md")
        self.git(
            "commit",
            "-m",
            "chore(sdd): lifecycle example READY_FOR_PR->PR_OPEN",
            "-m",
            "SDD-Lifecycle-Feature: example",
        )
        commit = self.git("rev-parse", "HEAD").stdout.strip()
        with self.assertRaisesRegex(LifecycleError, "no valid parent STATE.md"):
            classify_lifecycle_commit(self.root, commit, FEATURE)

    def test_suffix_rejects_fake_state_only_commit(self) -> None:
        self.ready()
        state_file = self.change / "STATE.md"
        state_file.write_text(state_file.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        self.git("add", "sdd/changes/example/STATE.md")
        self.git("commit", "-m", "fake state-only commit")
        with self.assertRaisesRegex(LifecycleError, "unauthorized lifecycle subject"):
            validate_ship_suffix(self.root, FEATURE)

    def test_ship_suffix_rejects_code_metrics_and_dirty_worktree(self) -> None:
        self.ready()
        (self.root / "code.py").write_text("print('unreviewed')\n", encoding="utf-8")
        self.git("add", "code.py")
        self.git("commit", "-m", "unreviewed code")
        with self.assertRaisesRegex(LifecycleError, "unauthorized lifecycle subject"):
            validate_ship_suffix(self.root, FEATURE)

        self.git("checkout", "-b", "clean-test")
        # This branch is only a test fixture; a fresh lifecycle run still starts
        # from the same implementation anchor and exercises the clean gate.
        (self.root / "dirty-metrics.md").write_text("metrics\n", encoding="utf-8")
        with self.assertRaisesRegex(LifecycleError, "clean"):
            validate_ship_suffix(self.root, FEATURE)

    def test_ship_suffix_rejects_lifecycle_subject_with_extra_path(self) -> None:
        self.ready()
        metrics = self.root / "sdd" / "metrics.md"
        metrics.write_text("not lifecycle metadata\n", encoding="utf-8")
        self.git("add", "sdd/metrics.md")
        self.git(
            "commit",
            "-m",
            "chore(sdd): lifecycle example READY_FOR_PR->PR_OPEN",
            "-m",
            "SDD-Lifecycle-Feature: example",
        )
        with self.assertRaisesRegex(LifecycleError, "outside the lifecycle allowlist"):
            validate_ship_suffix(self.root, FEATURE)

    def test_feature_slug_rejects_traversal_and_aliases(self) -> None:
        for feature in ("../example", "a/b", "a\\b", "", ".", "..", "a..b"):
            with self.subTest(feature=feature):
                with self.assertRaises(LifecycleError):
                    validate_feature_slug(feature)

    def test_marking_ready_rejects_code_commits_after_the_stable_anchor(
        self,
    ) -> None:
        self.ready()
        first_sha = read_state(self.change)["implementation_sha"]

        (self.root / "fix.txt").write_text("panel finding closed\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "close review finding")
        second_sha = self.git("rev-parse", "HEAD").stdout.strip()
        self.assertNotEqual(first_sha, second_sha)

        with self.assertRaisesRegex(LifecycleError, "unauthorized lifecycle subject"):
            mark_ready(self.root, FEATURE, "main")
        self.assertEqual(first_sha, read_state(self.change)["implementation_sha"])
        self.assertEqual(second_sha, self.git("rev-parse", "HEAD").stdout.strip())

    def test_marking_ready_again_does_not_resurrect_a_recorded_pr(self) -> None:
        """The refresh must not reopen a lifecycle that already moved past ready."""
        self.record_open()
        recorded = (self.change / "STATE.md").read_bytes()

        (self.root / "late.txt").write_text("after the PR\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "late commit")

        self.assertEqual(
            "READY_FOR_PR already passed; lifecycle is PR_OPEN.",
            mark_ready(self.root, FEATURE, "main"),
        )
        self.assertEqual(recorded, (self.change / "STATE.md").read_bytes())

    def test_recording_open_pr_does_not_archive_or_update_truth(self) -> None:
        original_spec = (self.root / "sdd/specs/example.md").read_bytes()
        original_roadmap = (self.root / "sdd/roadmap.md").read_bytes()
        self.record_open()
        self.assertTrue(self.change.is_dir())
        self.assertFalse((self.root / "sdd/changes/archive").exists())
        self.assertEqual(
            original_spec, (self.root / "sdd/specs/example.md").read_bytes()
        )
        self.assertEqual(original_roadmap, (self.root / "sdd/roadmap.md").read_bytes())
        self.assertEqual("PR_OPEN", read_state(self.change)["state"])

    def test_open_pr_cannot_be_archived(self) -> None:
        self.record_open()
        with self.assertRaisesRegex(LifecycleError, "still OPEN"):
            require_merge(
                self.root,
                FEATURE,
                runner=self.gh_runner(self.pr_payload("OPEN")),
            )
        self.assertTrue(self.change.is_dir())

    def test_closed_unmerged_pr_cannot_be_archived(self) -> None:
        self.record_open()
        with self.assertRaisesRegex(LifecycleError, "CLOSED without merge"):
            require_merge(
                self.root,
                FEATURE,
                runner=self.gh_runner(self.pr_payload("CLOSED")),
            )
        self.assertEqual("PR_OPEN", read_state(self.change)["state"])

    def test_legacy_change_can_record_real_already_merged_pr(self) -> None:
        self.ready()
        merge_sha = "d" * 40
        result = record_pr(
            self.root,
            FEATURE,
            PR_URL,
            runner=self.gh_runner(
                self.pr_payload(
                    "MERGED",
                    merged_at="2026-07-28T12:00:00Z",
                    merge_sha=merge_sha,
                )
            ),
        )
        self.assertEqual("MERGED recorded.", result)
        state = read_state(self.change)
        self.assertEqual("MERGED", state["state"])
        self.assertEqual(merge_sha, state["merge_sha"])

    def test_archive_updates_specs_and_roadmap_only_after_merge(self) -> None:
        self.record_open()
        spec = self.root / "sdd/specs/example.md"
        original_spec = spec.read_bytes()
        with self.assertRaisesRegex(LifecycleError, "still OPEN"):
            finalize_archive(
                self.root,
                FEATURE,
                specs_confirmed=True,
                runner=self.gh_runner(self.pr_payload("OPEN")),
                today=date(2026, 7, 28),
            )
        self.assertEqual(original_spec, spec.read_bytes())
        self.assertIn("- [ ] example", (self.root / "sdd/roadmap.md").read_text())

        merge_payload = self.pr_payload(
            "MERGED",
            merged_at="2026-07-28T12:00:00Z",
            merge_sha="b" * 40,
        )
        require_merge(
            self.root, FEATURE, runner=self.gh_runner(merge_payload)
        )
        spec.write_text("# Example\n\nMerged behavior.\n", encoding="utf-8")
        result = finalize_archive(
            self.root,
            FEATURE,
            specs_confirmed=True,
            runner=self.gh_runner(merge_payload),
            today=date(2026, 7, 28),
        )
        archive = self.root / "sdd/changes/archive/2026-07-28-example"
        self.assertIn("2026-07-28-example", result)
        self.assertTrue(archive.is_dir())
        self.assertEqual("ARCHIVED", read_state(archive)["state"])
        roadmap = (self.root / "sdd/roadmap.md").read_text()
        self.assertIn("- [x] example", roadmap)
        self.assertIn("changes/archive/2026-07-28-example/", roadmap)
        self.assertEqual("# Example\n\nMerged behavior.\n", spec.read_text())

    def test_blocked_change_cannot_advance_local_pr_or_archive_gates(self) -> None:
        (self.change / "BLOCKED.md").write_text("# Blocked\n\nDecision needed.\n")
        with self.assertRaisesRegex(LifecycleError, "unresolved"):
            mark_local_verified(self.root, FEATURE)
        (self.change / "BLOCKED.md").unlink()
        self.ready()
        (self.change / "BLOCKED.md").write_text("# Blocked\n\nDecision needed.\n")
        with self.assertRaisesRegex(LifecycleError, "unresolved"):
            record_pr(
                self.root,
                FEATURE,
                PR_URL,
                runner=self.gh_runner(self.pr_payload("OPEN")),
            )
        (self.change / "BLOCKED.md").unlink()
        record_pr(
            self.root,
            FEATURE,
            PR_URL,
            runner=self.gh_runner(self.pr_payload("OPEN")),
        )
        (self.change / "BLOCKED.md").write_text("# Blocked\n\nDecision needed.\n")
        with self.assertRaisesRegex(LifecycleError, "unresolved"):
            require_merge(
                self.root,
                FEATURE,
                runner=self.gh_runner(self.pr_payload("MERGED")),
            )

    def test_incomplete_tasks_cannot_advance(self) -> None:
        (self.change / "tasks.md").write_text("# Tasks\n\n- [ ] 1.1 Pending [R1]\n")
        with self.assertRaisesRegex(LifecycleError, "incomplete task"):
            mark_local_verified(self.root, FEATURE)

    def test_invalid_pr_evidence_is_rejected(self) -> None:
        self.ready()
        with self.assertRaisesRegex(LifecycleError, "baseRefName mismatch"):
            record_pr(
                self.root,
                FEATURE,
                PR_URL,
                runner=self.gh_runner(self.pr_payload("OPEN", base="develop")),
            )
        self.assertEqual("READY_FOR_PR", read_state(self.change)["state"])

    def test_missing_pr_metadata_blocks_before_gh(self) -> None:
        self.ready()
        state = read_state(self.change)
        state["state"] = "PR_OPEN"
        state["pr_state"] = "OPEN"
        write_state(self.change, state)

        def unexpected_runner(*_: object, **__: object):
            raise AssertionError("gh must not run with incomplete local metadata")

        with self.assertRaisesRegex(LifecycleError, "Incomplete PR evidence"):
            require_merge(
                self.root,
                FEATURE,
                runner=unexpected_runner,
            )

    def test_pr_missing_reviewed_commit_is_rejected(self) -> None:
        self.ready()
        with self.assertRaisesRegex(LifecycleError, "implementation SHA"):
            record_pr(
                self.root,
                FEATURE,
                PR_URL,
                runner=self.gh_runner(
                    self.pr_payload("OPEN", commits=["e" * 40])
                ),
            )

    def test_legacy_active_change_requires_explicit_migration(self) -> None:
        with self.assertRaisesRegex(LifecycleError, "Local review is not approved"):
            require_merge(
                self.root,
                FEATURE,
                runner=self.gh_runner(self.pr_payload("MERGED")),
            )
        self.assertTrue((self.change / "STATE.md").exists())

    def test_legacy_minimal_metadata_remains_readable_and_unchanged(self) -> None:
        legacy = (
            "---\n"
            "schema: 1\n"
            "state: ACTIVE\n"
            "local_review: PENDING\n"
            "---\n\n"
            "# Legacy lifecycle\n"
        )
        state_file = self.change / "STATE.md"
        state_file.write_text(legacy, encoding="utf-8")
        self.assertEqual("ACTIVE", read_state(self.change)["state"])
        self.assertEqual(
            "Lifecycle already initialized at state ACTIVE.",
            start_change(self.root, FEATURE),
        )
        self.assertEqual(legacy, state_file.read_text(encoding="utf-8"))

    def test_lifecycle_preserves_project_specific_validation_commands(self) -> None:
        project = self.root / "sdd" / "project.md"
        commands = (
            ("package.json", "npm test"),
            ("go.mod", "go test ./..."),
            ("pom.xml", "mvn test"),
        )
        for marker, command in commands:
            with self.subTest(marker=marker):
                (self.root / marker).write_text("", encoding="utf-8")
                project.write_text(
                    "# Project\n\n## Commands\n\n"
                    f"- test: {command}\n",
                    encoding="utf-8",
                )
                original = project.read_bytes()
                start_change(self.root, FEATURE)
                self.assertEqual(original, project.read_bytes())

    def test_cancelled_is_a_terminal_lateral_state(self) -> None:
        write_state(
            self.change,
            {
                "schema": "1",
                "state": "CANCELLED",
                "local_review": "PENDING",
            },
        )
        original = (self.change / "STATE.md").read_bytes()
        operations = (
            lambda: mark_local_verified(self.root, FEATURE),
            lambda: mark_ready(self.root, FEATURE, "main"),
            lambda: record_pr(
                self.root,
                FEATURE,
                PR_URL,
                runner=self.gh_runner(self.pr_payload("OPEN")),
            ),
            lambda: require_merge(
                self.root,
                FEATURE,
                runner=self.gh_runner(self.pr_payload("MERGED")),
            ),
        )
        for operation in operations:
            with self.subTest(operation=operation):
                with self.assertRaises(LifecycleError):
                    operation()
                self.assertEqual(original, (self.change / "STATE.md").read_bytes())

    def test_illegal_transition_sources_are_rejected(self) -> None:
        operations = {
            "mark-local-verified": (
                lambda: mark_local_verified(self.root, FEATURE),
                {"ARCHIVED", "CANCELLED"},
            ),
            "mark-ready": (
                lambda: mark_ready(self.root, FEATURE, "main"),
                {"ACTIVE", "ARCHIVED", "CANCELLED"},
            ),
            "record-pr": (
                lambda: record_pr(
                    self.root,
                    FEATURE,
                    PR_URL,
                    runner=self.gh_runner(self.pr_payload("OPEN")),
                ),
                {"ACTIVE", "LOCAL_VERIFIED", "ARCHIVED", "CANCELLED"},
            ),
            "verify-merge": (
                lambda: require_merge(
                    self.root,
                    FEATURE,
                    runner=self.gh_runner(self.pr_payload("MERGED")),
                ),
                {
                    "ACTIVE",
                    "LOCAL_VERIFIED",
                    "READY_FOR_PR",
                    "ARCHIVED",
                    "CANCELLED",
                },
            ),
        }
        for command, (operation, illegal_states) in operations.items():
            for state in sorted(illegal_states):
                with self.subTest(command=command, state=state):
                    write_state(
                        self.change,
                        {
                            "schema": "1",
                            "state": state,
                            "local_review": (
                                "PENDING" if state == "ACTIVE" else "APPROVED"
                            ),
                        },
                    )
                    before = (self.change / "STATE.md").read_bytes()
                    with self.assertRaises(LifecycleError):
                        operation()
                    self.assertEqual(before, (self.change / "STATE.md").read_bytes())

    def test_auto_and_archive_contracts_are_idempotent(self) -> None:
        self.record_open()
        state_once = (self.change / "STATE.md").read_bytes()
        result = record_pr(
            self.root,
            FEATURE,
            PR_URL,
            runner=self.gh_runner(self.pr_payload("OPEN")),
        )
        self.assertEqual("PR_OPEN already recorded.", result)
        self.assertEqual(state_once, (self.change / "STATE.md").read_bytes())

        merge_payload = self.pr_payload(
            "MERGED",
            merged_at="2026-07-28T12:00:00Z",
            merge_sha="c" * 40,
        )
        require_merge(self.root, FEATURE, runner=self.gh_runner(merge_payload))
        first = finalize_archive(
            self.root,
            FEATURE,
            specs_confirmed=True,
            runner=self.gh_runner(merge_payload),
            today=date(2026, 7, 28),
        )
        second = finalize_archive(
            self.root,
            FEATURE,
            specs_confirmed=True,
            runner=self.gh_runner(merge_payload),
            today=date(2026, 7, 28),
        )
        self.assertEqual(first.replace("Archived", "Already archived"), second)
        self.assertEqual(
            1,
            len(list((self.root / "sdd/changes/archive").iterdir())),
        )

    def implement_beyond_base(self) -> None:
        """Leave `main` behind the reviewed commit, as an unmerged branch does."""
        self.git("branch", "main")
        (self.change / "notes.md").write_text("implementation\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "implementation")
        self.implementation_sha = self.git("rev-parse", "HEAD").stdout.strip()
        self.ready()

    def test_unmerged_work_without_pr_cannot_be_archived(self) -> None:
        self.implement_beyond_base()
        with self.assertRaises(LifecycleError) as error:
            require_merge(self.root, FEATURE)
        self.assertIn("is not contained in", str(error.exception))
        self.assertEqual("READY_FOR_PR", read_state(self.change)["state"])

    def test_base_ancestry_proves_merge_without_a_pull_request(self) -> None:
        self.implement_beyond_base()
        self.git("checkout", "main")
        self.git("merge", "--no-ff", "-m", "merge implementation", "sdd/example")
        data, evidence, changed = require_merge(self.root, FEATURE)
        self.assertTrue(changed)
        self.assertEqual("MERGED", data["state"])
        self.assertEqual("ancestor", data["merge_evidence"])
        self.assertEqual("ancestor", evidence["evidence"])
        self.assertEqual("", data["pr_url"])
        self.assertEqual("", data["pr_state"])
        self.assertRegex(data["merge_sha"], r"^[0-9a-f]{40}$")

    def test_archive_reports_a_roadmap_tick_that_did_not_happen(self) -> None:
        """A silent no-op would let archive claim a loop the roadmap never closed."""
        (self.root / "sdd" / "roadmap.md").write_text(
            "# Roadmap\n\n- [ ] `example feature` — name does not parse alike\n",
            encoding="utf-8",
        )
        self.implement_beyond_base()
        self.git("checkout", "main")
        self.git("merge", "--no-ff", "-m", "merge implementation", "sdd/example")
        message = finalize_archive(
            self.root, FEATURE, specs_confirmed=True, today=date(2026, 7, 30)
        )
        self.assertIn("no roadmap entry names 'example'", message)
        self.assertIn(
            "- [ ] `example feature`",
            (self.root / "sdd" / "roadmap.md").read_text(encoding="utf-8"),
        )

    def test_squash_merge_proves_equivalence_without_a_pull_request(self) -> None:
        """A squash rewrites the SHA; the change is merged all the same."""
        self.implement_beyond_base()
        self.git("checkout", "main")
        self.git("merge", "--squash", "sdd/example")
        self.git("commit", "-m", "squashed implementation")
        squash_sha = self.git("rev-parse", "HEAD").stdout.strip()
        data, evidence, changed = require_merge(self.root, FEATURE)
        self.assertTrue(changed)
        self.assertEqual("MERGED", data["state"])
        self.assertEqual("equivalent", data["merge_evidence"])
        self.assertEqual("equivalent", evidence["evidence"])
        self.assertEqual(squash_sha, data["merge_sha"])
        self.assertEqual("", data["pr_url"])
        self.assertEqual("", data["pr_state"])

    def test_rebase_merge_proves_equivalence_commit_by_commit(self) -> None:
        self.git("branch", "main")
        for step in ("first", "second"):
            (self.change / f"{step}.md").write_text(f"{step}\n", encoding="utf-8")
            self.git("add", ".")
            self.git("commit", "-m", step)
        self.implementation_sha = self.git("rev-parse", "HEAD").stdout.strip()
        self.ready()
        # Base moves on, then takes the branch by rebase: every commit is copied
        # under a new SHA, so ancestry can never hold.
        self.git("checkout", "main")
        (self.root / "unrelated.md").write_text("meanwhile\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "unrelated base work")
        self.git("rebase", "main", "sdd/example")
        self.git("checkout", "main")
        self.git("merge", "--ff-only", "sdd/example")
        data, evidence, _ = require_merge(self.root, FEATURE)
        self.assertEqual("MERGED", data["state"])
        self.assertEqual("equivalent", data["merge_evidence"])
        self.assertEqual("equivalent", evidence["evidence"])
        self.assertRegex(data["merge_sha"], r"^[0-9a-f]{40}$")

    def test_unrelated_base_work_is_not_equivalence_evidence(self) -> None:
        """Only the reviewed change counts — activity in the base is not a merge."""
        self.implement_beyond_base()
        self.git("checkout", "main")
        (self.root / "unrelated.md").write_text("other work\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "unrelated base work")
        with self.assertRaises(LifecycleError) as error:
            require_merge(self.root, FEATURE)
        self.assertIn("Local review is not approved", str(error.exception))

    def test_equivalence_evidence_archives_and_stays_idempotent(self) -> None:
        self.implement_beyond_base()
        self.git("checkout", "main")
        self.git("merge", "--squash", "sdd/example")
        self.git("commit", "-m", "squashed implementation")
        message = finalize_archive(
            self.root, FEATURE, specs_confirmed=True, today=date(2026, 7, 30)
        )
        self.assertIn("2026-07-30-example", message)
        archived = self.root / "sdd/changes/archive/2026-07-30-example"
        self.assertEqual("ARCHIVED", read_state(archived)["state"])
        self.assertEqual("equivalent", read_state(archived)["merge_evidence"])

    def test_archive_move_is_staged_so_the_deletion_cannot_be_dropped(self) -> None:
        """An unstaged deletion is how an archived change comes back as active.

        `shutil.move` is invisible to git, so if the move is not staged the active
        path survives in HEAD and the next checkout writes it back as an orphan
        `STATE.md` that doctor reads as a live change.
        """
        self.implement_beyond_base()
        self.git("checkout", "main")
        self.git("merge", "--no-ff", "-m", "merge implementation", "sdd/example")
        tracked_before = self.git("ls-files", "sdd/changes/example").stdout
        self.assertIn("proposal.md", tracked_before)

        finalize_archive(
            self.root, FEATURE, specs_confirmed=True, today=date(2026, 7, 30)
        )

        # The source is gone from the index, not merely absent from disk.
        self.assertEqual(
            "", self.git("ls-files", "sdd/changes/example").stdout.strip()
        )
        staged = self.git("diff", "--cached", "--name-only").stdout
        self.assertIn("sdd/changes/archive/2026-07-30-example/proposal.md", staged)
        # Committing only what is staged must leave nothing behind at the old path.
        self.git("commit", "-m", "archive example")
        self.assertEqual(
            "", self.git("ls-files", "sdd/changes/example").stdout.strip()
        )
        # Scope: the roadmap tick stays unstaged, for the human to read first.
        self.assertIn("sdd/roadmap.md", self.git("diff", "--name-only").stdout)

    def test_staging_the_move_is_skipped_outside_a_work_tree(self) -> None:
        """Staging is a convenience, never a gate: no work tree, no `git add`."""
        attempted: list[list[str]] = []

        def runner(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            attempted.append(args)
            return subprocess.CompletedProcess(
                args=args, returncode=128, stdout="", stderr="not a git repository"
            )

        stage_archive_move(
            self.root, self.change, self.change.parent / "archive/x", runner
        )
        self.assertEqual([["git", "rev-parse", "--is-inside-work-tree"]], attempted)

    def test_repository_without_remote_completes_the_lifecycle(self) -> None:
        self.git("remote", "remove", "origin")
        self.implement_beyond_base()
        self.assertEqual("", read_state(self.change)["repository"])
        self.git("checkout", "main")
        self.git("merge", "--no-ff", "-m", "merge implementation", "sdd/example")
        message = finalize_archive(
            self.root, FEATURE, specs_confirmed=True, today=date(2026, 7, 29)
        )
        self.assertIn("2026-07-29-example", message)
        archived = self.root / "sdd/changes/archive/2026-07-29-example"
        self.assertEqual("ARCHIVED", read_state(archived)["state"])
        self.assertIn(
            "- [x] example", (self.root / "sdd/roadmap.md").read_text(encoding="utf-8")
        )


class SyncBaseTests(unittest.TestCase):
    """The base moving under an open PR — the one stretch nothing owned.

    Review stops at READY_FOR_PR and archive refuses to start before the merge,
    so with several features in flight the integration happened by hand in
    between and left no record of what was resolved. These pin what may be
    resolved mechanically, what must be handed back, and what a merge on a
    feature branch has to prove before ship will accept it.
    """

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.change = self.root / "sdd" / "changes" / FEATURE
        self.change.mkdir(parents=True)
        (self.change / "proposal.md").write_text(
            "# Proposal\n\n## Requirements\n\n### R1 — Example\n", encoding="utf-8"
        )
        (self.change / "tasks.md").write_text(
            "# Tasks\n\n- [x] 1.1 Complete behavior [R1]\n", encoding="utf-8"
        )
        (self.root / "sdd" / "roadmap.md").write_text(
            "# Roadmap\n\n- [ ] example — lifecycle fixture → changes/example/\n",
            encoding="utf-8",
        )
        (self.root / "README.md").write_text("# fixture\n\ncomun\n", encoding="utf-8")
        write_state(self.change, initial_state())
        self.git("init", "-b", "sdd/example")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "SDD Test")
        self.git("add", ".")
        self.git("commit", "-m", "fixture")
        self.git("branch", "main")

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=self.root, check=True, capture_output=True, text=True
        )

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").stdout.strip()

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-m", message)
        return self.head()

    def ready(self) -> None:
        mark_local_verified(self.root, FEATURE)
        mark_ready(self.root, FEATURE, "main")
        self.implementation_sha = read_state(self.change)["implementation_sha"]

    def base_gains(self, relative: str, content: str, message: str = "base work") -> str:
        """A commit lands on the base while this branch is out for review."""
        self.git("checkout", "main")
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        sha = self.commit(message)
        self.git("checkout", "sdd/example")
        return sha

    def test_a_base_that_has_not_moved_is_left_untouched(self) -> None:
        self.ready()
        before = self.head()
        report = sync_base(self.root, FEATURE)
        self.assertFalse(report["synced"])
        self.assertEqual([], report["pending"])
        self.assertIn("already contains", str(report["reason"]))
        self.assertEqual(before, self.head())

    def test_a_base_that_moved_is_merged_and_the_reviewed_anchor_survives(self) -> None:
        """Merge, never rebase: the anchor is what every later gate reads."""
        self.ready()
        base_sha = self.base_gains("colega.md", "otro trabajo\n")
        report = sync_base(self.root, FEATURE)
        self.assertTrue(report["synced"], report)
        commit = str(report["commit"])
        parents = self.git("show", "-s", "--format=%P", commit).stdout.split()
        self.assertEqual(2, len(parents))
        self.assertEqual(base_sha, parents[1])
        self.assertEqual(
            f"chore(sdd): sync example main@{base_sha[:12]}",
            self.git("show", "-s", "--format=%s", commit).stdout.strip(),
        )
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", self.implementation_sha, "HEAD"],
            cwd=self.root,
            check=True,
            capture_output=True,
        )
        self.assertIn(commit, validate_ship_suffix(self.root, FEATURE))

    def test_a_bookkeeping_conflict_is_resolved_by_keeping_both_lines(self) -> None:
        roadmap = self.root / "sdd" / "roadmap.md"
        roadmap.write_text(
            roadmap.read_text() + "- [ ] otra — de la rama → changes/otra/\n",
            encoding="utf-8",
        )
        self.commit("roadmap entry for this change")
        self.ready()
        self.git("checkout", "main")
        base_roadmap = self.root / "sdd" / "roadmap.md"
        base_roadmap.write_text(
            base_roadmap.read_text() + "- [ ] tercera — de la base → changes/tercera/\n",
            encoding="utf-8",
        )
        self.commit("roadmap entry on the base")
        self.git("checkout", "sdd/example")

        report = sync_base(self.root, FEATURE)
        self.assertTrue(report["synced"], report)
        self.assertEqual(["sdd/roadmap.md"], report["resolved"])
        merged = roadmap.read_text(encoding="utf-8")
        self.assertIn("- [ ] otra — de la rama", merged)
        self.assertIn("- [ ] tercera — de la base", merged)
        self.assertNotIn("<<<<", merged)
        self.assertIn(str(report["commit"]), validate_ship_suffix(self.root, FEATURE))

    def test_a_union_that_would_duplicate_an_entry_is_not_a_resolution(self) -> None:
        """Both sides touching the SAME entry is a decision, not a union."""
        roadmap = self.root / "sdd" / "roadmap.md"
        roadmap.write_text(
            "# Roadmap\n\n- [ ] example — reescrito en la rama → changes/example/\n",
            encoding="utf-8",
        )
        self.commit("reword the entry")
        self.ready()
        self.git("checkout", "main")
        roadmap.write_text(
            "# Roadmap\n\n- [x] example — lifecycle fixture → changes/example/\n",
            encoding="utf-8",
        )
        self.commit("tick the entry on the base")
        self.git("checkout", "sdd/example")

        report = sync_base(self.root, FEATURE)
        self.assertFalse(report["synced"])
        self.assertEqual(["sdd/roadmap.md"], report["pending"])
        self.assertTrue(
            any("duplicate" in note for note in report["notes"]), report["notes"]
        )
        self.assertTrue(sdd_lifecycle.merge_in_progress(self.root))

    def test_a_code_conflict_is_left_in_progress_and_recorded_when_resolved(self) -> None:
        readme = self.root / "README.md"
        readme.write_text("# fixture\n\nde la rama\n", encoding="utf-8")
        self.commit("branch edit")
        self.ready()
        self.base_gains("README.md", "# fixture\n\nde la base\n", "base edit")

        report = sync_base(self.root, FEATURE)
        self.assertFalse(report["synced"])
        self.assertEqual(["README.md"], report["pending"])
        self.assertTrue(sdd_lifecycle.merge_in_progress(self.root))

        readme.write_text("# fixture\n\nde la rama y de la base\n", encoding="utf-8")
        self.git("add", "--", "README.md")
        commit, conflicts = commit_sync(
            self.root, FEATURE, verification="python3 -m unittest"
        )
        self.assertEqual(["README.md"], conflicts)
        body = self.git("show", "-s", "--format=%B", commit).stdout
        self.assertIn("SDD-Sync-Resolved: README.md", body)
        self.assertIn("SDD-Sync-Verified: python3 -m unittest -> ok", body)
        self.assertIn("SDD-Lifecycle-Feature: example", body)
        self.assertIn(commit, validate_ship_suffix(self.root, FEATURE))

    def test_a_failed_verification_is_recorded_rather_than_hidden(self) -> None:
        readme = self.root / "README.md"
        readme.write_text("# fixture\n\nde la rama\n", encoding="utf-8")
        self.commit("branch edit")
        self.ready()
        self.base_gains("README.md", "# fixture\n\nde la base\n", "base edit")
        sync_base(self.root, FEATURE)
        readme.write_text("# fixture\n\nresuelto\n", encoding="utf-8")
        self.git("add", "--", "README.md")
        commit, _ = commit_sync(self.root, FEATURE, verification="make test", failed=True)
        self.assertIn(
            "SDD-Sync-Verified: make test -> FAILED",
            self.git("show", "-s", "--format=%B", commit).stdout,
        )

    def test_leftover_conflict_markers_are_never_recorded_as_resolved(self) -> None:
        readme = self.root / "README.md"
        readme.write_text("# fixture\n\nde la rama\n", encoding="utf-8")
        self.commit("branch edit")
        self.ready()
        self.base_gains("README.md", "# fixture\n\nde la base\n", "base edit")
        sync_base(self.root, FEATURE)
        readme.write_text(
            "# fixture\n\n<<<<<<< HEAD\nde la rama\n=======\nde la base\n>>>>>>> main\n",
            encoding="utf-8",
        )
        self.git("add", "--", "README.md")
        with self.assertRaises(LifecycleError) as caught:
            commit_sync(self.root, FEATURE)
        self.assertIn("conflict markers", str(caught.exception))

    def test_ship_rejects_a_merge_it_did_not_authorize(self) -> None:
        self.ready()
        self.git("checkout", "-b", "otra", "main")
        (self.root / "otra.md").write_text("otra rama\n", encoding="utf-8")
        self.commit("otra rama")
        self.git("checkout", "sdd/example")
        self.git("merge", "--no-edit", "otra")
        with self.assertRaises(LifecycleError) as caught:
            validate_ship_suffix(self.root, FEATURE)
        self.assertIn("unauthorized subject", str(caught.exception))

    def test_a_sync_that_did_not_come_from_the_base_is_rejected(self) -> None:
        """The subject is a claim; containment in the base is the fact."""
        self.ready()
        self.git("checkout", "-b", "otra", "main")
        (self.root / "otra.md").write_text("otra rama\n", encoding="utf-8")
        foreign = self.commit("otra rama")
        self.git("checkout", "sdd/example")
        self.git("merge", "--no-commit", "--no-ff", "otra")
        self.git(
            "commit",
            "-m",
            f"chore(sdd): sync example main@{foreign[:12]}",
            "-m",
            "SDD-Lifecycle-Feature: example",
        )
        with self.assertRaises(LifecycleError) as caught:
            validate_ship_suffix(self.root, FEATURE)
        self.assertIn("not contained in", str(caught.exception))

    def test_syncing_needs_a_published_state_and_a_clean_tree(self) -> None:
        with self.assertRaises(LifecycleError) as caught:
            sync_base(self.root, FEATURE)
        self.assertIn("is ACTIVE", str(caught.exception))
        self.ready()
        (self.root / "suelto.md").write_text("sin commitear\n", encoding="utf-8")
        with self.assertRaises(LifecycleError) as caught:
            sync_base(self.root, FEATURE)
        self.assertIn("clean", str(caught.exception))


class UnionResolutionTests(unittest.TestCase):
    def test_a_repeated_metrics_row_is_detected(self) -> None:
        text = (
            "| feature | coste |\n| --- | --- |\n| alpha | 1 |\n| alpha | 2 |\n"
            "| beta | 3 |\n"
        )
        self.assertEqual(["alpha"], duplicate_bookkeeping_keys("sdd/metrics.md", text))

    def test_a_table_separator_is_not_a_row(self) -> None:
        text = "| feature |\n| --- |\n| --- |\n"
        self.assertEqual([], duplicate_bookkeeping_keys("sdd/metrics.md", text))

    def test_unrelated_roadmap_entries_are_not_duplicates(self) -> None:
        text = (
            "- [ ] alpha — una → changes/alpha/\n"
            "- [x] beta — otra → changes/archive/2026-01-01-beta/\n"
        )
        self.assertEqual([], duplicate_bookkeeping_keys("sdd/roadmap.md", text))


class PublishArchiveTests(unittest.TestCase):
    """Closing the loop where everybody else can see it.

    An archive committed and never pushed leaves the base diverged from origin
    forever: every later feature branches from `origin/<base>` (EnterWorktree's
    `fresh` default), so it branches from a base without the archive, the check
    reports unpushed commits on every feature, and another clone still reads the
    change as active. These tests pin what is allowed to be pushed — and what
    stops the push instead.
    """

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.archive = self.root / "sdd" / "changes" / "archive" / "2026-01-01-example"
        self.archive.mkdir(parents=True)
        (self.root / "sdd" / "roadmap.md").write_text(
            "# Roadmap\n\n- [x] example → changes/archive/2026-01-01-example/\n",
            encoding="utf-8",
        )
        self.git("init", "-b", "main")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "SDD Test")
        (self.root / "README.md").write_text("# fixture\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "fixture")

        remote_dir = tempfile.TemporaryDirectory()
        self.addCleanup(remote_dir.cleanup)
        self.remote = Path(remote_dir.name)
        self.git("init", "--bare", str(self.remote))
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-u", "origin", "main")
        self.write_archive_state()

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=self.root, check=True, capture_output=True, text=True
        )

    def write_archive_state(self, state: str = "ARCHIVED", base: str = "main") -> None:
        (self.archive / "STATE.md").write_text(
            f"---\nschema: 1\nstate: {state}\nbase_branch: {base}\n"
            "merge_evidence: pr\nmerge_sha: abc123\n---\n",
            encoding="utf-8",
        )

    def commit_archive(self) -> str:
        self.git("add", "-A", "sdd")
        self.git("commit", "-m", "chore(sdd): archive example")
        return self.git("rev-parse", "HEAD").stdout.strip()

    def remote_sha(self, ref: str = "refs/heads/main") -> str:
        return subprocess.run(
            ["git", "--git-dir", str(self.remote), "rev-parse", ref],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    def test_it_pushes_the_archive_commit_to_the_base(self) -> None:
        local = self.commit_archive()
        message = publish_archive(self.root, "example")
        self.assertIn("Published 1 archive commit(s)", message)
        self.assertEqual(local, self.remote_sha())

    def test_dry_run_reports_what_would_be_pushed_and_pushes_nothing(self) -> None:
        before = self.remote_sha()
        self.commit_archive()
        message = publish_archive(self.root, "example", dry_run=True)
        self.assertIn("Would push 1 archive commit(s)", message)
        self.assertEqual(before, self.remote_sha())

    def test_an_uncommitted_archive_is_refused_before_anything_is_pushed(self) -> None:
        """Half a staged archive is exactly how an orphan STATE.md reaches main."""
        with self.assertRaises(LifecycleError) as caught:
            publish_archive(self.root, "example")
        self.assertIn("uncommitted changes", str(caught.exception))

    def test_unrelated_local_work_on_the_base_stops_the_push(self) -> None:
        self.commit_archive()
        (self.root / "src.py").write_text("print('hola')\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", "trabajo suelto en main")
        with self.assertRaises(LifecycleError) as caught:
            publish_archive(self.root, "example")
        self.assertIn("outside sdd/", str(caught.exception))
        self.assertIn("src.py", str(caught.exception))

    def test_a_remote_that_moved_on_is_the_users_to_integrate(self) -> None:
        """Never a force-push, and never a silent merge on somebody's behalf."""
        local = self.commit_archive()
        # A colleague's commit reaches origin/main while we were archiving: it
        # branches from the base we started at, so the two histories diverge.
        self.git("switch", "-c", "colega", "main~1")
        (self.root / "colega.md").write_text("otro trabajo\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", "trabajo del colega")
        self.git("push", "origin", "colega:main")
        self.git("switch", "main")
        self.git("branch", "-D", "colega")
        self.assertNotEqual(local, self.remote_sha())
        with self.assertRaises(LifecycleError) as caught:
            publish_archive(self.root, "example")
        self.assertIn("moved on", str(caught.exception))
        self.assertNotIn("force", str(caught.exception).split("never")[0])
        self.assertNotEqual(local, self.remote_sha())

    def test_publishing_from_another_branch_is_refused(self) -> None:
        self.commit_archive()
        self.git("switch", "-c", "sdd/otra")
        with self.assertRaises(LifecycleError) as caught:
            publish_archive(self.root, "example")
        self.assertIn("must happen on 'main'", str(caught.exception))

    def test_a_change_that_is_not_archived_yet_has_nothing_to_publish(self) -> None:
        self.write_archive_state(state="MERGED")
        self.commit_archive()
        with self.assertRaises(LifecycleError) as caught:
            publish_archive(self.root, "example")
        self.assertIn("not recorded as ARCHIVED", str(caught.exception))

    def test_no_remote_is_a_supported_workflow_not_an_error(self) -> None:
        self.commit_archive()
        self.git("remote", "remove", "origin")
        self.assertIn("stays local", publish_archive(self.root, "example"))

    def test_publishing_twice_is_idempotent(self) -> None:
        self.commit_archive()
        publish_archive(self.root, "example")
        self.assertIn("already matches", publish_archive(self.root, "example"))

    def test_the_cli_exposes_it(self) -> None:
        self.commit_archive()
        self.assertEqual(
            0,
            sdd_lifecycle.main(
                ["--root", str(self.root), "publish-archive", "example", "--dry-run"]
            ),
        )


class RoadmapTickTests(unittest.TestCase):
    """The archive tick, now that /sdd:new no longer annotates in-flight changes."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "sdd").mkdir()

    def write(self, content: str) -> None:
        (self.root / "sdd" / "roadmap.md").write_text(content, encoding="utf-8")

    def read(self) -> str:
        return (self.root / "sdd" / "roadmap.md").read_text(encoding="utf-8")

    def test_appends_the_archive_pointer_when_the_entry_has_none(self) -> None:
        self.write("# Roadmap\n\n- [ ] example — sin anotación in-flight\n")
        self.assertEqual(
            "ticked", update_roadmap(self.root, "example", "changes/archive/2026-08-04-example/")
        )
        self.assertIn(
            "- [x] example — sin anotación in-flight → "
            "changes/archive/2026-08-04-example/",
            self.read(),
        )

    def test_rewrites_a_legacy_in_flight_pointer_instead_of_appending(self) -> None:
        self.write("# Roadmap\n\n- [ ] example — legacy → changes/example/\n")
        update_roadmap(self.root, "example", "changes/archive/2026-08-04-example/")
        roadmap = self.read()
        self.assertIn("→ changes/archive/2026-08-04-example/", roadmap)
        self.assertEqual(1, roadmap.count("→"))

    def test_the_tick_is_idempotent(self) -> None:
        self.write("# Roadmap\n\n- [ ] example — algo\n")
        archive = "changes/archive/2026-08-04-example/"
        update_roadmap(self.root, "example", archive)
        first = self.read()
        self.assertEqual("current", update_roadmap(self.root, "example", archive))
        self.assertEqual(first, self.read())

    def test_the_metadata_sub_line_is_left_untouched(self) -> None:
        self.write(
            "## Stage 1 — el dominio persiste\n\n"
            "- [ ] example — algo\n"
            "      needs: other · size: M\n"
        )
        update_roadmap(self.root, "example", "changes/archive/2026-08-04-example/")
        roadmap = self.read()
        self.assertIn("      needs: other · size: M\n", roadmap)
        self.assertIn("- [x] example — algo → changes/archive/", roadmap)

    def test_an_unmatched_feature_is_reported_not_silently_skipped(self) -> None:
        self.write("# Roadmap\n\n- [ ] other — algo\n")
        self.assertEqual(
            "unmatched", update_roadmap(self.root, "example", "changes/archive/x/")
        )

    def test_no_roadmap_at_all_is_reported_as_absent(self) -> None:
        self.assertEqual(
            "absent", update_roadmap(self.root, "example", "changes/archive/x/")
        )


if __name__ == "__main__":
    unittest.main()
