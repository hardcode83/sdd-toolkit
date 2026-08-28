#!/usr/bin/env python3
"""Dependency-free validation contracts for the SDD toolkit."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
EXPECTATIONS = ROOT / "tests" / "fixture_expectations.json"
FRONTMATTER_RE = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)
PLUGIN_REFERENCE_RE = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9_./-]+)")
COMMAND_RE = re.compile(r"/sdd:([a-z][a-z0-9-]*)")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
DIAGNOSTIC_RE = re.compile(r"^(ERROR|WARNING) (SDD\d{3}) ")
STACK_COMMAND_RE = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(?:build|test|lint|typecheck|run)\s*[:=].*"
    r"(?:python3?|pytest|unittest|pip|npm test|go test)\b"
)


def read_json(path: Path, root: Path, errors: list[str]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"{path.relative_to(root)}: invalid JSON: {error}")
        return None


def validate_manifests(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    plugin_path = root / ".claude-plugin" / "plugin.json"
    marketplace_path = root / ".claude-plugin" / "marketplace.json"
    hooks_path = root / "hooks" / "hooks.json"
    plugin = read_json(plugin_path, root, errors)
    marketplace = read_json(marketplace_path, root, errors)
    hooks = read_json(hooks_path, root, errors)

    if isinstance(plugin, dict):
        for field in ("name", "description", "version", "author", "repository"):
            if not plugin.get(field):
                errors.append(f".claude-plugin/plugin.json: missing '{field}'")
        if plugin.get("version") and not SEMVER_RE.match(str(plugin["version"])):
            errors.append(".claude-plugin/plugin.json: version must be MAJOR.MINOR.PATCH")
        if not isinstance(plugin.get("author"), dict) or not plugin["author"].get("name"):
            errors.append(".claude-plugin/plugin.json: author.name is required")

    if isinstance(marketplace, dict):
        if not marketplace.get("name"):
            errors.append(".claude-plugin/marketplace.json: name is required")
        plugins = marketplace.get("plugins")
        if not isinstance(plugins, list) or not plugins:
            errors.append(".claude-plugin/marketplace.json: plugins must be non-empty")
        else:
            names: list[str] = []
            for index, entry in enumerate(plugins):
                if not isinstance(entry, dict):
                    errors.append(
                        f".claude-plugin/marketplace.json: plugins[{index}] must be an object"
                    )
                    continue
                name = entry.get("name")
                source = entry.get("source")
                if not name or not source:
                    errors.append(
                        f".claude-plugin/marketplace.json: plugins[{index}] needs name/source"
                    )
                    continue
                names.append(str(name))
                if not (root / str(source)).resolve().is_dir():
                    errors.append(
                        f".claude-plugin/marketplace.json: source '{source}' does not exist"
                    )
            if len(names) != len(set(names)):
                errors.append(".claude-plugin/marketplace.json: plugin names must be unique")

    if isinstance(hooks, dict):
        configured = hooks.get("hooks")
        if not isinstance(configured, dict):
            errors.append("hooks/hooks.json: hooks must be an object")
        elif not isinstance(configured.get("PreToolUse"), list):
            errors.append("hooks/hooks.json: PreToolUse must be a list")

    errors.extend(
        validate_codex_manifests(
            root, plugin.get("version") if isinstance(plugin, dict) else None
        )
    )
    return errors


def validate_codex_manifests(root: Path, plugin_version: object) -> list[str]:
    """The Codex adapter ships its own manifests, so they need the same checks.

    Nothing else reads them: unvalidated, the adapter's version silently drifted
    away from the plugin it adapts, announcing a release that no longer exists.
    """
    errors: list[str] = []
    codex_plugin_path = root / ".codex-plugin" / "plugin.json"
    codex_marketplace_path = root / ".agents" / "plugins" / "marketplace.json"
    codex_plugin = read_json(codex_plugin_path, root, errors)
    codex_marketplace = read_json(codex_marketplace_path, root, errors)

    if isinstance(codex_plugin, dict):
        for field in ("name", "description", "version", "author"):
            if not codex_plugin.get(field):
                errors.append(f".codex-plugin/plugin.json: missing '{field}'")
        version = str(codex_plugin.get("version", ""))
        if version and not SEMVER_RE.match(version):
            errors.append(".codex-plugin/plugin.json: version must be MAJOR.MINOR.PATCH")
        elif plugin_version and version != str(plugin_version):
            errors.append(
                f".codex-plugin/plugin.json: version {version} must match "
                f".claude-plugin/plugin.json version {plugin_version} — the adapter "
                "exposes those exact skills"
            )
        skills = codex_plugin.get("skills")
        if not skills or not (root / str(skills)).is_dir():
            errors.append(
                f".codex-plugin/plugin.json: skills path '{skills}' does not exist"
            )

    if isinstance(codex_marketplace, dict):
        if not codex_marketplace.get("name"):
            errors.append(".agents/plugins/marketplace.json: name is required")
        plugins = codex_marketplace.get("plugins")
        if not isinstance(plugins, list) or not plugins:
            errors.append(".agents/plugins/marketplace.json: plugins must be non-empty")
        else:
            for index, entry in enumerate(plugins):
                if not isinstance(entry, dict) or not entry.get("name"):
                    errors.append(
                        f".agents/plugins/marketplace.json: plugins[{index}] needs a name"
                    )
                    continue
                source = entry.get("source")
                path = source.get("path") if isinstance(source, dict) else None
                if not path or not (root / str(path)).is_dir():
                    errors.append(
                        f".agents/plugins/marketplace.json: plugins[{index}] source "
                        f"path '{path}' does not exist"
                    )
    return errors


def validate_reviewer_panel(root: Path = ROOT) -> list[str]:
    """Validate the single registry and its two runtime representations."""
    errors: list[str] = []
    registry = root / "skills" / "reviewer-panel" / "reviewers"
    module = root / "skills" / "reviewer-panel" / "reviewer_plan.py"
    skill = root / "skills" / "reviewer-panel" / "SKILL.md"
    if not module.is_file() or not skill.is_file():
        return ["skills/reviewer-panel: registry adapter resources are incomplete"]
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("sdd_reviewer_plan", module)
        if spec is None or spec.loader is None:
            raise ValueError("cannot load reviewer_plan.py")
        loaded = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = loaded
        spec.loader.exec_module(loaded)
        definitions = loaded.load_registry(registry)
    except Exception as error:  # validator reports a deterministic contract error
        return [f"skills/reviewer-panel: invalid registry: {error}"]
    expected = {definition.reviewer_id for definition in definitions}
    runtime_ids = sorted(path.stem for path in (root / "agents").glob("sdd-*.md"))
    if set(runtime_ids) != expected:
        errors.append("agents: Claude reviewer representations do not match the registry exactly")
    for reviewer_id in expected:
        path = root / "agents" / f"{reviewer_id}.md"
        if not path.is_file():
            errors.append(f"agents/{reviewer_id}.md: missing Claude compatibility adapter")
            continue
        content = path.read_text(encoding="utf-8")
        definition = next(d for d in definitions if d.reviewer_id == reviewer_id)
        lens_marker = definition.lens.lower()
        criteria_marker = f"Canonical criteria: {definition.criteria}"
        if (f"name: {reviewer_id}" not in content or "Read-only" not in content
                or lens_marker not in content.lower()
                or criteria_marker not in content
                or not all(reference.split("/")[-1] in content for reference in definition.referents[:3])):
            errors.append(f"agents/{reviewer_id}.md: identity/read-only contract drift")
    if not (root / "skills" / "reviewer-panel" / "reviewers").is_dir():
        errors.append("skills/reviewer-panel/reviewers: packaged registry is missing")
    return errors


def parse_frontmatter(
    path: Path, root: Path, errors: list[str]
) -> dict[str, str]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as error:
        errors.append(f"{path.relative_to(root)}: cannot read: {error}")
        return {}
    match = FRONTMATTER_RE.match(content)
    if not match:
        errors.append(f"{path.relative_to(root)}: missing YAML-style frontmatter")
        return {}
    data: dict[str, str] = {}
    for line in match.group("body").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            errors.append(f"{path.relative_to(root)}: invalid frontmatter line '{line}'")
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key in data:
            errors.append(f"{path.relative_to(root)}: duplicate frontmatter key '{key}'")
        data[key] = value.strip()
    return data


def validate_skills(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    skills_root = root / "skills"
    skill_files = sorted(skills_root.glob("*/SKILL.md"))
    names: list[str] = []
    for skill_file in skill_files:
        data = parse_frontmatter(skill_file, root, errors)
        name = data.get("name", "")
        names.append(name)
        if not name:
            errors.append(f"{skill_file.relative_to(root)}: name is required")
        elif name != skill_file.parent.name:
            errors.append(
                f"{skill_file.relative_to(root)}: name '{name}' must match directory"
            )
        if not data.get("description"):
            errors.append(f"{skill_file.relative_to(root)}: description is required")
        content = skill_file.read_text(encoding="utf-8")
        for reference in PLUGIN_REFERENCE_RE.findall(content):
            target = root / reference.rstrip(".,;:)")
            if not target.exists():
                errors.append(
                    f"{skill_file.relative_to(root)}: missing plugin reference '{reference}'"
                )

    if len(names) != len(set(names)):
        errors.append("skills: frontmatter names must be unique")
    documented = set(COMMAND_RE.findall((root / "rules.md").read_text(encoding="utf-8")))
    present = {path.parent.name for path in skill_files}
    missing = sorted(documented - present)
    if missing:
        errors.append(f"skills: rules.md references missing skills: {', '.join(missing)}")
    return errors


def validate_project_boundary(root: Path = ROOT) -> list[str]:
    """Validate the static boundary between plugin assets and consumer assets."""
    errors: list[str] = []
    init = root / "skills" / "init" / "SKILL.md"
    init_text = init.read_text(encoding="utf-8")
    if "Never copy the toolkit's tests" not in init_text:
        errors.append("skills/init/SKILL.md: must state that toolkit tests are not copied")
    if "If no stack or command is identifiable, leave it pending and ask." not in init_text:
        errors.append("skills/init/SKILL.md: must require conservative stack detection")
    rules = (root / "rules.md").read_text(encoding="utf-8")
    if "Project validation is project-owned" not in rules:
        errors.append("rules.md: must keep product validation commands project-owned")

    template_files = sorted((root / "templates").rglob("*.md"))
    forbidden_consumer_artifacts = (
        ".github/workflows/validate-toolkit.yml",
        "scripts/validate_toolkit.py",
        "pytest.ini",
        "requirements.txt",
        "pyproject.toml",
    )
    for template in template_files:
        content = template.read_text(encoding="utf-8")
        for artifact in forbidden_consumer_artifacts:
            if artifact in content:
                errors.append(
                    f"{template.relative_to(root)}: references toolkit-only artifact {artifact}"
                )
        if template.parent.name == "steering" and STACK_COMMAND_RE.search(content):
            errors.append(
                f"{template.relative_to(root)}: contains a hardcoded stack command"
            )

    plugin_only = (
        root / "tests",
        root / ".github" / "workflows" / "validate-toolkit.yml",
        root / "scripts" / "validate_toolkit.py",
    )
    for path in plugin_only:
        if not path.exists():
            errors.append(f"plugin-only asset is missing: {path.relative_to(root)}")

    readme = (root / "README.md").read_text(encoding="utf-8")
    required = (
        "La suite de este repositorio especifica y valida",
        "No se copian al proyecto",
        "pytest",
        "npm test",
        "go test ./...",
    )
    for phrase in required:
        if phrase not in readme:
            errors.append(f"README.md: missing technology-neutrality statement {phrase!r}")
    return errors


def snapshot(path: Path) -> dict[str, bytes]:
    return {
        item.relative_to(path).as_posix(): item.read_bytes()
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }


def load_expectations() -> dict[str, dict[str, Any]]:
    data = json.loads(EXPECTATIONS.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("fixture expectations must be an object")
    return data


def run_doctor(fixture: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "sdd-doctor.py"),
            "--root",
            str(fixture),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def fixture_contract_errors() -> list[str]:
    errors: list[str] = []
    try:
        expectations = load_expectations()
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return [f"tests/fixture_expectations.json: {error}"]
    fixture_names = {path.name for path in FIXTURES.iterdir() if path.is_dir()}
    expected_names = set(expectations)
    if fixture_names != expected_names:
        missing = sorted(fixture_names - expected_names)
        stale = sorted(expected_names - fixture_names)
        if missing:
            errors.append(f"fixtures without expectations: {', '.join(missing)}")
        if stale:
            errors.append(f"expectations without fixtures: {', '.join(stale)}")

    for name in sorted(fixture_names & expected_names):
        fixture = FIXTURES / name
        before = snapshot(fixture)
        first = run_doctor(fixture)
        second = run_doctor(fixture)
        after = snapshot(fixture)
        expectation = expectations[name]
        if before != after:
            errors.append(f"{name}: doctor modified the fixture")
        if first.stdout != second.stdout or first.returncode != second.returncode:
            errors.append(f"{name}: doctor output is not deterministic")
        if first.stderr or second.stderr:
            errors.append(f"{name}: doctor wrote to stderr")
        if first.returncode != expectation.get("exit_code"):
            errors.append(
                f"{name}: expected exit {expectation.get('exit_code')}, "
                f"got {first.returncode}"
            )
        actual = [
            f"{match.group(1)} {match.group(2)}"
            for line in first.stdout.splitlines()
            if (match := DIAGNOSTIC_RE.match(line))
        ]
        diagnostic_lines = [
            line
            for line in first.stdout.splitlines()
            if DIAGNOSTIC_RE.match(line)
        ]
        if any("Suggested action:" not in line for line in diagnostic_lines):
            errors.append(f"{name}: a diagnostic has no suggested action")
        if actual != expectation.get("diagnostics"):
            errors.append(
                f"{name}: expected diagnostics {expectation.get('diagnostics')}, "
                f"got {actual}"
            )
    return errors


# What a consumer actually executes. Touching any of it changes the behaviour a
# user gets, and the installer only offers an update when `version` changes — so
# shipping a change here without a bump publishes it to nobody. That has now
# happened twice (the tag job's own comment records the first time), which is why
# it is a check and not a habit.
DISTRIBUTED_PREFIXES = (
    "skills/",
    "agents/",
    "scripts/",
    "templates/",
    "references/",
    "hooks/",
)
DISTRIBUTED_FILES = ("rules.md",)
# The repository's own CI tooling and fixtures: copied to consumers, never run by
# them, so a change here alters nothing a user experiences. Docs are excluded for
# the same reason — a typo fix should not force a release.
DISTRIBUTION_EXEMPT = ("scripts/validate_toolkit.py",)


def changes_behaviour(path: str) -> bool:
    if path in DISTRIBUTION_EXEMPT:
        return False
    return path in DISTRIBUTED_FILES or path.startswith(DISTRIBUTED_PREFIXES)


def release_guard_errors(changed: list[str], version_changed: bool) -> list[str]:
    """Refuse a change to distributed behaviour that declares no new version.

    Pure on purpose: the rule is unit-tested here, and the workflow only supplies
    the diff and whether `version` moved.
    """
    if version_changed:
        return []
    behaviour = sorted({path for path in changed if changes_behaviour(path)})
    if not behaviour:
        return []
    listed = ", ".join(behaviour[:5]) + (" …" if len(behaviour) > 5 else "")
    return [
        f"{len(behaviour)} distributed file(s) changed with no version bump "
        f"({listed}). Raise `version` in BOTH .claude-plugin/plugin.json and "
        ".codex-plugin/plugin.json in this same change: the installer only offers "
        "an update when the declared version changes, so merging this as-is "
        "publishes it to nobody."
    ]


VALIDATORS = {
    "boundary": validate_project_boundary,
    "manifests": validate_manifests,
    "skills": validate_skills,
    "fixtures": fixture_contract_errors,
    "reviewer-panel": validate_reviewer_panel,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=(*VALIDATORS, "all", "release-guard"))
    parser.add_argument(
        "--changed",
        type=Path,
        help="release-guard: file holding the changed paths, one per line",
    )
    parser.add_argument(
        "--version-changed",
        action="store_true",
        help="release-guard: the declared version differs from the base's",
    )
    args = parser.parse_args(argv)

    if args.target == "release-guard":
        if not args.changed:
            parser.error("release-guard requires --changed")
        paths = [
            line.strip()
            for line in args.changed.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        errors = release_guard_errors(paths, args.version_changed)
        for error in errors:
            print(f"ERROR [release-guard] {error}")
        if not errors:
            print("PASS [release-guard]")
        return 1 if errors else 0

    targets = VALIDATORS if args.target == "all" else {args.target: VALIDATORS[args.target]}
    failed = False
    for name, validator in targets.items():
        errors = validator()
        if errors:
            failed = True
            for error in errors:
                print(f"ERROR [{name}] {error}")
        else:
            print(f"PASS [{name}]")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
