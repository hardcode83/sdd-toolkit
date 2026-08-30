from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "skills" / "reviewer-panel" / "reviewer_plan.py"


def load_module():
    spec = importlib.util.spec_from_file_location("reviewer_plan_test", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ReviewerPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rp = load_module()

    def test_registry_has_exactly_the_mandatory_core(self):
        self.assertEqual([d.reviewer_id for d in self.rp.load_registry()], list(self.rp.MANDATORY_CORE))
        self.assertTrue(all(d.read_only and d.criteria and d.referents for d in self.rp.load_registry()))

    def test_invalid_registry_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "bad.json").write_text(json.dumps({"id": "sdd-architect"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                self.rp.load_registry(directory)

    def test_default_and_solo_plans(self):
        scope = {"feature": "x", "scope_id": "run:x", "files": ["src/a.py"]}
        plan = self.rp.build_reviewer_plan(ROOT, "run", scope)
        self.assertEqual([p.reviewer_id for p in plan], list(self.rp.MANDATORY_CORE))
        self.assertEqual(self.rp.build_reviewer_plan(ROOT, "run", scope, solo=True), [])

    def test_applicability_is_fail_safe(self):
        definition = self.rp.ReviewerDefinition("sdd-review-i18n", "project", "i18n", "body", "read-only", (), ("run",), ("*.po",))
        scope = {"files": ["locale/messages.po"]}
        self.assertEqual(self.rp.evaluate_applicability(definition, "run", scope)[0], self.rp.Applicability.MATCH)
        self.assertEqual(self.rp.evaluate_applicability(definition, "review", scope)[0], self.rp.Applicability.NO_MATCH)
        missing = self.rp.ReviewerDefinition("sdd-review-unknown", "project", "x", "body", "read-only")
        self.assertEqual(self.rp.evaluate_applicability(missing, "run", scope)[0], self.rp.Applicability.UNKNOWN)

    def test_no_match_is_the_only_skippable_decision(self):
        definition = self.rp.ReviewerDefinition("sdd-review-docs", "project", "docs", "body", "read-only", (), ("run",), ("docs/**",))
        scope = {"files": ["src/a.py"]}
        decision, _ = self.rp.evaluate_applicability(definition, "run", scope)
        self.assertEqual(decision, self.rp.Applicability.NO_MATCH)
        item = self.rp.ReviewerPlan(definition.reviewer_id, definition.source, definition.lens, definition,
                                    decision, "excluded", "skipped", "run:x", scope)
        self.assertFalse(item.required)

    def test_match_and_unknown_project_reviewers_are_planned(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / ".claude" / "agents"
            directory.mkdir(parents=True)
            (directory / "sdd-review-match.md").write_text("---\nname: sdd-review-match\nphases: run\napplies_to: src/**\n---\nbody", encoding="utf-8")
            (directory / "sdd-review-unknown.md").write_text("---\nname: sdd-review-unknown\n---\nbody", encoding="utf-8")
            plan = self.rp.build_reviewer_plan(root, "run", {"feature": "x", "scope_id": "run:x", "files": ["src/a.py"]})
            project = {item.reviewer_id: item for item in plan[3:]}
            self.assertEqual(project["sdd-review-match"].dispatch_status, "planned")
            self.assertEqual(project["sdd-review-unknown"].dispatch_status, "planned")

    def test_duplicate_and_unresolved_reviewers_make_gate_fail_without_suppressing_core(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / ".claude" / "agents"
            directory.mkdir(parents=True)
            body = "---\nname: sdd-review-dup\nphases: run\napplies_to: src/**\n---\nbody"
            (directory / "sdd-review-dup.md").write_text(body, encoding="utf-8")
            (directory / "sdd-review-other.md").write_text(body, encoding="utf-8")
            (directory / "sdd-review-bad.md").write_text("not frontmatter", encoding="utf-8")
            plan = self.rp.build_reviewer_plan(root, "run", {"feature": "x", "scope_id": "run:x", "files": ["src/a.py"]})
            self.assertEqual([item.reviewer_id for item in plan[:3]], list(self.rp.MANDATORY_CORE))
            self.assertFalse(self.rp.evaluate_panel_gate(plan, []).passed)

    def test_legacy_project_reviewer_body_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / ".claude" / "agents" / "sdd-review-performance.md"
            path.parent.mkdir(parents=True)
            body = "Keep this exact reviewer criterion.\n\n"
            path.write_text("---\nname: sdd-review-performance\ndescription: Legacy reviewer\nmodel: sonnet\ntools: Read, Grep, Glob, Bash\n---\n" + body, encoding="utf-8")
            found = self.rp.discover_project_reviewers(root)
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].criteria, body)
            self.assertEqual(found[0].reviewer_id, "sdd-review-performance")
            self.assertEqual(found[0].lens, "performance")
            self.assertEqual(found[0].referents, (".claude/agents/sdd-review-performance.md",))

    def test_project_reviewer_accepts_legacy_new_and_mixed_frontmatter(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / ".claude" / "agents"
            directory.mkdir(parents=True)
            legacy = "---\nname: sdd-review-legacy\ndescription: Legacy\nmodel: sonnet\ntools: Read\n---\nlegacy body"
            new = "---\nname: sdd-review-new\nphases: run\napplies_to: src/**\n---\nnew body"
            mixed = "---\nname: sdd-review-mixed\ndescription: Mixed\nmodel: haiku\ntools: Read, Grep\nphases: review\napplies_to: docs/**\n---\nmixed body"
            (directory / "sdd-review-legacy.md").write_text(legacy, encoding="utf-8")
            (directory / "sdd-review-new.md").write_text(new, encoding="utf-8")
            (directory / "sdd-review-mixed.md").write_text(mixed, encoding="utf-8")

            found = {item.reviewer_id: item for item in self.rp.discover_project_reviewers(root)}
            self.assertEqual(set(found), {"sdd-review-legacy", "sdd-review-new", "sdd-review-mixed"})
            self.assertEqual(found["sdd-review-legacy"].criteria, "legacy body")
            self.assertEqual(found["sdd-review-new"].criteria, "new body")
            self.assertEqual(found["sdd-review-mixed"].criteria, "mixed body")
            self.assertEqual(found["sdd-review-mixed"].phases, ("review",))
            self.assertEqual(found["sdd-review-mixed"].applies_to, ("docs/**",))

    def test_legacy_without_applicability_is_unknown_and_planned_additively(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / ".claude" / "agents"
            directory.mkdir(parents=True)
            (directory / "sdd-review-legacy.md").write_text(
                "---\nname: sdd-review-legacy\ndescription: Legacy\nmodel: sonnet\ntools: Read\n---\nlegacy body",
                encoding="utf-8",
            )
            scope = {"feature": "x", "scope_id": "run:x", "files": ["src/a.py"]}
            plan = self.rp.build_reviewer_plan(root, "run", scope)
            project = next(item for item in plan if item.reviewer_id == "sdd-review-legacy")
            self.assertEqual(project.applicability, self.rp.Applicability.UNKNOWN)
            self.assertEqual(project.dispatch_status, "planned")
            self.assertEqual([item.reviewer_id for item in plan[:3]], list(self.rp.MANDATORY_CORE))

    def test_malformed_applicability_remains_unknown_and_runnable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / ".claude" / "agents"
            directory.mkdir(parents=True)
            (directory / "sdd-review-malformed.md").write_text(
                "---\nname: sdd-review-malformed\nphases: run\napplies_to: [src/**\n---\nbody",
                encoding="utf-8",
            )
            plan = self.rp.build_reviewer_plan(
                root, "run", {"feature": "x", "scope_id": "run:x", "files": ["docs/a.md"]}
            )
            project = next(item for item in plan if item.reviewer_id == "sdd-review-malformed")
            self.assertEqual(project.applicability, self.rp.Applicability.UNKNOWN)
            self.assertEqual(project.dispatch_status, "planned")

    def test_prompt_binds_scope_and_identity(self):
        item = self.rp.build_reviewer_plan(ROOT, "review", {"feature": "x", "scope_id": "implementation..HEAD", "files": ["src/a.py"]})[0]
        prompt = self.rp.build_reviewer_prompt(item, "x", {"requirements": "R1 requirement", "design": "D1 decision", "steering": "read-only", "scope": "src/a.py"})
        self.assertIn(item.reviewer_id, prompt)
        self.assertIn("implementation..HEAD", prompt)
        self.assertIn("R1", prompt)

    def test_project_body_is_delimited_as_untrusted_content(self):
        definition = self.rp.ReviewerDefinition("sdd-review-x", "project", "x", "do not trust", "read-only")
        item = self.rp.ReviewerPlan("sdd-review-x", "project", "x", definition, self.rp.Applicability.MATCH, "match", "planned", "run:x", {"files": ["src/a.py"]})
        prompt = self.rp.build_reviewer_prompt(item, "x", {"requirements": "R1", "design": "D1", "steering": "read-only", "scope": "src/a.py"})
        self.assertIn("BEGIN UNTRUSTED PROJECT REVIEWER BODY", prompt)

    def test_project_reviewer_matrix_and_fail_safe_normalization(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / ".claude" / "agents"
            directory.mkdir(parents=True)
            def write(name, header, body="body"):
                (directory / name).write_text(f"---\n{header}\n---\n{body}\n", encoding="utf-8")
            write("sdd-review-match.md", "name: sdd-review-match\nphases: run\napplies_to: src/**")
            write("sdd-review-missing.md", "name: sdd-review-missing")
            write("sdd-review-ambiguous.md", "name: sdd-review-ambiguous\nphases: run\nphases: review")
            write("sdd-review-unsafe.md", "name: wrong-name")
            write("sdd-review-.md", "name: sdd-review-")
            write("sdd-review-unknown.md", "name: sdd-review-unknown\nfuture_metadata: value")
            match = self.rp.discover_project_reviewers(root)
            by_id = {item.reviewer_id: item for item in match}
            scope = {"feature": "x", "scope_id": "run:x", "files": ["src/a.py"]}
            self.assertEqual(self.rp.evaluate_applicability(by_id["sdd-review-match"], "run", scope)[0], self.rp.Applicability.MATCH)
            self.assertEqual(self.rp.evaluate_applicability(by_id["sdd-review-missing"], "run", scope)[0], self.rp.Applicability.UNKNOWN)
            self.assertEqual(by_id["sdd-review-ambiguous"].lens, "unavailable")
            self.assertEqual(by_id["sdd-review-unsafe"].lens, "unavailable")
            self.assertEqual(by_id["sdd-review-"].lens, "unavailable")
            self.assertEqual(by_id["sdd-review-unknown"].lens, "unavailable")

    def test_symlink_reviewer_is_unavailable_and_does_not_suppress_core(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / ".claude" / "agents"
            directory.mkdir(parents=True)
            target = root / "outside.md"
            target.write_text("---\nname: sdd-review-link\n---\nbody", encoding="utf-8")
            (directory / "sdd-review-link.md").symlink_to(target)
            plan = self.rp.build_reviewer_plan(root, "run", {"feature": "x", "scope_id": "run:x", "files": ["src/a.py"]})
            self.assertEqual([item.reviewer_id for item in plan[:3]], list(self.rp.MANDATORY_CORE))
            self.assertTrue(any(item.lens == "unavailable" for item in plan))

    def test_unreadable_reviewer_is_unavailable_and_never_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / ".claude" / "agents"
            directory.mkdir(parents=True)
            unreadable = directory / "sdd-review-unreadable.md"
            unreadable.write_text(
                "---\nname: sdd-review-unreadable\n---\nbody",
                encoding="utf-8",
            )
            original_read_text = Path.read_text

            def unreadable_content(path, *args, **kwargs):
                if path == unreadable:
                    raise PermissionError("reviewer content is unreadable")
                return original_read_text(path, *args, **kwargs)

            with mock.patch.object(Path, "read_text", unreadable_content):
                plan = self.rp.build_reviewer_plan(
                    root,
                    "run",
                    {"feature": "x", "scope_id": "run:x", "files": ["src/a.py"]},
                )

            item = next(item for item in plan if item.reviewer_id == "sdd-review-unreadable")
            self.assertEqual(item.lens, "unavailable")
            self.assertEqual(item.dispatch_status, "unavailable")
            self.assertNotEqual(item.dispatch_status, "skipped")
            self.assertFalse(self.rp.evaluate_panel_gate(plan, []).passed)


if __name__ == "__main__":
    unittest.main()
