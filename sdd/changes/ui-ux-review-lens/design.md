# Design: ui-ux-review-lens

## Context

El panel descubre project reviewers en `.claude/agents/sdd-review-*.md`
(`skills/reviewer-panel/reviewer_plan.py:230-237`), los planifica con
`evaluate_applicability` (`:144-162`) y los evalúa con el gate fail-closed
`evaluate_panel_gate` (`:313-354`); `run`/`review` los lanzan aditivamente
(`skills/run/SKILL.md:63-111`, `skills/review/SKILL.md:97-124`). `/sdd:init` ya
ofrece project reviewers para lentes no cubiertas por el core y los genera desde
`templates/reviewer-template.md` (`skills/init/SKILL.md:119-123`). El toolkit se
autovalida con `scripts/validate_toolkit.py` (recorre `templates/**/*.md`,
prohíbe comandos de stack en steering vía `STACK_COMMAND_RE:24-27` y exige que
`agents/*.md` coincidan exactamente con el registro core `:175-192`) y con
`scripts/sdd-doctor.py` (regla `SDD028:489-506` para reviewers sin
`phases`/`applies_to`). Este change añade artefactos y texto de `/sdd:init`
**sin tocar** ese núcleo. Los manifests (`.claude-plugin/plugin.json`,
`.codex-plugin/plugin.json`) son metadata: no enumeran plantillas ni references
(Codex hace glob `"skills": "./skills/"`), así que los artefactos nuevos no
requieren registrarse; solo el bump de versión conjunto en release
(`architecture.md`: "update both plugin manifests together").

## Decisions

### D1 — Lente como project reviewer especializado enviado por el toolkit

**Chosen:** enviar `templates/reviewer-ui-ux.md`, una plantilla de reviewer
**especializada** (contrato JSON del panel, `lens: ui-ux`, las doce áreas de
R1.3, la lista de "AI-tells", `phases`/`applies_to` ya rellenos). `/sdd:init` la
materializa en `.claude/agents/sdd-review-ui-ux.md`. Un único artefacto lo
consumen Claude y Codex (el panel descubre el mismo archivo en ambos runtimes),
respetando el anti-patrón de `architecture.md` contra copias separadas de
metodología. Cumple R1, R3.

Rejected: cuarto core reviewer — rompe el invariante de registro
(`reviewer_plan.py:139-140`, `validate_toolkit.py:178`) y corre en todo change
(R6). Rejected: reutilizar el genérico `templates/reviewer-template.md` — no
fija las doce áreas ni la detección de patrones IA; el valor es justo esa
especialización.

### D2 — El referente operativo es el steering del proyecto; init lo garantiza

**Chosen:** el contrato de referent se mantiene cerrado a **regla de steering /
R# / D#** (proposal R5.1). `/sdd:init`, al materializar la lente, garantiza un
steering frontend/design-system del proyecto —creándolo desde
`templates/steering/frontend.md` (sección *Design system*) si no existe— que trae un **baseline mínimo de
reglas objetivas citables** (contraste, focus visible, accesibilidad por
teclado, interaction target, estados esenciales, responsive). Así la lente
siempre tiene una regla citable, incluso en un proyecto sin steering previo
(R2.3, R2.5, R5.3).

Rejected: aceptar "problema objetivo con evidencia" como categoría de referent —
ampliaría el contrato del panel, expresamente fuera de scope.

### D3 — `references/ui-ux-review.md` es fuente metodológica, nunca referent

**Chosen:** un doc de referencia del toolkit con la checklist objetiva de las
doce áreas y la lista de patrones genéricos de UI generada por IA (cada uno
exigiendo evidencia observable). Lo usan el autor del steering (init) y el
reviewer para **orientarse**, pero no es una ruta citable como evidencia del
panel: la plantilla del reviewer lo dice explícitamente (R2.1, R2.2, R5.1). No
introduce dependencia de plugin en runtime.

`references/ui-ux-review.md`, además:
- destila metodología UI/UX **objetiva propia del toolkit**;
- **no copia verbatim** contenido ni listas de skills externas (p. ej.
  `frontend-design`); evita mantener una copia paralela de su calibración
  (anti-patrón de `architecture.md:33`);
- mantiene únicamente **AI-tells mínimos, objetivos y siempre ligados a
  evidencia** (coherente con R5.4);
