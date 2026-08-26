# Design: post-pr-recertification

## Context

`scripts/sdd_lifecycle.py` (834 líneas, rama `sdd/post-pr-recertification` @ `81ac379`) implementa el state machine del lifecycle de SDD. `LIFECYCLE_TRANSITIONS` (l. 96-103) sólo permite cuatro aristas: `ACTIVE→LOCAL_VERIFIED`, `LOCAL_VERIFIED→READY_FOR_PR`, `READY_FOR_PR→PR_OPEN`, `READY_FOR_PR→MERGED`. `classify_lifecycle_commit` (l. 639-718) valida que cada commit post-`implementation_sha` sea STATE-only (path único = `sdd/changes/<feature>/STATE.md`), con subject normalizado y sin auto-referenciar el propio SHA (l. 697-698); el `elif` final rechaza cualquier cambio de `implementation_sha` que no sea `READY_FOR_PR` o `LOCAL_VERIFIED`. `mark_local_verified` (l. 1429-1452) rechaza desde `state ∉ {ACTIVE, LOCAL_VERIFIED}`; `mark_ready` (l. 1455-1491) es no-op idempotente desde `PR_OPEN`/`MERGED`. `record_pr` (l. 1494-1548) idempotente para `PR_OPEN` ya grabado, no toca `implementation_sha`. Las skills `skills/review/SKILL.md` (paso 5, l. 110-115), `skills/ship/SKILL.md` (paso 1, l. 36-44) y `skills/auto/SKILL.md` (resuming, l. 247-249) tampoco tienen ruta para re-anclar. Este design añade un self-loop `PR_OPEN→PR_OPEN` y un comando `mark-recertified` que lo materializa sin relajar ninguna invariante existente.

El estado del state machine con el nuevo self-loop se documenta en `sdd/changes/post-pr-recertification/lifecycle-states.svg` (ver §D12).

## Decisions

### D1 — `mark_recertified` vive en `scripts/sdd_lifecycle.py`, no en un módulo nuevo

**Chosen:** Añadir la función `mark_recertified(root, feature, runner)` en `sdd_lifecycle.py` junto a `mark_local_verified` y `mark_ready` (entre ambas), registrar el subparser `mark-recertified` en `build_parser` (l. 1910-1959), y la rama correspondiente en `main` (l. 1962-2011). Reutiliza `ensure_local_gates`, `active_change`, `read_state`, `lifecycle_commit`, `classify_lifecycle_commit`, `query_pr`, `validate_pr_identity` y `resolve_base_ref` ya presentes.

Rejected: módulo `sdd_recertify.py` separado — dividiría el lifecycle state machine y duplicaría imports/helpers; shared rule 1 dice "un solo home" para cada contrato.

### D2 — Forma del commit recertify: subject `PR_OPEN->PR_OPEN` y body con `SDD-Prior-Implementation-SHA`

**Chosen:** Subject `chore(sdd): lifecycle <feature> PR_OPEN->PR_OPEN` (self-loop explícito, encaja con el regex `LIFECYCLE_SUBJECT_RE` l. 77-79). Trailer estándar `SDD-Lifecycle-Feature: <feature>`. Body incluye `SDD-Prior-Implementation-SHA: <old>` para trazabilidad humana — la seguridad la da el clasificador, no este trailer.

Rejected: incluir el prior SHA en el subject — `LIFECYCLE_SUBJECT_RE` no lo contemplaría; ampliarlo debilitaría el guard.
Rejected: omitir el prior SHA — perdería la única traza legible de qué ancla reemplazó este commit.

### D3 — `child.implementation_sha` se escribe como `parent_sha` (= HEAD funcional revisado)

**Chosen:** En `mark_recertified`, tras capturar `HEAD` (= parent del commit lifecycle en construcción), `data["implementation_sha"] = parent_sha`. Esto esquiva el guard existente `commit in child_text` (l. 697-698) porque el commit recertify nunca escribe su propio SHA; escribe el de su parent. La rama nueva del clasificador (R2) verifica además que `parent_state.implementation_sha ≠ parent_sha` (cambio real) y que el subject/path/trailer siguen el allowlist existente.

