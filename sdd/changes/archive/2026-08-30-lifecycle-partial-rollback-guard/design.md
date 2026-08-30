# Design: lifecycle-partial-rollback-guard

## Context

El lifecycle vive en `scripts/sdd_lifecycle.py`. `mark_local_verified()` y
`mark_ready()` leen `STATE.md`, preparan una transición y delegan la
persistencia STATE-only en `lifecycle_commit()`, que escribe, hace staging y
ejecuta `git commit`; después `classify_lifecycle_commit()` valida el commit.
La clasificación y `validate_ship_suffix()` ya detectan un salto
`ACTIVE -> READY_FOR_PR`, pero lo hacen después de que el commit inválido
existe. La reproducción mostró que un fallo de commit combinado con un fallo
de rollback puede dejar `STATE.md` local en `LOCAL_VERIFIED`, mientras que el
parent Git sigue en `ACTIVE`; `mark_ready()` acepta hoy esa divergencia porque
solo consulta el estado local.

## Decisions

### D1 — Un guard común compara el estado lifecycle local con el parent Git

**Chosen:** añadir una única función interna en `scripts/sdd_lifecycle.py`,
`ensure_parent_state_matches(change, expected_before, runner)`, que lea el
`STATE.md` materializado en `HEAD` mediante `git show HEAD:<path>` y compare
todos los campos definidos por `STATE_FIELDS`, además del estado local y del
estado `before` de la transición. La función fallará si el parent no contiene
`STATE.md`, no puede parsearse, si el estado del parent no coincide con
`expected_before`, o si cualquier metadato lifecycle local —en especial
`implementation_sha`— diverge del parent. El error identificará ambos estados,
los campos divergentes y la transición esperada.

El guard vivirá junto a `lifecycle_commit()` y será la única implementación de
la comparación parent/local; los comandos no duplicarán `git show`, parsing ni
mensajes de divergencia.

Rejected: añadir una comprobación independiente dentro de cada comando —
duplicaría la semántica y dejaría transiciones futuras sin protección.

### D2 — Todas las transiciones STATE-only pasan por el guard común

**Chosen:** `lifecycle_commit()` invocará el guard como primera precondición,
antes de escribir bytes o hacer staging, derivando `expected_before` del
transition subject y usando el estado final de `data` como `after`. Esto cubre
`ACTIVE->LOCAL_VERIFIED`, `LOCAL_VERIFIED->READY_FOR_PR`,
`READY_FOR_PR->PR_OPEN`, `READY_FOR_PR->MERGED` y `PR_OPEN->PR_OPEN` sin
modificar sus semánticas. `mark-ready()` hará además un preflight mediante el
mismo helper antes de obtener contexto y preparar su metadata, para rechazar
el caso reproducido antes de cualquier mutación.

Las transiciones de archive que no escriben un lifecycle commit ordinario
seguirán sus precondiciones existentes; no se ampliará el alcance a nuevas
transiciones ni a la lógica de reviewer-panel.

Rejected: proteger solo `mark-ready()` — evitaría esta reproducción concreta,
pero dejaría el mismo hueco para otros comandos que llamen a `lifecycle_commit()`.

### D3 — Orden estricto: validar, mutar, staging, commit, clasificar

**Chosen:** cada persistencia seguirá este orden:

1. validar worktree/index, estado local y estado del parent Git;
2. capturar los bytes originales de `STATE.md` y la situación de staging;
3. construir y escribir una única versión completa del `STATE.md` en memoria y
   en disco;
4. hacer staging únicamente de `STATE.md`;
5. crear el commit STATE-only con subject y trailer lifecycle;
6. solo después del commit, ejecutar `classify_lifecycle_commit()` sobre el
   commit creado.

`mark-ready()` no escribirá `STATE.md` antes de que el preflight parent/local
   haya pasado. La secuencia válida seguirá produciendo dos commits
   consecutivos, primero `ACTIVE->LOCAL_VERIFIED` y luego
   `LOCAL_VERIFIED->READY_FOR_PR`.

Rejected: clasificar antes del commit — no puede validar un objeto Git que aún
no existe y no resuelve la atomicidad de la escritura.

### D4 — Commit failure y rollback failure son errores explícitos y terminales

**Chosen:** `lifecycle_commit()` conservará bytes y staging originales. Si falla
`git commit`, intentará restaurar staging y los bytes originales. Cada paso de
rollback se intentará de forma independiente para no ocultar la restauración
de bytes detrás de un fallo de staging. Si alguna restauración falla, lanzará
un `LifecycleError` específico de rollback incompleto que incluya qué parte
falló; no devolverá éxito, no ejecutará clasificación y no creará otro commit.

Si el rollback es completo, propagará el error original de commit y dejará el
worktree como estaba. Si es incompleto, el proceso queda deliberadamente en
estado de recuperación: el guard parent/local de cualquier comando posterior
rechazará el `STATE.md` residual antes de escribir o commitear, y el mensaje
indicará que hay que resolver el residue sin tratarlo como certificación.

Rejected: forzar una segunda restauración destructiva o reconstruir
`STATE.md` automáticamente — podría sobrescribir cambios legítimos del
usuario y convertir un fallo de persistencia en pérdida de datos.

### D5 — Las ediciones manuales de STATE.md nunca son evidencia lifecycle

