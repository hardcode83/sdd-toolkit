# Tasks: SDD Toolkit 0.33 lifecycle integrity

## 1. Lifecycle metadata commit primitive <!-- panel: PASS 2026-08-10 -->

- [x] 1.1 Implementar en `scripts/sdd_lifecycle.py` un helper de commit lifecycle que capture el parent antes de escribir, haga stage únicamente de `sdd/changes/<feature>/STATE.md`, use el subject exacto `chore(sdd): lifecycle <feature> <transition>` y el trailer `SDD-Lifecycle-Feature: <feature>`, y nunca incruste el SHA del commit hijo en STATE. [R1, R2, R4]
- [x] 1.2 Hacer que el helper rechace índice o worktree con cambios no autorizados, preserve paths del usuario y restaure únicamente sus bytes/stage si falla el commit; verificar exit codes y ausencia de mutaciones parciales con `tests/test_sdd_lifecycle.py`. [R2, D2, D6, R4, R5]
- [x] 1.3 Hacer idempotente el helper cuando el STATE renderizado ya coincide con la transición; verificar que una segunda ejecución no crea un commit lifecycle duplicado. [R1, R4]

## 2. `mark-ready` y transición limpia <!-- panel: PASS 2026-08-10 -->

- [x] 2.1 Actualizar `mark_ready()` en `scripts/sdd_lifecycle.py` para conservar `implementation_sha` como el HEAD padre estable y persistir el READY_FOR_PR mediante el helper lifecycle, sin reset, amend, rebase ni squash. [R1, R2]
- [x] 2.2 Cubrir en `tests/test_sdd_lifecycle.py` la matriz: worktree limpio pasa; cambio unstaged no-STATE falla sin mutar; cambio staged no-STATE falla sin mutar; STATE preexistente dirty falla sin sobrescribir; mezcla STATE+otro path falla; fallo de commit restaura solo la preparación del helper. Para cada caso capturar antes/después los bytes de STATE, `git diff`, `git diff --cached`, `git ls-files --stage`, exit code y paths, demostrando que ningún cambio staged/unstaged previo del usuario se modifica. [R2, D2, D6, R4, R5]
- [x] 2.3 Verificar en el mismo test que el commit de `mark-ready` modifica exactamente STATE.md, tiene un solo padre, subject/trailer exactos, deja worktree limpio y no contiene su propio SHA. [R1, R4]

## 3. Clasificador de commits lifecycle y ship <!-- panel: PASS 2026-08-10 -->

- [x] 3.1 Implementar en `scripts/sdd_lifecycle.py` el clasificador por commit: parent único; subject exacto sin sufijo; trailer coincidente; feature slug seguro sin `/`, `\\`, `..`, componentes vacíos ni aliases; path repo-relative normalizado único `sdd/changes/<feature>/STATE.md`; STATE padre/hijo parseable; transición válida; anchor coherente. [R1, R3, R5]
- [x] 3.2 Implementar la enumeración completa de `implementation_sha..HEAD` y rechazar cualquier commit posterior no clasificado, commit STATE-only arbitrario, subject con sufijo, path traversal, alias normalizado, commit mixto o modificación de métricas/código/evidencia/specs. No usar solo el diff agregado. [R3, R4, R5]
- [x] 3.3 Extender `scripts/sdd_lifecycle.py` con `validate_ship_suffix` y su subcomando CLI: debe verificar ancestry, enumerar cada commit `implementation_sha..HEAD` y aplicar el clasificador común. `skills/ship/SKILL.md` invocará este gate antes de ejecutar el único `git push`; no se añadirá `scripts/sdd_ship.py` ni otra capa ejecutable paralela. [R3, D3, D6, R5]
- [x] 3.4 Actualizar `skills/ship/SKILL.md` y el contrato CLI de `scripts/sdd_lifecycle.py validate-ship` para exigir ancestry, clasificación commit-a-commit, worktree limpio y push solo después de todos los gates; mantener explícitamente el push como responsabilidad exclusiva de ship. [R3, D3, R5]
- [x] 3.5 Añadir en `tests/test_sdd_lifecycle.py` y `tests/test_lifecycle_contract.py` pruebas que invoquen `validate_ship_suffix`/su CLI y simulen el push en el skill: acepta suffix lifecycle autorizado; enumera todos los commits; el skill ejecuta push exactamente una vez tras gates verdes; no ejecuta push ante ancestry, dirty worktree, commit no autorizado, subject suffix, traversal o path fuera de allowlist. [R3, D3, D6, R4]

