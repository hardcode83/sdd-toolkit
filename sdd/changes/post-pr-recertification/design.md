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

**Chosen:** El comando no invoca `git push`. Sólo valida vía `gh pr view` que `HEAD ∈ commits[]` y que el PR sigue `OPEN`. Si `HEAD ∉ commits[]`, rechaza con mensaje indicando que el usuario debe ejecutar `git push origin <head_branch>` antes. Esto preserva el contrato de ship como único publicador de feature branches (`skills/ship/SKILL.md` l. 133-135).

Rejected: hacer push desde `mark-recertified` — rompe "ship es el único que push", introduce un punto de fallo de red en mitad de la certificación.
Rejected: que el review skill lo haga — el skill es report-only en `review` (l. 154-157); publicar no es su contrato.

### D8 — Múltiples recertificaciones: el comando acepta re-entrada libre

**Chosen:** Cada llamada comprueba `HEAD != implementation_sha`; si verdadero, re-ancla. Si falso, devuelve "nada que recertificar" sin commit (idempotente). No hay contador, no hay estado extra — `implementation_sha` siempre refleja el último `HEAD` revisado.

Rejected: contador `recertification_count` en STATE — campo adicional, deriva de `gh pr view`, ruido.

### D9 — Rechazo explícito desde cualquier estado ≠ `PR_OPEN`

**Chosen:** `mark_recertified` lee `state`; si no es `PR_OPEN`, `LifecycleError("mark-recertified requires state PR_OPEN; found '<state>'. …")`. El mensaje nombra el estado actual y, cuando aplica, sugiere el comando correcto (`/sdd:review`, `/sdd:archive`, etc.).

Rejected: no-op silencioso — escondería errores de uso y bloquearía la diagnosis.

### D10 — `/sdd:review` bifurca a recertificación con la misma plantilla, scope acotado al rango

**Chosen:** Tras el branch guard (`git branch --show-current` l. 68), leer `STATE.md.state`. Si `PR_OPEN`: lanzar el panel sobre el rango `implementation_sha..HEAD` (en vez de la rama completa), y en PASS llamar `mark-recertified` (en vez de `mark-local-verified + mark-ready`). Mantener `validate-ship` post-milestone para confirmar que el nuevo suffix es lifecycle-only.

Rejected: nuevo skill `/sdd:recertify` — un home extra para el mismo contrato de "verificar y certificar"; shared rule 1 lo desaconseja.
Rejected: ejecutar panel sobre la rama completa — wasted context revisando código ya certificado por el panel anterior.

### D11 — `/sdd:ship` rechaza en `PR_OPEN` con `HEAD != implementation_sha` redirigiendo a `/sdd:review`

**Chosen:** Extender el case `PR_OPEN` del paso 1 de `skills/ship/SKILL.md` (l. 37-40) con una sub-rama explícita: si `HEAD != implementation_sha`, abortar con `LifecycleError` accionable que dice "ejecuta `/sdd:review <feature>` para recertificar el fix". Las dos ramas previas (`HEAD == implementation_sha` → sync-base + record-pr idempotente) se mantienen idénticas.

Rejected: invocar `mark-recertified` desde ship — ship no certifica, ship publica.
Rejected: aceptar el estado sin actuar — el PR quedaría con rango no revisado y la próxima iteración de validate-ship fallaría en silencio.

### D12 — Diagram del state machine con el nuevo self-loop, en SVG junto a design.md

**Chosen:** Generar `sdd/changes/post-pr-recertification/lifecycle-states.svg` con el state machine ACTIVE → LOCAL_VERIFIED → READY_FOR_PR → PR_OPEN → MERGED → ARCHIVED, los laterales (CANCELLED, BLOCKED) y el self-loop `PR_OPEN → PR_OPEN` etiquetado "recertify" destacado visualmente. Referenciado desde este design.

Rejected: ASCII art en el design — el SVG se renderiza inline en GitHub y difs limpio; ASCII se descolora y rompe review.

### D13 — Tests en `tests/test_sdd_lifecycle.py`, no en archivo nuevo

**Chosen:** Nueva clase `LifecycleRecertifyTests` en el módulo existente, junto a `SyncBaseTests` y `PublishArchiveTests`. Reutiliza el `setUp` (`temporary` repo, fixture git, PR payload faked). Añadir 3 tests contractuales a `tests/test_lifecycle_contract.py` (review PR_OPEN branch, ship PR_OPEN rejection, auto resuming).

Rejected: `tests/test_sdd_recertify.py` — los tests del lifecycle viven juntos en `test_sdd_lifecycle.py` (mirror de `SyncBaseTests`); separarlos rompe el patrón del archivo.

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