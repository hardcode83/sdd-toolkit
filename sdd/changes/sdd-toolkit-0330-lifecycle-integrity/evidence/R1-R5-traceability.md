# R1–R5 traceability

Evidence is recorded against the Toolkit source checkout, not AgentsLabs.

| Requirement | Design/tasks | Implementation | Tests and command | Expected evidence |
|---|---|---|---|---|
| R1 stable anchor | D1; 1.1–1.3; 2.1–2.3; 4.1 | `scripts/sdd_lifecycle.py`: `lifecycle_commit`, `mark_local_verified`, `mark_ready`, `record_pr`, `classify_lifecycle_commit` | `pytest -q tests/test_sdd_lifecycle.py -k 'mark_ready_commits or record_pr_commits or lifecycle'` | ACTIVE→LOCAL_VERIFIED and later lifecycle commits preserve the implementation anchor and contain no self-SHA. |
| R2 clean worktree | D2/D5; 1.2; 2.2; 4.2; 5.1–5.2 | `ensure_clean_or_only_expected_state`; `validate_ship_suffix`; review/ship docs | `pytest -q tests/test_sdd_lifecycle.py -k 'dirty or preexisting or commit_failure'` | Dirty/staged unrelated paths and metrics block handoff; helper rollback preserves user bytes/index. |
| R3 ship/record contract | D3/D4; 3.1–3.5; 4.1–4.4 | `validate_ship_suffix` CLI; `skills/ship/SKILL.md`; `record_pr` | `pytest -q tests/test_sdd_lifecycle.py tests/test_lifecycle_contract.py` | Every post-anchor commit is classified; record-pr creates STATE-only metadata and does not invoke push; nominal final push publishes PR_OPEN. |
| R4 adversarial regression | D6; 2.2–2.3; 3.5; 4.4; 5.2 | Temporary Git repositories in `tests/test_sdd_lifecycle.py` | `pytest -q tests/test_sdd_lifecycle.py tests/test_lifecycle_contract.py` | 65 tests and 37 subtests passed during implementation. |
| R5 scope/auditability | D6; 5.3–5.4 | `README.md`, `docs/guide.md`, this evidence file | `git diff --check`; `git status --short`; `git diff --name-only` | Modified paths are Toolkit scripts, skills, tests, docs and this change only; no AgentsLabs/P2/P3/archive paths. |

## Verification record

- Source worktree: `/private/tmp/sdd-toolkit-0330-lifecycle-integrity`
- Branch: `sdd/sdd-toolkit-0330-lifecycle-integrity`
- Baseline: `a9434a30daf7f16117f89a76315c13771c52fd66`
- `pytest -q` baseline: exit `0`, 230 passed, 63 subtests passed.
- Focused lifecycle suite during implementation: rerun required after this corrective change.
- `scripts/sdd_ship.py`: intentionally not created; the real gate remains in `scripts/sdd_lifecycle.py` and `skills/ship/SKILL.md`.
