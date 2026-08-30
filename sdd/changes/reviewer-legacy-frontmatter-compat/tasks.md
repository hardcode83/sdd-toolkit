# Tasks: reviewer-legacy-frontmatter-compat

La implementación debe conservar estrictamente D1–D5 del design. En
particular, `model` y `tools` se aceptan en el archivo Claude, pero no se
añaden como campos obligatorios de `ReviewerDefinition` ni se convierten en
capacidades Codex.

## 1. Parser dual de frontmatter <!-- panel: PASS 2026-08-29 -->

- [x] 1.1 Actualizar `_parse_project()` en `skills/reviewer-panel/reviewer_plan.py` para aceptar exactamente la unión documentada de `name`, `description`, `model`, `tools`, `phases` y `applies_to`, conservando `name` obligatorio, detección de duplicados, validaciones de ruta/archivo y parsing actual de metadata nueva; verificarlo con casos legacy-only, new-only y mixed en `tests/test_reviewer_plan.py` [R1, R3, R4]
- [x] 1.2 Añadir o ajustar fixtures temporales en `tests/test_reviewer_plan.py` para demostrar que un reviewer legacy válido se descubre como disponible, conserva el Markdown body completo, mantiene el `reviewer_id` derivado de filename/name y conserva el referent repository-relative; no añadir `model` ni `tools` a `ReviewerDefinition` [R1, R2, R3]

## 2. Aplicabilidad legacy y plan compartido

- [x] 2.1 Cubrir en `tests/test_reviewer_plan.py` que un reviewer legacy sin `phases`/`applies_to` se normaliza, se clasifica como `UNKNOWN` y permanece `planned`, mientras que un reviewer new-only o mixed conserva sus decisiones `MATCH`/`NO MATCH` según la semántica existente [R1, R3, R4]
- [x] 2.2 Verificar en `tests/test_reviewer_plan.py` que los reviewers de proyecto legacy continúan siendo aditivos junto a `sdd-architect`, `sdd-security` y `sdd-qa`, sin cambios en el orden/identidad de los core ni necesidad de migración o configuración Codex del proyecto [R1, R3]

## 3. Separación Claude/Codex

- [x] 3.1 No modificar `skills/reviewer-panel/SKILL.md`, `skills/run/SKILL.md`, `skills/review/SKILL.md` ni `skills/auto/SKILL.md`; verificar mediante los tests de adapters existentes que la ruta de dispatch Claude preserva `description`, `model`, `tools`, `name` y body para Claude/MiniMax-through-Claude [R2]
- [x] 3.2 Añadir cobertura en `tests/test_reviewer_plan.py` y/o los tests de adapter existentes para que el prompt/handoff Codex de un reviewer legacy preserve identity, lens/body y scope, mantenga el wrapper toolkit-owned y no exponga `model`/`tools` como selección de modelo, permisos o capacidades Codex [R2, R3]

## 4. Fail-closed para entradas inválidas

- [x] 4.1 Extender la matriz de fixtures de `tests/test_reviewer_plan.py` para cubrir frontmatter malformado, campos duplicados, campos realmente desconocidos fuera de la unión documentada, identidad inválida, filename/name mismatch, symlink/ruta insegura y contenido ilegible; verificar que cada caso se normaliza como `unavailable` y nunca como `skipped` [R4]
- [x] 4.2 Verificar en `tests/test_reviewer_plan.py` que un reviewer `unavailable` no suprime reviewers core ni otros reviewers de proyecto y que `evaluate_panel_gate()` no puede producir `PASS`; conservar `NO MATCH` como único estado skippable y `UNKNOWN` como runnable [R4]

## 5. Documentación y contrato mantenido

- [x] 5.1 Actualizar `templates/reviewer-template.md`, `docs/guide.md` y `docs/codex.md` para documentar que `description`, `model` y `tools` siguen siendo frontmatter válido de Claude, que `phases`/`applies_to` son metadata opcional del planner compartido y que no se exige migración de reviewers de proyecto [R2, R3, R5]

La actualización de `sdd/specs/reviewer-parity.md` queda reservada a
`/sdd:archive`, conforme al contrato SDD; no se modifica durante `/sdd:run`.

## 6. Verification

- [x] 6.1 Ejecutar la suite completa y confirmar que pasa: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -v` [R1, R2, R3, R4, R5]
- [x] 6.2 Ejecutar las validaciones de contratos del toolkit: `python3 scripts/validate_toolkit.py all`; si alguna validación falla, registrar la causa exacta antes de considerar el change listo [R1, R2, R3, R4, R5]
- [x] 6.3 Ejecutar las validaciones específicas requeridas por `sdd/project.md`: `python3 scripts/validate_toolkit.py manifests`, `python3 scripts/validate_toolkit.py skills`, `python3 scripts/validate_toolkit.py boundary` y `python3 scripts/validate_toolkit.py fixtures` [R2, R3, R4, R5]