- es **completamente independiente de que `frontend-design` esté instalado**;
- **no introduce ninguna dependencia runtime externa**.

Rejected: que el reviewer cite el doc del toolkit como referente — colisiona con
D2 y con `normalize_reviewer_result` (evidencia ⊆ scope).

### D4 — `applies_to` derivado del repo, con fail-safe de ambigüedad en init

**Chosen:** `/sdd:init` deriva los globs de superficie visual de las raíces
frontend que ya detecta en su paso 2 (`skills/init/SKILL.md:35`). La plantilla
trae un `applies_to` de ejemplo (p. ej. `**/*.tsx`, `**/*.jsx`, `**/*.vue`,
`**/*.svelte`, `**/*.css`, `**/*.scss`, `components/**`, `app/**`) que init
**ajusta** a las carpetas reales. Si init no puede determinar de forma fiable
esas raíces, usa `AskUserQuestion` para exponer la ambigüedad en vez de generar
un `applies_to` amplio/adivinado (R3.5, fail-safe). Cumple R3.2, R3.4, R3.5, R4.

Rejected: lista fija de globs — fallaría en layouts no convencionales y dejaría
pasar cambios visuales como NO MATCH silencioso.

### D5 — MATCH/NO MATCH sin tocar el planner

**Chosen:** el comportamiento de R4 lo da el planner **actual** vía la metadata
`phases: [run, review, auto]` + `applies_to` del agente generado: MATCH con
archivo visual en scope, NO MATCH (`skipped` registrado) sin él, UNKNOWN
fail-safe si falta metadata (`evaluate_applicability:144-162`,
`build_reviewer_plan:240-261`). No se edita `reviewer_plan.py` ni
`reviewer_panel.py` (R4.4, R6.1).

Rejected: añadir lógica de detección de "superficie visual" al planner —
innecesario y prohibido por scope.

### D6 — Plantilla de steering agnóstica de stack

**Chosen:** `templates/steering/frontend.md` (con sección *Design system* — OQ1)
con frontmatter `applies_to`, secciones
tokens/componentes/estados/responsive/accesibilidad y el baseline objetivo, en
prosa/placeholders. La sección de testing **no** usará líneas `test: …
pytest|npm test|…` para no disparar `STACK_COMMAND_RE`
(`validate_toolkit.py:24-27,288-291`); describe *qué* verificar, no *con qué
comando*. Cumple R2.3, R2.4.

Rejected: incluir comandos de verificación de ejemplo — falla la validación del
toolkit y viola el boundary plugin/proyecto (regla compartida 9).

### D7 — Integración en `/sdd:init` reutilizando su mecanismo de lentes

**Chosen:** extender el bloque de "Project reviewers for the panel"
(`skills/init/SKILL.md:119-123`) para **nombrar** la lente UI/UX y design-system
entre las ofertas y apuntar a `templates/reviewer-ui-ux.md`; añadir la garantía
del steering (D2) y la reafirmación del solape con `frontend-design`
(consistente > distintivo) que el catálogo ya documenta
(`references/plugin-catalog.md:34-37`; el paso 6 de init ya lo menciona). Cumple
R3.1, R3.3.

Rejected: una skill/slash-command nueva para la lente — el mecanismo de project
reviewers ya existe; añadir superficie sería scope creep.

### D8 — Cobertura de tests mapeada a R7

**Chosen:** tests unittest de librería estándar (convención del repo):
- `tests/test_reviewer_plan.py` — MATCH con scope `.tsx`, NO MATCH con scope
  solo-`.py`, para un `sdd-review-ui-ux.md` con la metadata de la plantilla (R7.1, R4).
- `tests/test_reviewer_results.py` o `test_panel_contract.py` — resultado de la
  lente unavailable/malformado ⇒ gate FAIL con la lente en el plan (R7.2, R6.3).
- `tests/test_toolkit_validation.py` — `reviewer-ui-ux.md` y el steering pasan
  frontmatter; el steering pasa `STACK_COMMAND_RE` (R7.3).
- `tests/test_sdd_doctor.py` — un agente generado desde la plantilla no dispara
  `SDD028` (R7.4).
- `tests/test_panel_receipt.py` — receipt y `--carry` con la lente presente
  además del core (R7.5, R6.4).

