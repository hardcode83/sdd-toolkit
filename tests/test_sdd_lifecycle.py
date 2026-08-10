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

from sdd_lifecycle import (  # noqa: E402
    LifecycleError,
    finalize_archive,
    mark_local_verified,
    mark_ready,
    read_state,
    record_pr,
    require_merge,
    stage_archive_move,
    start_change,
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
        self.assertEqual("ACTIVE recorded.", start_change(self.root, FEATURE))
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
        self.assertEqual("ACTIVE recorded.", start_change(self.root, FEATURE))
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
        anchor = self.git("rev-parse", "HEAD").stdout.strip()
        self.assertEqual("READY_FOR_PR recorded.", mark_ready(self.root, FEATURE, "main"))
        lifecycle = self.git("rev-parse", "HEAD").stdout.strip()
        self.assertEqual(anchor, read_state(self.change)["implementation_sha"])
        self.assertEqual(anchor, self.git("rev-parse", "HEAD^").stdout.strip())
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
        self.assertEqual([lifecycle], validate_ship_suffix(self.root, FEATURE))

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
            [self.git("rev-parse", "HEAD^").stdout.strip(), lifecycle],
            validate_ship_suffix(self.root, FEATURE),
        )

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
        with self.assertRaisesRegex(LifecycleError, "Legacy active change"):
            require_merge(
                self.root,
                FEATURE,
                runner=self.gh_runner(self.pr_payload("MERGED")),
            )
        self.assertFalse((self.change / "STATE.md").exists())

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
        self.assertIn("Legacy active change has no STATE.md", str(error.exception))

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
