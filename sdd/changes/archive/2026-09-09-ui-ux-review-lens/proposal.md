# Proposal: ui-ux-review-lens

## Why

El panel de revisión SDD tiene tres core reviewers (`sdd-architect`,
`sdd-security`, `sdd-qa`) que cubren arquitectura, seguridad y QA/EARS, pero
ninguna lente evalúa la **calidad de la superficie visual** de un frontend
(layout, jerarquía, tipografía, contraste, estados, accesibilidad,
consistencia con el design system). Hoy un change con pantalla nueva pasa el
panel sin que nadie verifique su UI/UX contra las reglas del proyecto.

La auditoría del toolkit 0.53.0 (realizada en esta sesión) concluyó que esto
**no** debe ser un cuarto core reviewer: `load_registry`
(`skills/reviewer-panel/reviewer_plan.py:139-140`) y `validate_toolkit.py:178`
exigen que el registro core contenga *exactamente* los tres roles, y el core
es siempre `MATCH` (`evaluate_applicability:147-148`), por lo que correría en
changes backend/infra sin superficie visual. El mecanismo correcto ya existe:
los **project reviewers** aditivos que el panel descubre en
`.claude/agents/sdd-review-*.md` (`reviewer_plan.py:230-237`), filtrados por
`phases`/`applies_to` (MATCH/NO MATCH), que `/sdd:init` ya sabe ofrecer para
lentes no cubiertas por el core (`skills/init/SKILL.md:119-122`, que nombra
explícitamente *accessibility*).

## What changes

Después de este change el toolkit envía una **lente UI/UX de primera clase**
como project reviewer, sin tocar el núcleo del panel. Concretamente aparecen:
una plantilla de reviewer especializada (`templates/reviewer-ui-ux.md`), una
fuente metodológica/objetiva del toolkit (`references/ui-ux-review.md`) y una
plantilla de steering frontend/design-system en `templates/steering/`, e
integración en `/sdd:init` para que **proponga y genere**
`.claude/agents/sdd-review-ui-ux.md` + el steering del proyecto cuando detecte
superficie frontend. La lente hace `MATCH` solo en
changes con archivos visuales y se registra como `skipped` (NO MATCH) en
backend/infra puro, por lo que no añade coste donde no aporta. `reviewer_plan.py`,
`reviewer_panel.py`, los tres JSON/markdown core y el closed-world gate quedan
intactos. La inspección visual de una app en ejecución (Playwright, browser MCP,
screenshots) queda **fuera de scope**, como posible change posterior una vez la
lente estática esté demostrada.

## Requirements

### R1 — Plantilla de reviewer UI/UX de primera clase

**As a** equipo con frontend, **I want** una plantilla de reviewer UI/UX que el
toolkit envíe y `/sdd:init` materialice como project reviewer, **so that** el
panel gane una lente visual sin que cada proyecto la escriba desde cero ni el
toolkit toque su núcleo.

Acceptance criteria:

1. WHEN el toolkit se valida, THE SYSTEM SHALL incluir `templates/reviewer-ui-ux.md`
   con frontmatter válido (`name`, `description`, `model`, `tools`, `phases`,
   `applies_to`) que pase `parse_frontmatter` de `scripts/validate_toolkit.py`.
2. WHEN un mantenedor lee la plantilla, THE SYSTEM SHALL declarar el contrato de
   salida como el envelope JSON del panel (`reviewer_id`, `scope_id`, `lens`,
   `verdict`, `findings`, `evidence`, `status`) idéntico en forma al de
   `agents/sdd-architect.md`, con `lens: ui-ux`.
3. THE SYSTEM SHALL enumerar en la plantilla las doce áreas de comprobación:
   layout/spacing/whitespace; jerarquía visual; tipografía; color, contraste y
   semántica; responsive/mobile; estados loading/empty/error/disabled/hover/focus;
   accesibilidad y navegación por teclado; consistencia con design tokens y
   componentes existentes; formularios e interacción; densidad y legibilidad de
   tablas/dashboards; patrones genéricos de UI generada por IA; y claridad de la
   acción principal y usabilidad.
4. THE SYSTEM SHALL traer en la plantilla, ya rellenos, `phases: [run, review, auto]`
   y un `applies_to` de superficie visual de ejemplo, de modo que un agente
   generado a partir de ella **no** dispare `SDD028` (`scripts/sdd-doctor.py:489-506`).

### R2 — Fuente metodológica del toolkit y steering del proyecto

**As a** reviewer UI/UX, **I want** una fuente metodológica/objetiva mantenida
en el toolkit y una plantilla de steering frontend/design-system, **so that** el
proyecto tenga siempre un steering propio contra el que la lente pueda citar
referentes, sin depender de plugins externos en runtime.

Acceptance criteria:

1. WHEN el toolkit se valida, THE SYSTEM SHALL incluir `references/ui-ux-review.md`
   con una checklist objetiva de las áreas de R1.3 y una lista de patrones
   genéricos de UI generada por IA, cada patrón exigiendo evidencia observable.
