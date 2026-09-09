# Tasks: ui-ux-review-lens

<!-- Sin secciones `<!-- hard -->` (autoría de docs/plantillas + contract tests
     deterministas, sin varianza algorítmica). Sin tareas `<!-- manual -->`:
     todo se verifica con unittest, validate_toolkit y sdd-doctor. El bump de
     versión conjunto de los manifests es una nota de release del design, NO una
     tarea de esta feature. -->

## 1. Referencia metodológica del toolkit <!-- panel: skipped — sección de documentación pura (references/ui-ux-review.md); no toca código de producción ni tests -->

- [x] 1.1 Crear `references/ui-ux-review.md` con la checklist objetiva de las
  doce áreas de R1.3 (layout/spacing/whitespace, jerarquía, tipografía,
  color/contraste/semántica, responsive/mobile, estados
  loading/empty/error/disabled/hover/focus, accesibilidad y teclado,
  consistencia con tokens/componentes, formularios e interacción,
  densidad/legibilidad de tablas y dashboards, patrones genéricos de IA,
  claridad de la acción principal). [R2.1]
- [x] 1.2 Añadir en ese doc una lista de **AI-tells mínimos, objetivos y
  siempre ligados a evidencia observable**, redactada como metodología **propia
  del toolkit** — sin copiar verbatim contenido/listas de skills externas
  (`frontend-design`), sin dependencia runtime externa y sin mencionar `/design`
  ni `/design-sync`. Dejar explícito que el doc es fuente metodológica, **no** un
  referent citable del panel. [R2.2, R5.4, D3]
- [x] 1.3 Verificar que el doc no prescribe ninguna estética de marca concreta
  (Apple, Material, etc.) como norma; el proyecto es autoridad estética. [R2.6]

## 2. Plantilla de steering frontend/design-system <!-- panel: PASS 2026-09-08 receipt:e0dc7d12 -->

- [x] 2.1 Crear `templates/steering/frontend.md` con frontmatter `applies_to` y
  secciones para design tokens, componentes, estados, responsive y
  accesibilidad, más una sección *Design system* (OQ1). Contenido en
  prosa/placeholders. [R2.3, D6]
- [x] 2.2 Incluir un **baseline mínimo de reglas objetivas UI/UX citables**
  (contraste, focus visible, accesibilidad por teclado, tamaño de interaction
  target, estados esenciales, responsive) para que la lente pueda citarlo como
  referente. Sin prescribir estética de marca (R2.6). [R2.3, R5.3]
- [x] 2.3 Mantener la plantilla agnóstica de stack: la sección de testing en
  prosa, **sin** líneas `build:/test:/lint:/run: … python|pytest|npm test|…`
  (no debe disparar `STACK_COMMAND_RE`) ni referencias a artefactos propios del
  toolkit. [R2.4]
- [x] 2.4 Añadir a `tests/test_toolkit_validation.py` un test de que
  `templates/steering/frontend.md` pasa `parse_frontmatter` y **no** dispara
  `STACK_COMMAND_RE` de `scripts/validate_toolkit.py`. [R7.3]

## 3. Plantilla de reviewer UI/UX <!-- panel: PASS 2026-09-08 receipt:1316e87e -->

- [x] 3.1 Crear `templates/reviewer-ui-ux.md` con frontmatter válido (`name:
  sdd-review-ui-ux`, `description`, `model`, `tools`, `phases: [run, review,
  auto]`, `applies_to` de superficie visual de ejemplo) — modelado sobre
  `templates/reviewer-template.md` y `agents/sdd-architect.md`. [R1.1, R1.4]
- [x] 3.2 Declarar el contrato de salida como el envelope JSON del panel
  (`reviewer_id`, `scope_id`, `lens: ui-ux`, `verdict`, `findings`, `evidence`,
  `status`), idéntico en forma al de `agents/sdd-architect.md`. [R1.2]
- [x] 3.3 Enumerar en el cuerpo las doce áreas de comprobación (R1.3). El
  reviewer generado debe ser **autosuficiente** para ejecutar sus doce áreas y
  **no** requerir acceso runtime a `references/ui-ux-review.md` durante el panel:
  ese archivo del toolkit es fuente metodológica para **autorar/mantener** la
  plantilla y puede mencionarse como origen, pero la plantilla no debe depender
  de poder leerlo en ejecución. [R1.3]
- [x] 3.4 Fijar la disciplina *referent-or-discard*: los únicos referentes
  válidos son **regla de steering citada, R# o D#**; un finding sin referente no
  se reporta; los AI-tells solo con evidencia observable; verificar contra el
  steering frontend/design-system y los tokens/componentes reales del repo, no
  contra una estética del toolkit. [R5.1, R5.2, R5.4]
