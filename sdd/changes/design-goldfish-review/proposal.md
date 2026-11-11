# Proposal: design-goldfish-review

## Why

Hoy el panel SDD revisa **código** (por sección en `/sdd:run`, por feature en
`/sdd:review`). El `design.md` solo lo revisa alguien sin contexto en
`/sdd:auto` (paso 3: `sdd-architect` contra `architecture.md`); en `/sdd:design`
interactivo o con aprobación delegada no lo revisa nadie con ojos frescos. Los
defectos de diseño se descubren entonces durante la implementación, que es la
fase más cara: cada uno cuesta un intento del implementador, una ronda de
panel y, a menudo, un `deferred` que bloquea el PASS final.

Evidencia medida (proyecto consumidor AgentsLabs, change
`software-delivery-progress-and-strategy`, 2026-11-04 → 11-11): 12 hallazgos de
paneles y de la review final eran defectos **de diseño** (datos que el diseño
consume y ningún registro lleva, caminos terminales sin el efecto, valores
configurables sin dueño, clasificadores con entradas que caen al default
equivocado). Costaron ~8 rondas de arreglo y el change sigue sin PASS final por
dos de ellos. Una prueba retrospectiva el 2026-11-11 —un revisor de contexto
fresco sobre un snapshot del repo en el commit del diseño, sin acceso a la
conversación ni al código posterior— encontró 5 de los 12 claramente (incluido
uno de los dos bloqueantes), 4 parcialmente, y ~10 defectos adicionales, en
~5 minutos.

La idea procede del patrón "Elephant-Goldfish" (google/elephant-goldfish-model,
Apache-2.0): quien diseña tiene el contexto; quien revisa no lo tiene, y por eso
ve las suposiciones no escritas. Se adopta solo esa idea, como paso del toolkit,
sin depender del plugin externo.

## What changes

- Una metodología canónica de revisión de diseño (`references/design-review.md`)
  compartida por Claude y Codex.
- Un agente Claude de solo lectura que la aplica (`agents/design-goldfish.md`),
  fuera del registro del panel core.
- `/sdd:design` lanza la revisión antes de su gate; `/sdd:auto` la usa como
  sustituto de aprobación del diseño.
- El validador del toolkit comprueba el contrato del agente y la metodología.

## Out of scope

- No es un cuarto core reviewer ni certifica nada: el panel core, su registro
  y su gate fail-closed no cambian.
- No revisa código ni `tasks.md`.
- No se importa ni se instala el plugin externo.

## Requirements (EARS)

### R1 — Metodología canónica única

- R1.1 The toolkit SHALL ship `references/design-review.md` as the single
  methodology for design review, defining five passes: traceability, data
  availability, path completeness, consistency, verifiability & safety.
- R1.2 The methodology SHALL require every finding to cite design/proposal
  lines and the source lines that contradict or fail to support them, with a
  severity (`high|medium|low`), and SHALL end with `VERDICT: PASS` (no high) or
  `VERDICT: REVISE`.
- R1.3 The methodology SHALL restrict the reviewer's inputs to the change's
  `proposal.md`, `design.md`, `BLOCKED.md`, applicable steering/specs and the
  source files they name, and SHALL forbid the reviewer from using any session
  conversation.

### R2 — Adaptador Claude de solo lectura

- R2.1 The toolkit SHALL ship `agents/design-goldfish.md` with `name`,
  `description`, `model`, read-only `tools` and a body that defers to
  `design-review.md` instead of copying it.
- R2.2 The agent SHALL NOT match the core-reviewer glob `agents/sdd-*.md`, so
  the panel registry and its parity contract remain exactly the three core
  reviewers.

### R3 — Integración en /sdd:design

- R3.1 WHEN `/sdd:design` has written `design.md` and the change is not
  trivial, the skill SHALL run one fresh-context design review before the
  gate (Claude: the `design-goldfish` agent; Codex: one native subagent
  instructed with `design-review.md`).
- R3.2 WHEN the review returns `high` findings, the skill SHALL amend
  `design.md` (or surface them as open questions) and MAY re-review at most
  once.
- R3.3 The gate summary SHALL list the review verdict and every unresolved
  finding; IF the runtime cannot spawn a fresh-context reviewer THEN the skill
  SHALL say so in the gate summary and SHALL NOT claim the review ran.

### R4 — Integración en /sdd:auto

- R4.1 WHEN `/sdd:auto` runs the design phase, its approval substitute SHALL
  be the design review of R3 (replacing the `sdd-architect` review of the
  design document), with at most two review rounds; unresolved `high` findings
  with a recommendation → `assumed`, without one → BLOCK.

### R5 — Validación

- R5.1 `scripts/validate_toolkit.py` SHALL fail when the design-review agent
  or methodology is missing, when the agent is not read-only or does not
  reference the methodology, or when the methodology lacks any of the five
  passes or the verdict line.
- R5.2 Both plugin manifests SHALL be bumped together.