2. THE SYSTEM SHALL tratar `references/ui-ux-review.md` como fuente
   metodológica/objetiva del toolkit para construir y orientar el steering y el
   reviewer, y NO como una categoría de referent del panel; este change no
   requiere modificar el contrato de referent de `/sdd:run` / `/sdd:review` ni
   `reviewer_plan.py` / `reviewer_panel.py`.
3. WHEN el toolkit se valida, THE SYSTEM SHALL incluir una plantilla de steering
   frontend/design-system en `templates/steering/` con secciones para design
   tokens, componentes, estados, responsive y accesibilidad, con frontmatter
   `applies_to`, y con un **baseline mínimo de reglas objetivas UI/UX citables**
   —contraste, focus visible, accesibilidad por teclado, tamaño de interaction
   target, estados esenciales y responsive— construido y orientado a partir de
   `references/ui-ux-review.md`.
4. THE SYSTEM SHALL mantener la plantilla de steering agnóstica de stack: no
   contendrá ningún comando de stack hardcodeado (debe pasar la comprobación
   `STACK_COMMAND_RE` de `scripts/validate_toolkit.py:288-291`) ni referenciar
   artefactos propios del toolkit.
5. WHEN `/sdd:init` materializa la lente UI/UX, THE SYSTEM SHALL garantizar que
   existe un steering frontend/design-system del proyecto —creándolo desde la
   plantilla si no existe—, de modo que los findings operativos puedan citar ese
   steering, R# o D# como referente.
6. THE SYSTEM SHALL NOT prescribir Apple, Material ni ninguna otra estética de
   marca concreta como estándar UI/UX normativo. El steering del proyecto SHALL
   permanecer como autoridad sobre las decisiones estéticas.

### R3 — Activación selectiva vía `/sdd:init`

**As a** persona que inicializa SDD en un proyecto con frontend, **I want** que
`/sdd:init` proponga la lente UI/UX y la genere si acepto, **so that** el equipo
la reciba versionada en el repo sin conocer la convención de nombres del panel.

Acceptance criteria:

1. WHEN `/sdd:init` detecta una superficie frontend/design-system relevante,
   THE SYSTEM SHALL ofrecer (no imponer) crear la lente UI/UX como una de las
   lentes de proyecto de `skills/init/SKILL.md:119-122`.
2. IF la persona acepta, THEN THE SYSTEM SHALL generar `.claude/agents/sdd-review-ui-ux.md`
   a partir de `templates/reviewer-ui-ux.md` y crear el steering frontend/design-system
   si no existe, con `applies_to` derivado de las carpetas frontend reales del
   repo (no una lista fija).
3. WHEN `/sdd:init` ofrece la lente junto al plugin `frontend-design`,
   THE SYSTEM SHALL reafirmar el solapamiento documentado en
   `references/plugin-catalog.md:34-37`: `frontend-design` empuja a lo
   *distintivo* y la lente verifica *consistencia*, y el steering del proyecto
   manda sobre la taste del plugin.
4. WHEN `/sdd:init` genera el agente, THE SYSTEM SHALL producir un archivo cuyo
   frontmatter incluya `phases` y `applies_to` de modo que `/sdd:doctor` no
   reporte `SDD028` sobre él.
5. IF `/sdd:init` no puede determinar de forma fiable las raíces visuales de
   frontend, THEN THE SYSTEM SHALL exponer la ambigüedad en vez de generar en
   silencio un `applies_to` amplio, adivinado o engañoso.

### R4 — MATCH solo en superficie visual, sin modificar el planner

**As a** orquestador de `/sdd:run` y `/sdd:review`, **I want** que la lente
corra únicamente cuando el scope toca archivos visuales, **so that** los changes
puramente backend/infra no paguen su coste.

Acceptance criteria:

1. WHEN el scope de una sección o feature incluye al menos un archivo que casa el
   `applies_to` de la lente, THE SYSTEM SHALL planificar la lente como `MATCH` y
   ejecutarla (`build_reviewer_plan`/`evaluate_applicability` sin cambios).
2. WHEN el scope no incluye ningún archivo que case el `applies_to` de la lente,
   THE SYSTEM SHALL registrar la lente como `skipped` por NO MATCH definitivo,
   nunca omitirla de forma silenciosa.
3. WHILE la lente carezca de `phases` o `applies_to` evaluables (metadata
   ausente o ambigua), THE SYSTEM SHALL tratarla como `UNKNOWN` y ejecutarla
   (fail-safe), preservando la semántica actual del planner.
4. THE SYSTEM SHALL lograr lo anterior sin editar `skills/reviewer-panel/reviewer_plan.py`
   ni `scripts/reviewer_panel.py`.

### R5 — Findings objetivos, accionables y con referente; sin estética impuesta

**As a** persona que recibe el veredicto del panel, **I want** que cada finding
UI/UX cite un referente y describa un fallo objetivo con una dirección de
arreglo, **so that** el resultado sea accionable y no una opinión de gusto.

Acceptance criteria:

1. THE SYSTEM SHALL instruir en la plantilla la disciplina *referent-or-discard*:
   un finding sin referente no debe reportarse. Los únicos referentes operativos
   válidos del panel son una regla de steering citada, un R# o un D#; una fuente
   metodológica del toolkit como `references/ui-ux-review.md` NO es por sí misma
   un referent del panel. Este change no amplía el contrato de referent existente.