Rejected: escribir el SHA del propio commit recertify — bloqueado por el guard self-reference.
Rejected: dejar `implementation_sha` igual al del padre — no sería una recertificación.
Rejected: usar un puntero simbólico (`HEAD~1`) — STATE.md exige SHA concreto para que el merge gate (`require_merge`, `validate_pr_identity`) opere por hechos.

### D4 — `LIFECYCLE_TRANSITIONS` admite `("PR_OPEN", "PR_OPEN")` como elemento del set

**Chosen:** Añadir `{("PR_OPEN", "PR_OPEN")}` a `LIFECYCLE_TRANSITIONS`. El set sigue siendo allowlist; las cuatro transiciones existentes no se tocan. El clasificador (`classify_lifecycle_commit` l. 670-671) que usa este set acepta el nuevo par sin cambios adicionales a la lógica de lookup.

Rejected: introducir un token literal "RECERTIFY" en el subject y mantener un set paralelo — bifurca el código y rompe el contrato uniforme de los commits lifecycle.

### D5 — Extensión de `classify_lifecycle_commit` con rama dedicada, antes del `elif` final

**Chosen:** Insertar un bloque nuevo (entre l. 716 y 717) que, sólo cuando `transition == "PR_OPEN->PR_OPEN"`, valida: `child_state.implementation_sha == parent` (parent SHA) y `parent_state.implementation_sha != parent` (hubo cambio real). El `elif` final que rechaza cambios de ancla para las demás transiciones queda intacto; las reglas para `READY_FOR_PR` (l. 706-710) y `LOCAL_VERIFIED` (l. 711-715) también.

Rejected: un clasificador paralelo (`classify_recertify_commit`) — duplica lookup, validadores y difiere con el tiempo.
Rejected: relajar el `elif` final quitando la comparación — abriría la puerta a manipulación manual de STATE.md, que es exactamente lo que la invariante protege.

### D6 — `mark_recertified` exige rama actual == `head_branch` registrada

**Chosen:** Tras leer STATE, ejecutar `git branch --show-current` y comparar con `data["head_branch"]`. Si difiere, `LifecycleError` con el nombre real y la rama esperada. Coincide con la convención de `mark_ready` (l. 1462-1466 implícita vía `git_context`) y ship (l. 1122-1127 explícita).

Rejected: omitir la comprobación — un recertify ejecutado desde la rama equivocada firmaría un rango que no es el change; mismo riesgo que `mark-ready` mitiga.

### D7 — `mark_recertified` no hace push y nunca toca `git push`

**Chosen:** El comando no invoca `git push`. `/sdd:review` tampoco. Sólo validan vía `gh pr view` que `HEAD ∈ commits[]` y que el PR sigue `OPEN`. Si `HEAD ∉ commits[]`, `mark-recertified` rechaza con un mensaje accionable indicando al usuario que ejecute un push normal antes (`git push origin <head_branch>`, **nunca** `--force`/`--force-with-lease`).

El push del fix funcional es responsabilidad explícita del usuario en el flujo post-PR: con un PR ya abierto, añadir un commit funcional y publicarlo es un `git push origin <head_branch>` normal, no una publicación inicial. Distinguir entre las dos publicaciones:

- **Publicación inicial del PR**: la ejecuta `/sdd:ship` (`skills/ship/SKILL.md` l. 120-141) tras `READY_FOR_PR`, mediante `gh pr create` + un único push final tras `record-pr`. Es la única vez que ship hace un push de la feature branch.
- **Actualización normal de una rama cuyo PR ya está abierto**: la ejecuta el usuario con `git push origin <head_branch>` cuando añade un commit funcional tras `PR_OPEN`. No hay `gh pr create`, no hay `--force`, no hay reescritura de historia; la rama simplemente avanza. `mark-recertified` sólo verifica que ese push ocurrió (HEAD ∈ `commits[]` del PR).

