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


VALIDATORS = {
    "boundary": validate_project_boundary,
    "manifests": validate_manifests,
    "skills": validate_skills,
    "fixtures": fixture_contract_errors,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=(*VALIDATORS, "all"))
    args = parser.parse_args(argv)
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
