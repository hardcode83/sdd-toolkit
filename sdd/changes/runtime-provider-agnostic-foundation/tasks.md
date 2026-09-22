# Tasks: runtime-provider-agnostic-foundation

<!-- Markers, read by /sdd:run and the lifecycle gates (HTML comments, invisible
     when rendered). On a section heading: "hard" makes that section's
     implementer run on the stronger model; "panel: PASS <date> receipt:<id>"
     is written by the panel gate (reviewer_panel.py) when the section's review
     panel passes — never by hand; "panel: skipped — <reason>" records a
     deliberate skip (scaffolding, docs, config). On a task line:
     "manual" marks a task only a human can perform — run leaves it to you and
     it may travel with the PR as a deferred entry; it may sit on any line of
     the task item, not only the checkbox line. -->

## 1. Provider capability profile and alias preflight

- [ ] 1.1 Create `scripts/provider_profile.py` (stdlib only) with `read_claude_code_profile(env)` returning `base_url`, `alias_map` (only aliases whose `ANTHROPIC_DEFAULT_<ALIAS>_MODEL` is set), and `structured_output`/`effort`/`budget_semantics`/`fallback` as `"unknown"` when not determinable — never guessed. [R1]
- [ ] 1.2 Implement `alias_warnings(aliases, env)`: when `ANTHROPIC_BASE_URL` is set, one actionable message per alias in {haiku, sonnet, opus, fable} lacking its `ANTHROPIC_DEFAULT_<ALIAS>_MODEL`; no warnings when BASE_URL is unset; full model names pass through with no warning. [R2]
- [ ] 1.3 Add the CLI entry point: `python3 scripts/provider_profile.py check --aliases sonnet,opus` prints warnings to stderr and exits 1 when any mapping is missing, exits 0 otherwise. [R2]
- [ ] 1.4 Re-implement `provider_warnings` in `scripts/sdd_auto_outcome.py` on top of `alias_warnings`, keeping its existing signature, message shape, and behavior so `tests/test_sdd_auto_outcome.py` passes unchanged. [R2]

## 2. Phase preflight integration

- [ ] 2.1 Add to `skills/run/SKILL.md` (step 1, before the first `Agent` launch): run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/provider_profile.py" check --aliases sonnet,opus`; on exit 1, stop the phase and report the exact missing variable names from stderr. [R2]
- [ ] 2.2 Add the same preflight step to `skills/review/SKILL.md` before the panel launch, identical wording and hard-stop behavior. [R2]
- [ ] 2.3 Add the same preflight step to `skills/auto/SKILL.md` (inline path, before any `Agent` launch; the delegated path is already covered by `sdd_auto_outcome.py`). [R2]

## 3. Environment inheritance regression tests

- [ ] 3.1 Extend `tests/test_sdd_auto_outcome.py`: fake `claude` records its full environment; a test sets `ANTHROPIC_BASE_URL`, a credential variable, `ANTHROPIC_MODEL`, and `ANTHROPIC_DEFAULT_SONNET_MODEL`, runs `sdd_auto_outcome.run`, and asserts all of them reached the executable plus exactly `SDD_AUTO_DELEGATED=1` and `SDD_AUTO=1` added on top of the parent environment. [R3]
- [ ] 3.2 In the same module, assert `delegated_environment` adds only the two SDD guards to a supplied base environment and mutates nothing else. [R3]

## 4. Reviewer dispatch regression tests

- [ ] 4.1 Create `tests/test_reviewer_dispatch_regression.py` with the correct arm: a fake launcher returns one caller-bound envelope per planned reviewer (`invocation_id`, `planned_reviewer_id` = the launched identity, `payload`) to `reviewer_plan.dispatch_claude_panel`; assert panel PASS; then run the `reviewer_panel.py` gate over those envelopes against a fixture scope and assert a receipt is written; assert `sdd_lifecycle.ensure_panel_receipt` accepts it. [R4]
- [ ] 4.2 Failure arm, variant "background return": a fake launcher returns payloads lacking trusted invocation identity (no `invocation_id` / no `planned_reviewer_id`); assert `dispatch_claude_panel` fails closed with no PASS panel. [R4]
- [ ] 4.3 Failure arm, variant "fork ended without gate": simulate reviewer output existing only as self-declared PASS with the gate never run (no receipt on disk); assert `sdd_lifecycle.ensure_panel_receipt` raises and certification is unreachable — the claimed PASS certifies nothing. [R4]
- [ ] 4.4 Assert the existing doctor check for a hand-written `panel: PASS` annotation without a matching receipt (`SDD032`) flags the symptom of the historical incident, keeping that detection pinned. [R4]

## 5. Documentation: recipes, layer model, Codex configuration surface

- [ ] 5.1 Restructure `references/models.md` into the Anthropic-compatible group (Claude Code runtime × Anthropic/Kimi/MiniMax providers) with an exact env recipe for Kimi (aliases mapped to the Kimi model, BASE_URL, credential variable) alongside the existing MiniMax recipe, each recipe noting the observation date and a verification command. [R5]
- [ ] 5.2 Add the quota-semantics section to `references/models.md`: `--max-budget-usd` does not protect usage-window quotas (Kimi's 5-hour window observed 2026-09); Auto Mode classifier requests on non-Anthropic gateways consume provider quota (observed Claude Code notice via api.kimi.com); no optimization prescribed. [R5]
- [ ] 5.3 Create `references/runtime-provider.md`: the three layers (SDD core / runtime adapter / provider capability) with concrete file classifications; the rule that a new abstraction requires two real implementations; the profile schema with `unknown` semantics; configuration acquisition as runtime-specific (env-derived implemented for Claude Code only); the standing rule that a runtime unable to guarantee foreground, same-turn, caller-bound reviewer collection is BLOCKED/INCOMPATIBLE for panel certification — never PASS. [R1, R4]
- [ ] 5.4 Add a "Configuration surface" section to `docs/codex.md` stating from evidence what Codex consumes (its own session model configuration; the `shell_environment_policy.set` block from `codex-adapter-install.sh`) and that `ANTHROPIC_*` variables and tier aliases are not Codex configuration (aliases document intent only). [R5]

## 6. Release bump and validation

- [ ] 6.1 Bump `version` to 0.54.4 in both `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json` in one commit (repo rule: manifests move together; CI enforces parity). [R1]
- [ ] 6.2 Run `python3 scripts/validate_toolkit.py all` and fix any contract violation it reports (skills, manifests, boundary, fixtures). [R1]

## 7. Verification

- [ ] 7.1 Full test suite passes: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -v`
- [ ] 7.2 Toolkit contracts validate: `python3 scripts/validate_toolkit.py all`

## Implementation Notes

<!-- Append-only, written by the implementer of each section for the next one:
     decisions taken, names chosen, gotchas found. One bullet each, no prose. -->