Rejected: hacer push desde `mark-recertified` — introduce un fallo de red en mitad de la certificación y cruza el contrato de "publicar" sin pertenecer a la fase de certificación.
Rejected: hacer push desde `/sdd:review` — el skill es report-only (l. 154-157); publicar no es su contrato en ningún caso.
Rejected: que `/sdd:ship` haga también el push del fix tras `PR_OPEN` — ship no certifica, sólo publica; el fix entraría en el PR sin que un panel lo haya visto.

### D8 — Múltiples recertificaciones: el comando acepta re-entrada libre

**Chosen:** Cada llamada comprueba `HEAD != implementation_sha`; si verdadero, re-ancla. Si falso, devuelve "nada que recertificar" sin commit (idempotente). No hay contador, no hay estado extra — `implementation_sha` siempre refleja el último `HEAD` revisado.

Rejected: contador `recertification_count` en STATE — campo adicional, deriva de `gh pr view`, ruido.

### D9 — Rechazo explícito desde cualquier estado ≠ `PR_OPEN`

**Chosen:** `mark_recertified` lee `state`; si no es `PR_OPEN`, `LifecycleError("mark-recertified requires state PR_OPEN; found '<state>'. …")`. El mensaje nombra el estado actual y, cuando aplica, sugiere el comando correcto (`/sdd:review`, `/sdd:archive`, etc.).

Rejected: no-op silencioso — escondería errores de uso y bloquearía la diagnosis.

### D10 — `/sdd:review` bifurca a recertificación con la misma plantilla, scope acotado al rango

**Chosen:** Tras el branch guard (`git branch --show-current` l. 68), leer `STATE.md.state`. Si `PR_OPEN`: lanzar el panel sobre el rango `implementation_sha..HEAD` (en vez de la rama completa), y en PASS llamar `mark-recertified` (en vez de `mark-local-verified + mark-ready`). Mantener `validate-ship` post-milestone para confirmar que el nuevo suffix es lifecycle-only.

**Boundary temporal y SHAs del proceso (sin ambigüedad):**

Denotamos `I_n` al ancla registrada en `STATE.md.implementation_sha` antes del fix, y `H_n` al HEAD funcional tras el commit de fix pero **antes** del commit lifecycle de recertificación. La secuencia exacta es:

```
I_n  ──►  H_n  ──►  push  ──►  /sdd:review  ──►  PASS  ──►  mark-recertified
old_anchor   functional fix HEAD                       panel sobre (I_n .. H_n]
                                                  (commits con I_n exclusive,
                                                   H_n inclusive)

                                          ──►  lifecycle commit C_n
                                              subject: chore(sdd): lifecycle <feature> PR_OPEN->PR_OPEN
                                              parent: H_n
                                              STATE.md.implementation_sha = H_n (parent_sha, NO el SHA de C_n)
                                              ──►  HEAD_nuevo = C_n
```

Propiedades que se mantienen invariantes:

- **El SHA certificado es exactamente `H_n`**, nunca `C_n`. El clasificador exige `child_state.implementation_sha == parent_sha` (D5), donde `parent_sha = H_n`. Esto preserva el invariante del merge gate: `validate_pr_identity` exige que `implementation_sha ∈ commits[]` del PR (l. 1406-1409); como `H_n` ya estaba pusheado al PR antes del review, la condición sigue valiendo.
- **El rango revisado por el panel es `(I_n .. H_n]`** — implementacionalmente `git rev-list implementation_sha..HEAD --not implementation_sha`, que produce todos los commits introducidos por el fix, exclusive de `I_n` e inclusive de `H_n`. El panel **no** ve ni el código anterior a `I_n` (ya certificado en reviews previos) ni el commit lifecycle `C_n` (no existe aún al lanzar el panel).
- **El nuevo suffix validado por `validate_ship_suffix` es `(H_n .. C_n]`** — un único commit lifecycle, `C_n`. Por construcción el suffix sigue siendo lifecycle-only.

**Ciclos sucesivos sobre el mismo PR.** Cada recertificación sobrescribe `implementation_sha` con el último `H_n`. Para el siguiente ciclo:

```
I_{n+1}  :=  H_n          (el ancla vieja del ciclo n+1 es el HEAD funcional revisado en el ciclo n)
H_{n+1}  :=  nuevo HEAD funcional tras el siguiente fix
```

El panel del ciclo `n+1` se ejecuta sobre `(I_{n+1} .. H_{n+1}]` — **sólo el trabajo nuevo introducido entre recertificaciones**, no el acumulado de todos los fixes. Esto cumple la regla de `skills/review/SKILL.md` "two fix rounds, then stop" (l. 94-98) por construcción: cada ronda revisa exactamente su delta. El suffix tras `n` ciclos contiene `n` commits lifecycle `PR_OPEN->PR_OPEN` consecutivos, cada uno con su propio `SDD-Prior-Implementation-SHA` en el body, formando una cadena auditable de anclas.

Rejected: nuevo skill `/sdd:recertify` — un home extra para el mismo contrato de "verificar y certificar"; shared rule 1 lo desaconseja.
Rejected: ejecutar panel sobre la rama completa — wasted context revisando código ya certificado por el panel anterior.
Rejected: certificar `C_n` en vez de `H_n` — el merge gate exige que el SHA certificado esté en `commits[]` del PR antes del commit lifecycle; `C_n` aún no está pusheado, así que fallaría `validate_pr_identity` en el siguiente `require_merge`.

### D11 — `/sdd:ship` rechaza en `PR_OPEN` con `HEAD != implementation_sha` redirigiendo a `/sdd:review`

**Chosen:** Extender el case `PR_OPEN` del paso 1 de `skills/ship/SKILL.md` (l. 37-40) con una sub-rama explícita: si `HEAD != implementation_sha`, abortar con `LifecycleError` accionable que dice "ejecuta `/sdd:review <feature>` para recertificar el fix". Las dos ramas previas (`HEAD == implementation_sha` → sync-base + record-pr idempotente) se mantienen idénticas.

Rejected: invocar `mark-recertified` desde ship — ship no certifica, ship publica.
Rejected: aceptar el estado sin actuar — el PR quedaría con rango no revisado y la próxima iteración de validate-ship fallaría en silencio.

### D12 — Diagram del state machine con el nuevo self-loop, en SVG junto a design.md

**Chosen:** Generar `sdd/changes/post-pr-recertification/lifecycle-states.svg` con el state machine ACTIVE → LOCAL_VERIFIED → READY_FOR_PR → PR_OPEN → MERGED → ARCHIVED, los laterales (CANCELLED, BLOCKED) y el self-loop `PR_OPEN → PR_OPEN` etiquetado "recertify" destacado visualmente. Referenciado desde este design.

Rejected: ASCII art en el design — el SVG se renderiza inline en GitHub y difs limpio; ASCII se descolora y rompe review.

### D13 — Tests en `tests/test_sdd_lifecycle.py`, no en archivo nuevo

**Chosen:** Nueva clase `LifecycleRecertifyTests` en el módulo existente, junto a `SyncBaseTests` y `PublishArchiveTests`. Reutiliza el `setUp` (`temporary` repo, fixture git, PR payload faked). Añadir 3 tests contractuales a `tests/test_lifecycle_contract.py` (review PR_OPEN branch, ship PR_OPEN rejection, auto resuming).

**Matriz contractual de tests (T1–T6 + N1–N17).** Cada fila define: preestado, operación, resultado esperado, e invariante/requisito cubierto. Los nombres son los nombres de métodos en la nueva clase `LifecycleRecertifyTests` (siguen la convención `test_<descripción>_...` del archivo).

#### Positivos