**Chosen:** `ensure_clean_or_only_expected_state()` seguirá permitiendo que el
usuario tenga una edición no staged de `STATE.md` para poder diagnosticarla,
pero el guard la comparará con el parent Git y rechazará cualquier divergencia
como estado no materializado. `lifecycle_commit()` no escribirá ni hará
staging si el preflight falla. Las ediciones staged de `STATE.md` continuarán
siendo rechazadas por el helper existente. Ningún comando interpretará una
edición manual como `LOCAL_VERIFIED`, `READY_FOR_PR` ni como un nuevo anchor.

El cambio no creará commits correctivos, no editará `STATE.md` manualmente y
no modificará `validate-ship()` ni `classify_lifecycle_commit()`; esas capas
seguirán siendo la defensa posterior y el gate estricto.

Rejected: exigir que todo `STATE.md` local esté byte-a-byte idéntico al parent
antes de cada comando — impediría la mutación legítima que cada transición
debe preparar; la comparación se hará campo a campo sobre el contrato
`STATE_FIELDS`, antes de la escritura controlada, y los cambios de formato o
campos no reconocidos seguirán siendo rechazados por la comprobación de
edición preexistente.

### D6 — Prueba determinista del residue parcial y de la secuencia normal

**Chosen:** ampliar `tests/test_sdd_lifecycle.py` usando un fixture temporal
de Git y un `runner` controlado, con casos separados para cada forma de
rollback incompleto y un tercer caso combinado:

1. `git commit` falla y falla la restauración del staging;
2. `git commit` falla y falla la restauración de los bytes originales de
   `STATE.md`;
3. `git commit` falla y fallan ambas restauraciones.

Cada caso verificará el error explícito, que `HEAD` no avanza, que no aparece
ningún commit lifecycle combinado y que un `mark_ready()` posterior con un
runner normal rechaza el parent `ACTIVE` frente al `STATE.md` local residual.
El caso combinado verificará además que se intentan ambas restauraciones y
que el error identifica las dos fallas, sin ocultar una detrás de la otra.
El test de restauración de bytes comprobará el contenido residual y el test
de restauración de staging comprobará el estado del índice según corresponda;
ninguno convertirá el residue en evidencia certificada.

Se conservarán y ejecutarán `test_mark_ready_commits_state_only_with_stable_anchor`
y `test_complete_permitted_transition_sequence`, que verifican la secuencia
normal de dos commits. Se añadirá una aserción específica de los subjects y
estados parent/child del caso normal si hace falta para que el requisito sea
visible en una sola prueba.

Rejected: simular solo un `git commit` fallido o combinar las dos restauraciones
en un único caso — no demostraría cada barrera individual ni que ambas se
intentan cuando fallan simultáneamente.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Guard y persistencia | `scripts/sdd_lifecycle.py` | Añadir la comparación central parent/local, invocarla antes de mutar, hacer rollback best-effort completo y diferenciar commit failure de rollback incompleto. |
| Transiciones | `scripts/sdd_lifecycle.py` | Añadir el preflight de `mark-ready()` y conectar el guard común sin cambiar estados ni subjects válidos. |
| Regresión lifecycle | `tests/test_sdd_lifecycle.py` | Cubrir commit failure + rollback failure + posterior `mark-ready`, además de mantener la secuencia normal. |
| Contrato vivo | `sdd/specs/lifecycle-states.md`, `sdd/specs/lifecycle-implementation-anchor.md` | Documentar continuidad parent/local, rollback incompleto y rechazo de residue. Se actualizarán al archivar. |

No se modificarán `classify_lifecycle_commit()`, `validate_ship_suffix()`, el
esquema `STATE.md`, los estados permitidos, `tests/test_sdd_session.py` ni la
lógica de reviewer-panel.

## Data & interfaces

No hay cambios de schema, persistencia externa ni dependencias. La nueva
función es una interfaz interna de `scripts/sdd_lifecycle.py` y recibe el
change, el estado lifecycle esperado del parent y el `Runner` inyectable para
que los tests puedan controlar fallos. Los mensajes de error son parte del
diagnóstico, pero no se añade un nuevo estado lifecycle.

## Risks & mitigations

- **Falsos positivos por edición legítima:** comparar solo el estado lifecycle
  esperado antes de la mutación y conservar el rechazo de staging manual; no
  sobrescribir bytes del usuario.
- **Rollback parcial más visible:** preferir un error terminal y accionable a
  continuar; el guard posterior impide certificar el residue.
- **Regresión en transiciones normales:** conservar los tests existentes y
  exigir dos commits STATE-only en la secuencia aprobada.
- **Deriva entre comandos:** centralizar parent/local parsing en un solo
  helper llamado desde `lifecycle_commit()` y el preflight de `mark-ready()`.
- **Relajación accidental del merge gate:** no modificar classifier ni
  `validate_ship_suffix`; añadir pruebas de que el commit inválido sigue
  rechazándose.

## Requirement traceability

| Requirement | Design coverage | Verification |
|---|---|---|
| R1 | D1, D2, D3 | Guard común, parent Git como fuente de continuidad y rechazo antes de mutar. |
| R2 | D4, D5 | Tests de commit/rollback failure, residue y rechazo posterior; preservación de ediciones manuales. |
| R3 | D2, D3, D5 | Tests de dos commits normales y ausencia de cambios en classifier/gate. |
| R4 | D6 | Fixture determinista con fallo encadenado y error accionable. |

## Open questions

No quedan decisiones funcionales abiertas. La implementación deberá concretar
solo los detalles mecánicos de cómo el `Runner` identifica el fallo de
rollback y cómo compone el mensaje sin cambiar el contrato lifecycle.