## 4. `record-pr` y review <!-- panel: PASS 2026-08-10 -->

- [x] 4.1 Actualizar `record_pr()` en `scripts/sdd_lifecycle.py` para escribir únicamente metadata PR en STATE, conservar exactamente `implementation_sha`, crear un commit explícito lifecycle con transición `READY_FOR_PR -> PR_OPEN`, validar ese commit con el mismo clasificador común que usa `scripts/sdd_lifecycle.py` y no invocar push. [R1, R3, D1, D3, D4, R4]
- [x] 4.2 Actualizar `skills/review/SKILL.md` para validar después de las transiciones lifecycle: worktree limpio; implementation_sha estable y ancestro; cada commit posterior autorizado; STATE coherente con la transición; sin exigir self-reference. [R1, R2, R3]
- [x] 4.3 Actualizar `skills/auto/SKILL.md` y `skills/ship/SKILL.md` para eliminar la afirmación de que `record-pr` hace push y describir el límite commit-local/push-exclusivo de ship. [R3, R5]
- [x] 4.4 Ampliar `tests/test_sdd_lifecycle.py` y `tests/test_lifecycle_contract.py`: `record-pr` crea commit STATE-only, conserva el anchor, pasa el commit por el clasificador común y no llama push; review pasa con transición lifecycle limpia y coherente; ambos fallan ante dirty/mixed state o metadata inconsistente. [R1, R2, R3, D1, D3, D4, D5, R4]

## 5. Métricas, contratos y trazabilidad <!-- panel: PASS 2026-08-10 -->

- [x] 5.1 Declarar en `scripts/sdd_lifecycle.py` (`mark_ready`, `record_pr`, `validate_ship_suffix`), `skills/review/SKILL.md`, `skills/ship/SKILL.md` y `skills/auto/SKILL.md` que métricas genéricas no forman parte del lifecycle allowlist, no se stagean y un path tracked dirty por métricas impide declarar clean handoff. [R2, R5]
- [x] 5.2 Añadir `tests/test_sdd_lifecycle.py::test_metrics_path_is_not_lifecycle_allowlisted` y fixtures de paths para demostrar que `sdd/metrics.md` y cualquier path distinto de STATE son rechazados como suffix lifecycle. [R4, R5]
- [x] 5.3 Actualizar `README.md` y `docs/guide.md` (los dos documentos de gobernanza versionados de este checkout) con la matriz completa `R1–R5 → D1–D6 → task ID → archivo:función/entrypoint → test ID → comando exacto → exit code/salida esperada → artefacto de evidencia`, incluyendo la propiedad no auto-referencial y la validación commit-a-commit. [R1, R5]
- [x] 5.4 Crear `sdd/changes/sdd-toolkit-0330-lifecycle-integrity/evidence/R1-R5-traceability.md` durante la implementación y exigir una fila material por cada R1–R5, con D#, task, path:línea, test nombrado, comando exacto, exit code, salida relevante y criterio de pass; incluir evidencia de que ningún path de AgentsLabs application, P2, P3 o archive fue modificado. [R5, D1, D2, D3, D4, D5, D6, R4]

## 6. Verification <!-- panel: PASS 2026-08-10 -->

- [x] 6.1 Ejecutar la suite Toolkit completa definida por el proyecto: `pytest`; registrar exit code, tests ejecutados y ausencia de regresiones. [R4]
- [x] 6.2 Ejecutar los tests focalizados de lifecycle: `pytest tests/test_sdd_lifecycle.py tests/test_lifecycle_contract.py`; registrar exit code y cada caso de la matriz dirty/clean, ancestry, clasificador y push. [R4]
- [x] 6.3 Ejecutar `python3 scripts/validate_toolkit.py all` y `python3 scripts/sdd-doctor.py --root tests/fixtures/valid`; ambos deben terminar con exit code `0`. [R5]
- [x] 6.4 Ejecutar `git diff --check`, comprobar `git status --short` limpio y verificar con `git diff --name-only` y `git diff --name-only <baseline>..HEAD` que solo se modifican paths del Toolkit y que no se introducen artefactos de AgentsLabs, P2, P3 ni archives; registrar evidencia de paths autorizados en `evidence/R1-R5-traceability.md`. [R5, D6]