| ID | Test | Preestado | Operación | Resultado esperado | Cubre |
|---|---|---|---|---|---|
| **T1** | `test_recertify_re_anchors_and_passes_validate_ship` | `state=PR_OPEN`, `I_n=old_anchor`, HEAD=old_anchor. Commit funcional `F` que deja HEAD=F. PR_OPEN en `gh`, `commits=[I_n, F]`. | `mark-recertified`; después `validate_ship_suffix`. | (1) Commit lifecycle `C` con subject `PR_OPEN->PR_OPEN`, `implementation_sha=F`, `pr_url/pr_number/pr_state/repository/head_branch/base_branch` inalterados. (2) `validate_ship_suffix` pasa con `[C]` en el suffix. | R1.1, R1.5, D3, D5 |
| **T2** | `test_recertify_is_idempotent_when_head_matches_anchor` | `state=PR_OPEN`, `HEAD=implementation_sha`, sin commits nuevos. | `mark-recertified`. | Mensaje `"Recertification is current; nothing to do"`. Sin commit lifecycle nuevo. `STATE.md` byte-idéntico antes y después. | R4.1, D8 |
| **T3** | `test_recertify_preserves_pr_identity` | `state=PR_OPEN`, PR_OPEN en `gh` con URL/N fijos. | `mark-recertified`. | Tras la operación: `pr_url`, `pr_number`, `pr_state`, `repository`, `head_branch`, `base_branch` byte-idénticos; sólo cambia `implementation_sha`. | R1.1 |
| **T4** | `test_recertify_chained_two_cycles` | `state=PR_OPEN`, ancla=I₀. Secuencia: funcional F₁ (HEAD=F₁) → recertify → ancla=F₁. Funcional F₂ (HEAD=F₂) → recertify → ancla=F₂. | `mark-recertified` dos veces consecutivas. | Dos commits lifecycle `C₁, C₂` consecutivos. `implementation_sha=F₂`. `pr_url/pr_number` constantes. `validate_ship_suffix` pasa tras la segunda. Cada commit lleva `SDD-Prior-Implementation-SHA` apuntando al ancla anterior. | R4.2, R4.4, D8, D10 |
| **T5** | `test_validate_ship_suffix_accepts_recertify_commit` | `state=PR_OPEN`, ya recertificado. | `validate_ship_suffix`. | Devuelve `[C_recertify]`; ninguna `LifecycleError`. | R2.1, D5 |
| **T6** | `test_classify_lifecycle_commit_accepts_recertify_transition` | Commit con subject `PR_OPEN->PR_OPEN`, `child.implementation_sha=parent`, `parent_state.implementation_sha≠parent`, único path `STATE.md`, trailer presente. | `classify_lifecycle_commit`. | Devuelve `(feature, transition)` sin error. | R2.1, D5 |

#### Negativos

