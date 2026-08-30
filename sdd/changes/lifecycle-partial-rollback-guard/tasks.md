# Tasks: lifecycle-partial-rollback-guard

La implementación debe preservar D1–D6 del design. En particular, el guard
compara estados lifecycle local/parent Git, no igualdad byte-a-byte; el residue
parcial nunca puede certificarse; y `validate_ship_suffix()` y
`classify_lifecycle_commit()` no se modifican.

## 1. Guard común de continuidad parent/local <!-- panel: PASS 2026-08-30 -->

- [x] 1.1 Añadir en `scripts/sdd_lifecycle.py` un helper único para leer y parsear el `STATE.md` del parent Git y comparar su estado con el estado local esperado y el `before` de la transición, devolviendo errores accionables para parent ausente, inválido o divergente [R1, R2, R4]
- [x] 1.2 Invocar el guard desde `lifecycle_commit()` antes de escribir `STATE.md` o hacer staging, derivando la transición esperada del subject y preservando el orden y el contrato STATE-only existentes [R1, R3]
- [x] 1.3 Hacer que `mark-ready()` ejecute el mismo preflight antes de preparar o mutar metadata, y añadir en `tests/test_sdd_lifecycle.py` un caso donde el parent Git sigue `ACTIVE` y el `STATE.md` local dice `LOCAL_VERIFIED`; verificar rechazo, HEAD sin avance y ausencia de commit combinado [R1, R2, R4]
- [x] 1.4 Validar también la ruta idempotente de `mark-local-verified()` contra el parent Git y rechazar cualquier divergencia en los campos lifecycle, incluido `implementation_sha` [R1, R2, R4]

## 2. Rollback explícito y fail-closed <!-- panel: PASS 2026-08-30 -->

- [x] 2.1 Ajustar `lifecycle_commit()` en `scripts/sdd_lifecycle.py` para conservar bytes y staging originales, intentar cada restauración independientemente tras un fallo de commit y distinguir error original de rollback incompleto sin ocultar fallos secundarios [R2]
- [x] 2.2 Añadir en `tests/test_sdd_lifecycle.py` un test determinista de `git commit` fallido + restauración de staging fallida; verificar error de rollback incompleto, HEAD sin avance, ningún commit lifecycle combinado y residue no consumible por un `mark-ready()` posterior [R2, R4]
- [x] 2.3 Añadir un test determinista de `git commit` fallido + restauración de bytes originales de `STATE.md` fallida; verificar que el error identifica la restauración de bytes, HEAD no avanza y `mark-ready()` rechaza la divergencia parent/local [R2, R4]
- [x] 2.4 Añadir un test combinado de `git commit` fallido + ambas restauraciones fallidas; verificar que se intentan staging y bytes, que el error identifica ambas fallas y que no se crea ningún commit lifecycle combinado [R2, R4]
- [x] 2.5 Verificar que las ediciones manuales staged/no staged de `STATE.md` siguen siendo rechazadas o no certificables según el helper existente, sin sobrescribir cambios legítimos ni convertirlos en estado lifecycle [R2, R3]
- [x] 2.6 Cubrir con regresiones deterministas el residue idempotente y la edición manual de `implementation_sha`, y mantener la restauración de bytes protegida también ante fallo de escritura [R2, R4]

## 3. Secuencia normal y límites del gate

- [x] 3.1 Mantener y ejecutar `test_mark_ready_commits_state_only_with_stable_anchor` y `test_complete_permitted_transition_sequence` en `tests/test_sdd_lifecycle.py`, confirmando dos commits consecutivos `ACTIVE->LOCAL_VERIFIED` y `LOCAL_VERIFIED->READY_FOR_PR` con el mismo implementation anchor [R3, R4]
- [x] 3.2 Añadir o ajustar cobertura en `tests/test_sdd_lifecycle.py` para demostrar que un suffix con transición inválida continúa siendo rechazado por `validate_ship_suffix()`/`classify_lifecycle_commit()` sin modificar esas funciones [R3]
- [x] 3.3 Revisar el diff de `scripts/sdd_lifecycle.py` y `tests/test_sdd_lifecycle.py` para confirmar que no se cambian estados permitidos, schema `STATE.md`, subjects válidos, `validate_ship_suffix()` ni `classify_lifecycle_commit()` [R1, R3]

## 4. Verification

- [x] 4.1 Ejecutar la regresión lifecycle focalizada: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v tests.test_sdd_lifecycle.LifecycleTests.test_mark_ready_commits_state_only_with_stable_anchor tests.test_sdd_lifecycle.LifecycleTests.test_complete_permitted_transition_sequence` [R3, R4]
- [x] 4.2 Ejecutar la suite completa: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -v` [R1, R2, R3, R4] <!-- 408 OK, 1 skip after feb2204 test-fix -->
- [x] 4.3 Ejecutar las validaciones de contratos del toolkit: `python3 scripts/validate_toolkit.py all` [R1, R2, R3, R4]
- [x] 4.4 Ejecutar las validaciones específicas: `python3 scripts/validate_toolkit.py manifests`, `python3 scripts/validate_toolkit.py skills`, `python3 scripts/validate_toolkit.py boundary` y `python3 scripts/validate_toolkit.py fixtures` [R1, R2, R3, R4]