- [x] 3.5 Añadir a `tests/test_toolkit_validation.py` un test de que
  `templates/reviewer-ui-ux.md` pasa la validación de frontmatter. [R7.3]
- [x] 3.6 Añadir a `tests/test_sdd_doctor.py` un test de que un agente
  `.claude/agents/sdd-review-ui-ux.md` generado desde la plantilla **no** dispara
  `SDD028` (trae `phases` y `applies_to`). [R7.4]

## 4. Integración en `/sdd:init` <!-- panel: PASS 2026-09-08 receipt:89f1e28d -->

- [x] 4.1 Extender el bloque «Project reviewers for the panel» de
  `skills/init/SKILL.md` para **nombrar** la lente UI/UX + design-system entre
  las ofertas y apuntar a `templates/reviewer-ui-ux.md`; ofrecer (no imponer).
  [R3.1]
- [x] 4.2 Al aceptar, `/sdd:init` genera `.claude/agents/sdd-review-ui-ux.md`
  desde la plantilla y **garantiza el baseline** del steering
  frontend/design-system (`sdd/steering/frontend.md`, sección *Design system*):
  - si `sdd/steering/frontend.md` **no existe**, crearlo desde
    `templates/steering/frontend.md`;
  - si **ya existe**, **NO** sobrescribirlo;
  - comprobar que contiene el baseline UI/UX objetivo requerido por R2.3/R5.3
    (contraste, focus visible, teclado, interaction target, estados esenciales,
    responsive);
  - si falta total o parcialmente, completarlo de forma **aditiva** preservando
    las reglas existentes del proyecto.
  La mera existencia de `frontend.md` no cuenta como garantía suficiente del
  baseline. [R2.5, R3.2, R3.4]
- [x] 4.3 Derivar `applies_to` de las raíces frontend reales que init ya detecta
  (paso 2); **fail-safe**: si no puede determinarlas de forma fiable, exponer la
  ambigüedad (AskUserQuestion) en vez de generar un `applies_to` amplio/adivinado
  (OQ2). [R3.5]
- [x] 4.4 Reafirmar en el texto de init el solapamiento ya documentado con
  `frontend-design` (`references/plugin-catalog.md:34-37`): genera *distintivo*
  vs verifica *consistencia*, y el steering del proyecto manda. Sin convertir
  `frontend-design` en dependencia. [R3.3]

## 5. Comportamiento del panel con la lente y preservación de invariantes <!-- panel: PASS 2026-09-08 receipt:97e96f07 -->

- [x] 5.1 Añadir a `tests/test_reviewer_plan.py` un test de que un
  `sdd-review-ui-ux.md` con `phases`/`applies_to` de superficie visual da
  `MATCH` en un scope con un archivo frontend (p. ej. `.tsx`) y `NO MATCH`
  (`skipped`) en un scope solo-backend (p. ej. solo `.py`); UNKNOWN sigue
  ejecutando si falta metadata. [R4.1, R4.2, R4.3, R7.1]
- [x] 5.2 Añadir a `tests/test_reviewer_results.py` (o `test_panel_contract.py`)
  un test de que un resultado de la lente unavailable/malformado/fuera-de-scope
  hace `FAIL` el gate con la lente presente en el plan (fail-closed, sin
  substitución inline). [R6.3, R7.2]
- [x] 5.3 Añadir a `tests/test_panel_receipt.py` un test de que un receipt y
  `--carry` funcionan con la lente presente además del core. [R6.4, R7.5]
- [x] 5.4 Verificar por diff que este change **no** modifica
  `skills/reviewer-panel/reviewer_plan.py`, `scripts/reviewer_panel.py`, los tres
  JSON de `skills/reviewer-panel/reviewers/` ni los tres `agents/sdd-*.md` core.
  [R4.4, R6.1]

## 6. Verification