| ID | Test | Preestado | Operación | Resultado esperado | Cubre |
|---|---|---|---|---|---|
| **N1** | `test_recertify_refuses_merged_pr` | `state=PR_OPEN`, pero `gh pr view` devuelve `state=MERGED`. | `mark-recertified`. | `LifecycleError` conteniendo `"MERGED"` y sugiriendo `/sdd:archive`. `STATE.md` sin cambios. | R1.2 |
| **N2** | `test_recertify_refuses_closed_pr` | `state=PR_OPEN`, pero `gh pr view` devuelve `state=CLOSED` y `mergedAt=None`. | `mark-recertified`. | `LifecycleError` conteniendo `"CLOSED"`, sugiriendo reabrir o abrir PR nuevo vía `/sdd:ship`. | R1.2 |
| **N3** | `test_recertify_refuses_dirty_worktree` | `state=PR_OPEN`, working tree con `code.py` untracked. | `mark-recertified`. | `LifecycleError` regex `"outside the lifecycle STATE.md allowlist"`. Working tree inalterado. | R5.5 |
| **N4** | `test_recertify_refuses_staged_state_change` | `state=PR_OPEN`, `STATE.md` con cambios staged pero no committed. | `mark-recertified`. | `LifecycleError` regex `"already has staged changes"`. | R5.5 |
| **N5** | `test_recertify_refuses_force_push_or_rebase` | `state=PR_OPEN`, `implementation_sha=A`. Tras `git rebase` destructivo, HEAD=B con B no descendiente de A. PR en `gh` con `commits=[A, B]`. | `mark-recertified`. | `LifecycleError` regex que indica que `A` no es ancestro de `HEAD`. (El guard del rango `validate_ship_suffix` también lo capturaría si se llega a invocar.) | R1.3 |
| **N6** | `test_recertify_refuses_different_pr` | `state=PR_OPEN` con `repository=X/Y`. `gh pr view` devuelve `state=OPEN` pero `baseRefName`/`headRefName`/`url` distintos. | `mark-recertified`. | `LifecycleError` regex `"PR <field> mismatch"`. | R1.1, D6 |
| **N7** | `test_recertify_refuses_manual_state_md_edit_with_code_commit` | `state=PR_OPEN`. Usuario edita STATE.md a mano cambiando `implementation_sha`, hace commit con subject `chore(sdd): lifecycle <f> PR_OPEN->PR_OPEN`, sin que el commit sea el resultado de `mark-recertified`. | `validate_ship_suffix`. | `LifecycleError` `"unauthorized lifecycle subject"` o `"implementation_sha..."` (cualquiera de los guards existentes lo caza). | D5, propuesta R3.2 |
| **N8** | `test_recertify_refuses_recertify_subject_with_wrong_anchor` | `state=PR_OPEN`. Commit con subject `PR_OPEN->PR_OPEN` pero `child.implementation_sha` ≠ parent (escribió un SHA distinto a mano). | `classify_lifecycle_commit`. | `LifecycleError` regex `"must record the reviewed HEAD"` (D5). | R2.2 |
| **N9** | `test_recertify_refuses_non_pr_open_state` | Cambia STATE.md a `READY_FOR_PR`/`ACTIVE`/`LOCAL_VERIFIED`/`MERGED`/`ARCHIVED`/`CANCELLED`. Working tree limpio. | `mark-recertified`. | `LifecycleError` con el estado actual y, según aplique, sugerencia del comando correcto. Tabla paramétrica como `test_illegal_transition_sources_are_rejected` (l. 705-755). | R5.1, D9 |
| **N10** | `test_recertify_refuses_blocked` | `state=PR_OPEN`, `BLOCKED.md` no vacío. | `mark-recertified`. | `LifecycleError` regex `"unresolved work"`. (Gate `ensure_local_gates`.) | R5.2 |
| **N11** | `test_recertify_refuses_incomplete_tasks` | `state=PR_OPEN`, `tasks.md` con una tarea `- [ ]`. | `mark-recertified`. | `LifecycleError` regex `"incomplete task"`. (Gate `ensure_local_gates`.) | R5.3 |
| **N12** | `test_recertify_refuses_local_review_not_approved` | `STATE.md.local_review=PENDING`. | `mark-recertified`. | `LifecycleError` regex `"Local review is not approved"`. | R5.4 |
| **N13** | `test_recertify_refuses_wrong_branch` | `state=PR_OPEN`, `head_branch=sdd/<feature>`, pero `git branch --show-current` es otra rama. | `mark-recertified`. | `LifecycleError` nombrando la rama real y la esperada. | R5.x (implícito en D6) |
| **N14** | `test_recertify_refuses_head_not_in_pr_commits` | `state=PR_OPEN`, `gh pr view.commits` no contiene HEAD (usuario olvidó pushear). | `mark-recertified`. | `LifecycleError` regex `"not present in the Pull Request commits"` (vía `validate_pr_identity`). | R1.4 |
| **N15** | `test_recertify_refuses_old_anchor_not_in_pr_commits` | PR rebaseado en GitHub por un admin: `commits[]` ya no contiene `I_n`. | `mark-recertified`. | `LifecycleError` regex `"implementation SHA is not present in the Pull Request commits"` (l. 1406-1409). | R1.4 |
| **N16** | `test_recertify_does_not_invoke_git_push` | `state=PR_OPEN`, todo en orden. Runner que registra comandos. | `mark-recertified`. | La lista de comandos registrados NO contiene ningún `["git", "push", ...]`. | R1 (sin push), D7 |
| **N17** | `test_recertify_preserves_existing_contract_tests` | Suite completa. | Re-ejecutar `tests/test_sdd_lifecycle.py` y `tests/test_lifecycle_contract.py`. | Todos los tests preexistentes pasan, en particular `test_marking_ready_again_does_not_resurrect_a_recorded_pr` (l. 447-460), `test_marking_ready_rejects_code_commits_after_the_stable_anchor` (l. 430-445), `test_ship_suffix_rejects_code_metrics_and_dirty_worktree` (l. 394-407), `test_illegal_transition_sources_are_rejected` (l. 705-755) y los tests de `SyncBaseTests`. | R3, propuesta Backwards compat |

