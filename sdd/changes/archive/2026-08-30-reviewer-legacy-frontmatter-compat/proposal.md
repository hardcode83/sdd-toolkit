# Proposal: reviewer-legacy-frontmatter-compat

## Why

La versión 0.40.0 introdujo una regresión en `skills/reviewer-panel/reviewer_plan.py`: `_parse_project()` solo acepta `name`, `phases` y `applies_to`, aunque el template y la guía todavía indican crear reviewers de proyecto con `description`, `model` y `tools`. Como consecuencia, reviewers válidos de `.claude/agents/sdd-review-*.md` se normalizan como `unavailable` en Codex y el panel falla cerrado. El design archivado `codex-reviewer-parity` promete compatibilidad con esos reviewers legacy sin exigir migración inmediata, por lo que el parser debe volver a aceptar ambos contratos.

## What changes

Restaurar la compatibilidad backward-compatible del parser de reviewers de proyecto. El formato aceptado incluirá el frontmatter legacy (`name`, `description`, `model`, `tools`) y el formato nuevo (`name`, `phases`, `applies_to`), con combinaciones válidas de ambos. La normalización compartida conservará el cuerpo, identidad y alcance del reviewer para Codex, tratará `model` y `tools` como declaraciones propias de Claude sin convertirlas en permisos o selección de modelo de Codex, y mantendrá el contrato toolkit-owned de solo lectura. Los reviewers realmente inválidos seguirán siendo `unavailable` y no podrán producir un PASS ni ocultar otros reviewers.

## Requirements

### R1 — Aceptar ambos formatos de frontmatter

**As a** mantenedor de un proyecto con reviewers existentes, **I want** que el panel reconozca tanto el frontmatter legacy como el nuevo, **so that** no tenga que migrar `.claude/agents` para actualizar el toolkit.

Acceptance criteria:

1. WHEN un archivo repository-local `sdd-review-*.md` contiene `name`, `description`, `model` y `tools` con el contrato legacy documentado, THE SYSTEM SHALL normalizarlo como reviewer de proyecto disponible.
2. WHEN un archivo repository-local contiene `name`, `phases` y `applies_to` con el contrato nuevo, THE SYSTEM SHALL normalizarlo como reviewer de proyecto disponible.
3. WHEN un archivo combina campos legacy y nuevos válidos, THE SYSTEM SHALL aceptarlo sin exigir la presencia de campos del otro formato.
4. WHEN un reviewer legacy no declara `phases` o `applies_to`, THE SYSTEM SHALL conservarlo como candidato runnable con la semántica fail-safe existente, en vez de clasificarlo como `unavailable` únicamente por la ausencia de metadata nueva.

### R2 — Normalización sin alterar la semántica de Claude

**As a** usuario de Claude Code o MiniMax-through-Claude, **I want** que `model` y `tools` sigan siendo declaraciones del agente Claude, **so that** la corrección para Codex no cambie cómo Claude ejecuta el reviewer.

Acceptance criteria:

1. WHEN Claude dispatches a legacy project reviewer, THE SYSTEM SHALL preserve its `description`, `model`, `tools`, `name` and Markdown body for the existing Claude agent path.
2. WHEN Codex normalizes the same reviewer, THE SYSTEM SHALL reuse its identity, lens/body and project scope while applying the toolkit-owned read-only, identity, result and evidence contract.
3. THE SYSTEM SHALL NOT reinterpret a legacy `model` as Codex model selection or a legacy `tools` declaration as permission to widen Codex capabilities.

### R3 — Mantener descubrimiento y criterios del reviewer

**As a** mantenedor de un proyecto, **I want** que la compatibilidad abarque los reviewers publicados por el template, **so that** sus criterios sigan siendo efectivos después de la normalización.

Acceptance criteria:

1. WHEN a valid legacy reviewer is discovered, THE SYSTEM SHALL retain its complete Markdown body as the project-owned reviewer criteria/context.
2. WHEN the filename and `name` satisfy the existing reviewer convention, THE SYSTEM SHALL retain the stable reviewer identity and repository-relative referent used by the logical plan.
3. THE SYSTEM SHALL continue discovering project reviewers additively alongside `sdd-architect`, `sdd-security` and `sdd-qa`, without requiring copied Codex agents or project migration.

### R4 — Preservar fail-closed para entradas realmente inválidas

**As** mantenedor del toolkit, **I want** ampliar únicamente el contrato documentado, **so that** la compatibilidad no relaje las barreras de seguridad ni de certificación.

Acceptance criteria:

1. WHEN a reviewer has malformed frontmatter, duplicate/unsupported fields outside the accepted legacy or new sets, invalid required identity, unsafe path, symlink, filename/name mismatch, or unreadable content, THE SYSTEM SHALL mark it `unavailable` and SHALL NOT treat it as skipped or passing.
2. WHEN a normalized reviewer is `unavailable`, THE SYSTEM SHALL preserve unaffected reviewers in the plan and THE SYSTEM SHALL prevent the panel from producing `PASS`.
3. WHEN applicability metadata is present but malformed, unsupported or unevaluable, THE SYSTEM SHALL retain the existing `UNKNOWN`/runnable behavior; only definitive `NO MATCH` SHALL be skippable.

### R5 — Regresión y documentación del contrato

**As a** mantenedor del toolkit, **I want** executable coverage and aligned user-facing guidance, **so that** future parser changes cannot reintroduce this regression.

Acceptance criteria:

1. THE SYSTEM SHALL provide deterministic tests for legacy-only, new-only, mixed, malformed and fail-closed reviewer fixtures, including assertions for preserved body, identity, applicability and panel gate behavior.
2. THE SYSTEM SHALL document that `description`, `model` and `tools` remain accepted for Claude project reviewers and that `phases`/`applies_to` are optional compatibility metadata for the shared planner.
3. THE SYSTEM SHALL preserve the existing Claude/Codex parity and read-only boundary tests, with no requirement for paid native model execution.

## Out of scope

- Migrating or rewriting existing consumer `.claude/agents` files.
- Removing, renaming or deprecating `description`, `model` or `tools` from Claude agent frontmatter.
- Treating Claude `model`/`tools` as Codex configuration, granting broader Codex permissions, or adding a provider framework.
- Weakening the panel's fail-closed result validation, mandatory core reviewers, lifecycle gates, or `solo` semantics.
- New reviewer roles, unrelated lifecycle changes, or changes to the archived `codex-reviewer-parity` record itself.

## Affected specs

- `sdd/specs/reviewer-parity.md` — extend the project-reviewer frontmatter compatibility and normalization contract.
- `sdd/specs/ship-and-review-contract.md` — cross-reference only if implementation touches the existing certification boundary; no lifecycle semantics should change.