Rejected: copiar los tests al proyecto consumidor — prohibido por
`architecture.md`/regla 9; son tests del toolkit.

## Changes by area

| Área | Archivos | Cambio |
|---|---|---|
| Plantilla reviewer | `templates/reviewer-ui-ux.md` *(nuevo)* | Reviewer UI/UX especializado: contrato JSON, `lens: ui-ux`, 12 áreas, AI-tells, `phases`+`applies_to`, disciplina referent-or-discard (R1, R5.1) |
| Referencia toolkit | `references/ui-ux-review.md` *(nuevo)* | Checklist objetiva + patrones IA con evidencia; fuente metodológica, no referent (R2.1, R2.2, D3) |
| Plantilla steering | `templates/steering/frontend.md` *(nuevo)* | Convenciones frontend + sección *Design system*: tokens/componentes/estados/responsive/a11y + baseline objetivo citable; agnóstica de stack (R2.3, R2.4, D6, OQ1) |
| Init | `skills/init/SKILL.md` | Nombrar la lente UI/UX + garantizar steering + reafirmar solape frontend-design + fail-safe de globs (R3) |
| Tests | `tests/test_reviewer_plan.py`, `test_reviewer_results.py`/`test_panel_contract.py`, `test_toolkit_validation.py`, `test_sdd_doctor.py`, `test_panel_receipt.py` | Cobertura de R7 (D8) |
| Release (nota) | `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json` | Bump de versión **conjunto** en release, no en tasks de esta feature (ver Riesgos) |

## Data & interfaces

Ninguna nueva interfaz de código. El "contrato" es documental: el envelope JSON
del panel ya existente (`reviewer_id, scope_id, lens, verdict, findings,
evidence, status`) reutilizado con `lens: ui-ux`, y la metadata de frontmatter
`phases`/`applies_to` que el planner ya consume. Sin cambios de esquema, API,
eventos ni env vars.

## Risks & mitigations

- **Bump de versión de manifests (architecture.md).** Un cambio de comportamiento
  distribuido pide mover ambos manifests juntos. *Mitigación:* el repo bumpea
  versión en un commit de release dedicado (p. ej. `chore(release): bump toolkit
  to 0.53.0`); esta feature no toca los manifests en sus tasks, y el bump
  conjunto se hace en release. Se registra como nota en "Changes by area".
- **`applies_to` incompleto ⇒ NO MATCH silencioso.** *Mitigación:* D4 (derivar
  del repo + fail-safe R3.5). Riesgo residual: globs correctos pero un archivo
  visual en ruta atípica; aceptable, mismo que cualquier project reviewer.
- **Falsos positivos / churn de una lente subjetiva.** *Mitigación:* contrato
  cerrado steering/R#/D# (D2), baseline objetivo, AI-tells solo con evidencia
  (R5.4); el cap de dos rondas de fix de run/review ya acota la iteración.
- **Deriva de `STACK_COMMAND_RE` en el steering.** *Mitigación:* D6 (prosa, sin
  comandos) + test R7.3.

### Future integration (no normativa, fuera de scope actual)

- `/design-sync` podría utilizarse **en el futuro** para ayudar a
  mantener/sincronizar el design-system/steering del proyecto
  (`sdd/steering/frontend.md`) desde un proyecto Design System de claude.ai.
- `/design` (Claude Design canvas) podría ayudar a **autorar** ese design system.
- Ambas capacidades quedan **explícitamente fuera del scope actual** y **nunca
  son dependencia** de `sdd-review-ui-ux`: la lente permanece read-only y
  autónoma. Se anotan aquí solo como posible integración opcional posterior,
  junto al change futuro `ui-ux-visual-inspection` ya previsto.

## Open questions

*(Resueltas en el gate de diseño.)*

- **OQ1 — Nombre del doc de steering → RESUELTO:** `templates/steering/frontend.md`
  con una sección *Design system*. Init reutiliza el nombre existente si el
  proyecto ya tiene un doc frontend. La lente lee ese doc como referente (R2.3,
  R2.5, D6).
- **OQ2 — Confirmación de globs en init → RESUELTO:** init genera los
  `applies_to` sin preguntar cuando las raíces frontend son inequívocas, y solo
  usa `AskUserQuestion` para exponer la ambigüedad cuando no puede determinarlas
  de forma fiable (fail-safe R3.5, D4).