**Tests contractuales adicionales en `tests/test_lifecycle_contract.py`** (3 tests, no paramétricos):

| ID | Test | Cubre |
|---|---|---|
| **C1** | `test_review_skill_branches_at_pr_open_for_recertify` — verifica que `skills/review/SKILL.md` menciona la rama `PR_OPEN`, contiene la llamada a `mark-recertified`, y NO contiene `mark-local-verified`/`mark-ready` en esa rama. | R6.1, R6.2, D10 |
| **C2** | `test_ship_skill_refuses_pr_open_with_unanchored_head` — verifica que `skills/ship/SKILL.md` rechaza explícitamente el caso `PR_OPEN` + `HEAD != implementation_sha` con redirección a `/sdd:review`. | R7.1, D11 |
| **C3** | `test_auto_skill_resumes_pr_open_with_recertify_path` — verifica que `skills/auto/SKILL.md` (sección resuming) cubre el caso `PR_OPEN` con commits no anclados delegando a `/sdd:review`. | (alineamiento con R6 vía auto) |

Rejected: `tests/test_sdd_recertify.py` — los tests del lifecycle viven juntos en `test_sdd_lifecycle.py` (mirror de `SyncBaseTests`); separarlos rompe el patrón del archivo.
Rejected: tests parametrizados con `subTest` para N9 — la tabla paramétrica ya existe (`test_illegal_transition_sources_are_rejected` l. 705-755); añadir otro `subTest` loop opaca el mensaje de fallo. El test N9 lo extiende directamente con `setUp` por estado.

### D14 — Sin cambios de versión ni de schema

**Chosen:** No se incrementa `schema` de STATE.md (sigue siendo "1"). No se renombra ningún campo. `STATE_FIELDS` (l. 28-41) no cambia. La única adición lógica es la fila `("PR_OPEN", "PR_OPEN")` en `LIFECYCLE_TRANSITIONS`. Cambios existentes en `STATE.md` de cambios in-flight siguen siendo válidos; backwards compatibility total.

Rejected: bump de schema "2" — no hay incompatibilidad hacia atrás; bumps sin causa rompen merges en cambios in-flight.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Lifecycle state machine | `scripts/sdd_lifecycle.py` | Añadir `{("PR_OPEN", "PR_OPEN")}` a `LIFECYCLE_TRANSITIONS` (l. 96-103). Insertar rama dedicada en `classify_lifecycle_commit` antes del `elif` final (l. 716-717). Añadir `mark_recertified(root, feature, runner)`. Añadir subparser `mark-recertified` en `build_parser` (l. 1910-1959). Añadir rama en `main` (l. 1962-2011). |
| Review skill | `skills/review/SKILL.md` | Bifurcar paso 5 según `state`: si `PR_OPEN`, panel sobre `implementation_sha..HEAD` y `mark-recertified`. Documentar precondición de push manual antes de review. Actualizar nota de "invalidates the recorded implementation_sha" (l. 104-108) para apuntar al flujo soportado. |
| Ship skill | `skills/ship/SKILL.md` | En el case `PR_OPEN` del paso 1 (l. 37-40), añadir sub-rama `HEAD != implementation_sha` → error accionable + redirección a `/sdd:review`. |
| Tests (lógica) | `tests/test_sdd_lifecycle.py` | Nueva clase `LifecycleRecertifyTests` con los tests del matriz T1–T6 + N1–N17. Reutiliza `setUp` y `gh_runner` existentes. |
| Tests (contrato) | `tests/test_lifecycle_contract.py` | 3 tests nuevos verificando que `review/SKILL.md`, `ship/SKILL.md` y `auto/SKILL.md` reflejan el flujo de recertificación. |
| Diagram | `sdd/changes/post-pr-recertification/lifecycle-states.svg` | SVG del state machine con el self-loop `PR_OPEN→PR_OPEN` etiquetado. |
| Doc del design | `sdd/changes/post-pr-recertification/design.md` | Este documento (existe al ejecutar la fase). |