- [x] 6.1 Suite completa en verde: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -v`. [R7]
- [x] 6.2 Contratos del toolkit en verde: `python3 scripts/validate_toolkit.py all` — incluye que el registro core sigue siendo exactamente `sdd-architect`, `sdd-security`, `sdd-qa` y que las plantillas nuevas están bien formadas. [R6.2, R7.3]
- [x] 6.3 `git diff` contra la base confirma que solo cambian los artefactos y `skills/init/SKILL.md` (+ tests), y ninguno de los archivos núcleo de 5.4. [R6.1]

## Implementation Notes

<!-- Append-only, escrito por el implementer de cada sección para el siguiente:
     decisiones, nombres, gotchas. Una viñeta cada uno, sin prosa. -->

- Sección 1: `references/ui-ux-review.md` creado con H1 + secciones `##`/`###`; doce áreas numeradas bajo `## Checklist objetiva — las doce áreas` (área 11 remite a la lista de AI-tells).
- Sección 1: sección `## AI-tells: patrones genéricos de UI generada por IA` — 8 patrones, cada bullet en formato "**Patrón.** Evidencia: …"; usar este mismo formato si 3.x cita ejemplos del reviewer.
- Sección 1: el doc declara explícitamente (sección "Qué es este documento — y qué no es") que NO es referent citable del panel — solo steering/R#/D#; útil para que 3.x/3.4 lo referencien sin duplicar la aclaración.
- Sección 1: única mención a `frontend-design` es para decir que no se copia de ahí (no cuenta como dependencia ni como referencia normativa); no aparece `/design` ni `/design-sync` en ningún lado del doc.
- Sección 1: mención a Apple/Material está en `## Autoridad estética`, explícitamente como ejemplos NO normativos — el proyecto manda.
- Sección 1: `python3 scripts/validate_toolkit.py all` sigue en verde con el nuevo archivo (no se tocó ningún artefacto núcleo).
- Sección 2: `templates/steering/frontend.md` creado modelado sobre `templates/steering/component.md` (frontmatter `applies_to: ["<frontend-path>/**"]`, sin `phases:` — igual que component.md, distinto de product/testing/security/architecture que sí lo usan por ser de proyecto entero).
- Sección 2: orden de secciones = `Design system` (OQ1, autoridad estética del proyecto, no Apple/Material) → `Design tokens` → `Components` → `States` → `Responsive` → `Accessibility` → `Testing`.
- Sección 2: el baseline objetivo (contraste WCAG AA 4.5:1/3:1, focus visible, teclado, interaction target 44x44 CSS px vía WCAG 2.5.5, estados esenciales, breakpoints responsive) va como **texto visible** (bullets en prosa normal, no `<!-- -->`), para que sea citable tal cual una vez el proyecto copie la plantilla; las invitaciones a personalizar (tokens reales, breakpoints reales, umbrales propios) sí van en comentarios `<!-- -->` siguiendo el house style de los demás `templates/steering/*.md`.
- Sección 2: sección `Testing` es 100% prosa descriptiva de *qué* verificar, sin ninguna línea `build:/test:/lint:/typecheck:/run: …` y sin mencionar python/pytest/unittest/pip/npm/go — verificado con `STACK_COMMAND_RE` directamente antes de correr la suite completa.
- Sección 2: test nuevo `test_frontend_steering_template_has_frontmatter_and_no_stack_command` en `tests/test_toolkit_validation.py`, importa `STACK_COMMAND_RE` y `parse_frontmatter` de `scripts/validate_toolkit.py` (ambos ya públicos, no requirió tocar el script).
- Sección 2: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_toolkit_validation -v` → 13 tests OK; `python3 scripts/validate_toolkit.py all` → 5/5 PASS (boundary/manifests/skills/fixtures/reviewer-panel), sin tocar `reviewer_plan.py`/`reviewer_panel.py`/gate/`validate_toolkit.py`.
- Sección 3: `templates/reviewer-ui-ux.md` creado modelado sobre `templates/reviewer-template.md` (estructura: Compatibility → comentario de copia → Referentes → referent-or-discard → doce áreas → AI-tells → Output contract) y `agents/sdd-architect.md` (forma exacta del envelope JSON, incl. `unreached` opcional). Frontmatter ya relleno: `name: sdd-review-ui-ux`, `phases: [run, review, auto]`, `applies_to: ["src/**/*.tsx", "src/**/*.jsx", "src/**/*.vue", "src/**/*.css", "app/**/*.tsx"]` (glob de ejemplo, comentario instruye ajustarlo a las rutas reales del proyecto) — así el agente generado no dispara SDD028 sin que el equipo tenga que rellenar nada primero.
- Sección 3: `references/ui-ux-review.md` se menciona una sola vez como origen metodológico de autoría (nunca como referent ni evidencia); el texto explica que citarlo como `evidence` sería rechazado porque `normalize_reviewer_result` (`skills/reviewer-panel/reviewer_plan.py`) exige evidencia ⊆ `scope.files ∪ scope.referents` — confirmado leyendo esa función, no se tocó.
- Sección 3: sección "Referent-or-discard (mandatory)" declara explícitamente que este template NO amplía el contrato de referent existente del panel (mismo contrato que usan los tres reviewers core): solo regla de steering citada / R# / D#.
- Sección 3: test `test_ui_ux_reviewer_template_has_valid_frontmatter` añadido a `tests/test_toolkit_validation.py::ToolkitStructureTests`, mismo patrón que el test de `frontend.md` (usa `parse_frontmatter` ya importado, sin tocar `validate_toolkit.py`); además comprueba `name == "sdd-review-ui-ux"` y presencia de `description`/`model`/`tools`.
- Sección 3: test `UiUxReviewerTemplateTests.test_generated_agent_does_not_trigger_sdd028` añadido a `tests/test_sdd_doctor.py` — copia el contenido real de `templates/reviewer-ui-ux.md` (no un fixture inventado) a `.claude/agents/sdd-review-ui-ux.md` en un proyecto temporal y verifica que `SDD028` no aparece en `run_doctor`; así el test falla si alguien borra `phases`/`applies_to` de la plantilla real en el futuro.
- Sección 3: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_toolkit_validation tests.test_sdd_doctor -v` → 41 tests OK; `python3 scripts/validate_toolkit.py all` → 5/5 PASS; `agents/` sigue conteniendo exactamente `sdd-architect.md`, `sdd-qa.md`, `sdd-security.md` (la plantilla nueva vive solo en `templates/`, no se tocó el registro core ni `reviewer_plan.py`/`reviewer_panel.py`/`validate_toolkit.py`/`sdd-doctor.py`).
- Sección 4: único archivo tocado: `skills/init/SKILL.md`. Se extendió el bloque «Project reviewers for the panel» (antes ~líneas 119-123) en dos partes: (1) se añadió "UI/UX and design-system consistency…" a la lista de ejemplos de lentes no cubiertas por el core reviewer, junto a performance/i18n/tenancy/accessibility/compliance; (2) se añadió un párrafo nuevo "**UI/UX and design-system lens (specialized offering).**" inmediatamente después de los tres bullets genéricos existentes, con sus propios cuatro bullets (genera desde `templates/reviewer-ui-ux.md`, no desde `templates/reviewer-template.md`; garantiza el baseline de `sdd/steering/frontend.md` creando desde `templates/steering/frontend.md` solo si no existe, y completando de forma aditiva si existe pero le falta baseline; deriva `applies_to` de las raíces frontend de paso 2 con fail-safe `AskUserQuestion` si son ambiguas; reafirma el solape con `frontend-design` citando `references/plugin-catalog.md:34-37` verbatim, sin convertirlo en dependencia).
- Sección 4: la reafirmación del solape con `frontend-design` (4.4) enlaza explícitamente con el punto 6 existente del step 6 de init (que ya menciona `frontend-design` + "the reminder that its steering doc wins over the skill's taste") — se referencia "offered in step 6" en el nuevo párrafo en vez de duplicar la explicación del catálogo.
- Sección 4: no se tocó `reviewer_plan.py`, `reviewer_panel.py`, ningún core reviewer, ningún manifest, ni se introdujo `/design`, `/design-sync`, Playwright o browser MCP; `frontend-design` sigue siendo mención/oferta, nunca dependencia obligatoria.
- Sección 4: `python3 scripts/validate_toolkit.py skills` → PASS [skills]; `python3 scripts/validate_toolkit.py all` → 5/5 PASS (boundary/manifests/skills/fixtures/reviewer-panel).
- Sección 5: solo se tocaron tests, ningún archivo de producción. 5.1 añadido en `tests/test_reviewer_plan.py::ReviewerPlanTests.test_ui_ux_lens_matches_frontend_scope_and_skips_backend_only_scope`: un fixture `.claude/agents/sdd-review-ui-ux.md` con `phases: [run, review, auto]` y `applies_to: ["src/**/*.tsx", "src/**/*.jsx", "src/**/*.vue", "src/**/*.css"]` (glob estilo `templates/reviewer-ui-ux.md`) da `MATCH`/`planned` con scope `["src/components/App.tsx"]` (fnmatch de `src/**/*.tsx` exige un `/` interno tras el prefijo, por eso el fixture usa una subcarpeta, no `src/App.tsx` directo) y `NO MATCH`/`skipped` con scope solo-`.py`; un segundo fixture sin `phases`/`applies_to` da `UNKNOWN`/`planned` (fail-safe) — todo vía `build_reviewer_plan`/`evaluate_applicability` reales, sin tocar `reviewer_plan.py`.
- Sección 5: 5.2 elegido `tests/test_reviewer_results.py` (no `test_panel_contract.py`, que es sobre el contenido de `skills/run/SKILL.md` y `agents/sdd-*.md`, no sobre `evaluate_panel_gate`) — clase nueva `UiUxLensGateTests` con un solo test (`test_unavailable_malformed_and_out_of_scope_lens_result_fails_the_gate`) y 4 `subTest`: unavailable (`synthesize_unavailable_result` ⇒ "reviewer did not pass"), malformed evidence (`evidence: [None]` ⇒ "reviewer evidence entries are malformed"), fuera de scope (`evidence: ["src/other-project/secret.md"]` ⇒ "reviewer evidence is outside scope"), y payload malformado que ni siquiera normaliza (`status: "incomplete"` ⇒ `normalize_reviewer_result` levanta `ValueError`) — la lente está `MATCH`/`planned`/`required=True` en el plan en los 4 casos, nunca sustituida inline por un PASS. Requirió añadir `import tempfile` al archivo (no existía).
- Sección 5: 5.3 en `tests/test_panel_receipt.py`: nueva fixture `UiUxLensReceiptFixture(ReceiptFixture)` que añade `.claude/agents/sdd-review-ui-ux.md` y un archivo `.tsx` real al repo temporal (commit aparte) y sobreescribe `scope()` para incluir ese archivo junto al `.py` existente; dos tests, `UiUxLensReceiptTests` (receipt de un panel PASS incluye `sdd-review-ui-ux` junto a los tres core) y `UiUxLensCarryTests` (`--carry` tras un fix de solo-docs recupera el PASS de `sdd-review-ui-ux` del receipt previo igual que los core, sin volver a lanzarlo) — reutiliza `self.lenses()`/`self.envelope()`/`self.run_panel()` ya existentes en el archivo, sin duplicarlos.
- Sección 5: 5.4 — `git diff HEAD --stat` + `git status --porcelain` confirman que solo cambiaron `skills/init/SKILL.md`, `tests/test_panel_receipt.py`, `tests/test_reviewer_plan.py`, `tests/test_reviewer_results.py`, `tests/test_sdd_doctor.py`, `tests/test_toolkit_validation.py` (modificados) más `references/ui-ux-review.md`, `templates/reviewer-ui-ux.md`, `templates/steering/frontend.md`, `sdd/changes/ui-ux-review-lens/` (nuevos, de secciones previas); ninguno de `skills/reviewer-panel/reviewer_plan.py`, `scripts/reviewer_panel.py`, los tres JSON de `skills/reviewer-panel/reviewers/`, ni `agents/sdd-architect.md`/`agents/sdd-qa.md`/`agents/sdd-security.md` aparece — sin BLOCKER.
- Sección 5: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_reviewer_plan tests.test_reviewer_results tests.test_panel_contract tests.test_panel_receipt -v` → 47 tests OK; `python3 scripts/validate_toolkit.py all` → 5/5 PASS (boundary/manifests/skills/fixtures/reviewer-panel).
- Revisión (feature, 2026-09-09): el panel de `/sdd:review` a escala feature aceptó dos findings y se remediaron (supersede las notas de sección 3 y 5 de arriba, que describen la implementación original del 2026-09-08). (1) QA/medium sobre `applies_to`: el ejemplo `["src/**/*.tsx", …, "app/**/*.tsx"]` usaba `fnmatch`, donde `*` ya cruza `/`, así que la forma `**/` exige un separador extra y hacía NO MATCH silencioso a archivos poco profundos como `app/page.tsx`/`app/layout.tsx` (entrypoints canónicos de Next.js App Router). Corregido a la lista de D4: `["**/*.tsx", "**/*.jsx", "**/*.vue", "**/*.svelte", "**/*.css", "**/*.scss", "components/**", "app/**"]` en `templates/reviewer-ui-ux.md` (con nota sobre la semántica de `fnmatch` en el comentario de copia); los fixtures de `tests/test_reviewer_plan.py`/`test_reviewer_results.py`/`test_panel_receipt.py` se alinearon a esa lista y `test_ui_ux_lens_matches_frontend_scope_and_skips_backend_only_scope` ahora asevera MATCH sobre `app/page.tsx`/`app/layout.tsx` como guardia de regresión. Esto significa que la nota de sección 5 «solo se tocaron tests, ningún archivo de producción» ya no rige: la corrección también tocó la plantilla de producción. (2) Security/low sobre el contrato de referent: la rama «sin steering» de la plantilla autorizaba findings «objetivos con evidencia» que no pueden llenar el campo `referent` obligatorio; reconciliado hacia el contrato cerrado (regla de steering / R# / D#, D2) — init garantiza el steering (R2.5/R5.3), y sin regla/R#/D# citable no se reporta; no se añade categoría de referent. Cubierto por el receipt de revisión a nivel feature (sha `df19ccb`, receipt `33f54c58`, gate PASS con los tres core), no por los receipts por sección.