2. WHEN el proyecto tiene steering frontend/design-system, THE SYSTEM SHALL hacer
   que la lente verifique contra ese steering y los tokens/componentes reales del
   repo, citando la regla de steering (o un R#/D#) como referente, no contra una
   estética del toolkit.
3. IF el proyecto no tenía steering frontend/design-system suficiente, THEN
   THE SYSTEM SHALL apoyarse en el baseline de reglas objetivas del steering que
   `/sdd:init` genera (R2.3, R2.5) como referente citable de la lente; la
   evidencia concreta (p. ej. ratio de contraste, foco no visible, estado
   faltante, componente duplicado en vez de reutilizado) demuestra el
   incumplimiento pero NO sustituye al referent.
4. WHEN la lente reporta un patrón genérico de UI generada por IA, THE SYSTEM
   SHALL exigir evidencia observable en el código o el diseño en scope, nunca una
   afirmación de gusto.

### R6 — Preservación de invariantes del panel

**As a** mantenedor del toolkit, **I want** que este change no debilite el core
ni el closed-world gate, **so that** la garantía fail-closed del panel siga
intacta.

Acceptance criteria:

1. THE SYSTEM SHALL no modificar `skills/reviewer-panel/reviewer_plan.py`,
   `scripts/reviewer_panel.py`, los tres JSON de `skills/reviewer-panel/reviewers/`
   ni los tres `agents/sdd-*.md` core (verificable por `git diff` contra la base).
2. WHEN el toolkit se valida tras el change, THE SYSTEM SHALL mantener que el
   registro core contiene exactamente `sdd-architect`, `sdd-security`, `sdd-qa`
   (`python3 scripts/validate_toolkit.py all` en verde).
3. IF un resultado de la lente es unavailable, malformado o fuera de scope,
   THEN THE SYSTEM SHALL seguir fallando cerrado en el gate existente
   (`evaluate_panel_gate`), sin substitución inline.
4. THE SYSTEM SHALL preservar el comportamiento de receipts y `--carry` cuando la
   lente está presente en el plan.

### R7 — Cobertura de tests del contrato

**As a** mantenedor del toolkit, **I want** tests que fijen el comportamiento de
la lente, **so that** MATCH/NO MATCH, fail-closed y la conformidad de los
artefactos no puedan regresar en silencio.

Acceptance criteria:

1. THE SYSTEM SHALL añadir tests que verifiquen que un `sdd-review-ui-ux.md` con
   `phases` y `applies_to` de superficie visual da `MATCH` en un scope con un
   archivo frontend y `NO MATCH` en un scope solo-backend.
2. THE SYSTEM SHALL añadir un test de que un resultado de la lente
   unavailable/malformado hace `FAIL` el gate con la lente presente en el plan.
3. THE SYSTEM SHALL añadir un test de que `templates/reviewer-ui-ux.md` y la
   plantilla de steering pasan la validación de frontmatter y (para el steering)
   la comprobación de comando-de-stack de `validate_toolkit.py`.
4. THE SYSTEM SHALL añadir un test de que un agente generado desde la plantilla
   no dispara `SDD028` en `sdd-doctor`.
5. THE SYSTEM SHALL añadir un test de que un receipt y `--carry` funcionan con la
   lente presente además del core.

## Out of scope

- **Convertir la lente en un cuarto core reviewer** — rompería el invariante de
  registro y correría en changes sin superficie visual. Permanece como project
  reviewer aditivo.
- **Modificar la semántica de `reviewer_plan.py`, `reviewer_panel.py`, receipts o
  el closed-world gate**, o editar los tres core reviewers.
- **Inspección visual de una aplicación en ejecución**: levantar la app,
  Playwright, browser MCP o análisis de screenshots. Posible change posterior
  (`ui-ux-visual-inspection`) una vez la lente estática esté demostrada; requiere
  resolver que la evidencia de PASS debe estar in-scope (`normalize_reviewer_result`
  exige evidencia ⊆ scope) y que los screenshots vivan fuera del worktree.
- **Hardcodear una estética concreta** (Apple, Material u otra) como norma. El
  referente del toolkit son estándares objetivos; la estética la define el
  steering del proyecto.
- **Requerir el plugin `frontend-design` como dependencia en runtime**. Se puede
  mencionar/ofrecer en `/sdd:init`, nunca exigir.
- **Cambiar los core reviewers para que emitan findings UI/UX.**

## Affected specs

- `sdd/specs/reviewer-parity.md` — su R1/R2 ya documentan project reviewers
  aditivos con `phases`/`applies_to`; puede recibir una nota de que el toolkit
  ahora **envía** una lente UI/UX de primera clase. El contrato de paridad no
  cambia.
- `sdd/specs/ui-ux-review-lens.md` *(no existe aún — se creará al archivar)* —
  documentará la lente enviada por el toolkit: artefactos (plantilla de reviewer,
  reference, steering), la integración de `/sdd:init` y el contrato de findings
  objetivos con referente.