## Data & interfaces

- **CLI**: nuevo subparser `mark-recertified <feature>` en `sdd_lifecycle.py`. Sin flags obligatorios. Mensaje de éxito: `"PR_OPEN re-anchored at <new sha[:12]>."`. Mensaje de no-op: `"Recertification is current; nothing to do."`. Errores vía `LifecycleError` con código de salida 1.
- **STATE.md**: ningún campo nuevo. El commit recertify SOBREESCRIBE `implementation_sha` (única excepción al guard existente, ya cubierta por la nueva rama del clasificador). Los demás campos se preservan literalmente.
- **API interna**: `mark_recertified(root, feature, runner=...)` sigue la convención de las demás funciones del módulo (acepta un `runner` inyectable para tests; default `subprocess.run`). Sin decoradores ni side effects fuera del lifecycle.
- **Sin eventos / sin cambios de config**: este cambio no añade variables de entorno, ni config files, ni dispara hooks.

## Risks & mitigations

| Riesgo | Mitigación |
|---|---|
| Una rama de recertificación que escribe el SHA del propio commit | El clasificador exige `child.implementation_sha == parent_sha`, y `parent != commit` por construcción (el commit recertify es nuevo). Test específico cubre el caso. |
| Manipulación manual de STATE.md: el usuario edita `implementation_sha` a mano y hace commit con subject `PR_OPEN->PR_OPEN` | `classify_lifecycle_commit` exige `child.implementation_sha == parent` (no el SHA escrito a mano) y `parent_state.implementation_sha != parent`. Tests N7 + N8. |
| Múltiples sesiones ejecutando `mark-recertified` en paralelo | Ambas producen transiciones `PR_OPEN->PR_OPEN` lícitas; la segunda lee como `parent_state.implementation_sha` el resultado de la primera, lo que es correcto. Sin race condition sobre STATE.md porque `lifecycle_commit` rechaza dirty/staged paths. |
| Recertificación de un PR ya MERGED | `mark_recertified` re-query `gh pr view`; si `state == MERGED`, `LifecycleError("PR is MERGED; run /sdd:archive.")`. Test N1. |
| Recertificación de un PR CLOSED sin merge | Mismo check; mensaje sugiere reabrir o abrir nuevo PR vía `/sdd:ship`. Test N2. |
| Recertificación sin push (HEAD no en `commits[]` del PR) | `validate_pr_identity` falla con `LifecycleError("HEAD <sha> is not in the PR's commits.")`. Test N14. |
| `validate_ship_suffix` tras recertificación rechaza el recertify commit | La nueva rama del clasificador lo acepta; test T5. |
| Cambios accidentales en `record-pr` o `mark-ready` | Out of scope explícito en la proposal; el diff del PR no tocará esas dos funciones. Code review lo confirma. |
| Auto flow ejecuta `/sdd:review` en un feature PR_OPEN con commits no anclados | La rama de resuming en `skills/auto/SKILL.md` (l. 247-249) delega a `/sdd:review`; el review skill aplica la rama de recertificación. Sin nueva lógica en auto. |
| Backwards compatibility: cambios legacy sin `pr_url` | `mark_recertified` exige PR completo; rechaza con "record PR with /sdd:ship first". No rompe el flujo legacy. |

## Open questions

Ninguna que requiera decisión del usuario antes de implementar. Las decisiones tomadas son las mínimas necesarias y siguen las restricciones explícitas del usuario (nombre `mark-recertified`, self-loop, sin push, ramas en `/sdd:review` y `/sdd:ship`, sin nuevos estados, sin relajar `validate-suffix`, sin cambios funcionales en `record-pr`/`mark-ready`). El usuario puede revisar las decisiones D1–D14 en el gate del design antes de pasar a `/sdd:tasks`.