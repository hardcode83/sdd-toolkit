# Proposal: post-pr-recertification

## Why

Reproducido en AutoHostAI: un cambio que ya pasó por `ACTIVE → LOCAL_VERIFIED → READY_FOR_PR → PR_OPEN` recibe un defecto en code review remoto, se añade un commit funcional a la rama del PR y `implementation_sha` queda obsoleto. Los comandos actuales del lifecycle (`mark-local-verified`, `mark-ready`, `record-pr`) **no pueden re-anclar el SHA desde `PR_OPEN`**: el primero rechaza por estado, el segundo es no-op idempotente, el tercero no toca `implementation_sha`. `validate_ship_suffix` rechaza correctamente el commit funcional nuevo (no es lifecycle, ni `sync-base`), pero **no existe ningún flujo soportado para re-certificar el mismo PR** — sólo queda editar `STATE.md` a mano (prohibido por las invariantes del lifecycle) o forzar push (prohibido por las reglas del toolkit). El bug es un gap real del lifecycle, no un caso de uso que los comandos cubran "a medias".

## What changes

Aparece un comando nuevo `mark-recertified` en `scripts/sdd_lifecycle.py` que, desde `state: PR_OPEN`, re-ancla `implementation_sha` al HEAD funcional revisado mediante un commit lifecycle **STATE-only** con transición self-loop `PR_OPEN → PR_OPEN`. El comando preserva `repository`, `base_branch`, `head_branch`, `pr_number`, `pr_url`, `pr_state`, `local_review` y rechaza force-push, MERGED, CLOSED y estados distintos a `PR_OPEN`. La rama de recertificación del flujo vive en `/sdd:review <feature>` cuando detecta `state == PR_OPEN`; `/sdd:ship` en `PR_OPEN` con `HEAD != implementation_sha` deja de ser ambiguo y redirige a review. `validate_ship_suffix`, `record-pr` y `mark-ready` no se modifican funcionalmente: el suffix tras recertificar sigue siendo lifecycle-only por construcción.

## Requirements

### R1 — Comando `mark-recertified` re-ancla `implementation_sha` desde `PR_OPEN`

**As a** mantenedor del cambio en `PR_OPEN`, **I want** un comando soportado que re-ancle `implementation_sha` al HEAD funcional revisado del mismo PR, **so that** pueda cerrar defectos de code review remoto sin editar `STATE.md` a mano ni forzar push.

Acceptance criteria:

1. WHEN el usuario ejecuta `python3 scripts/sdd_lifecycle.py --root . mark-recertified <feature>` con `state: PR_OPEN` y `HEAD ≠ implementation_sha`, THE SYSTEM SHALL escribir un commit lifecycle STATE-only de transición `PR_OPEN → PR_OPEN` cuyo `STATE.md` registra `implementation_sha = parent del commit` (= HEAD funcional revisado) y preserva `repository`, `base_branch`, `head_branch`, `pr_number`, `pr_url`, `pr_state`, `local_review` sin cambios.
2. IF el PR registrado en `STATE.md` ya no está `OPEN` (es `MERGED` o `CLOSED`), THEN THE SYSTEM SHALL abortar con un `LifecycleError` que nombra el estado real de GitHub y, para `CLOSED`-sin-merge, sugiere reabrir o abrir PR nuevo vía `/sdd:ship`.
3. IF `implementation_sha` registrado no es ancestro del HEAD actual (force-push o rebase destructivo), THEN THE SYSTEM SHALL abortar con `LifecycleError` indicando que la rama no se puede re-anclar tras force-push.
4. IF HEAD actual no aparece en `commits[]` de `gh pr view <recorded pr_url>`, THEN THE SYSTEM SHALL abortar con `LifecycleError` indicando que el commit no está pusheado y el usuario debe ejecutar `git push origin <head_branch>` antes de recertificar.
5. WHEN el comando termina con éxito, THE SYSTEM SHALL garantizar que `validate_ship_suffix` acepta el nuevo suffix (un único commit lifecycle) sin relajar ninguna regla existente.

### R2 — La transición `PR_OPEN → PR_OPEN` queda registrada como válida en el clasificador de lifecycle commits

**As a** validador del lifecycle, **I want** que `classify_lifecycle_commit` reconozca la transición self-loop `PR_OPEN → PR_OPEN`, **so that** un commit recertify sea clasificable sin relajar las reglas generales ni permitir manipulación manual del ancla.

Acceptance criteria:

1. WHEN `classify_lifecycle_commit` examina un commit cuyo subject es `chore(sdd): lifecycle <feature> PR_OPEN->PR_OPEN` y cuyo diff toca únicamente `sdd/changes/<feature>/STATE.md`, THE SYSTEM SHALL aceptarlo como lifecycle válido.
2. IF el commit dice `PR_OPEN->PR_OPEN` pero `child_state.implementation_sha ≠ parent_sha` (es decir, el commit no re-ancla al HEAD revisado), THEN THE SYSTEM SHALL rechazar con `LifecycleError` indicando la regla violada.
3. IF el commit dice `PR_OPEN->PR_OPEN` pero `parent_state.implementation_sha == parent_sha` (es decir, no hay cambio real del ancla), THEN THE SYSTEM SHALL rechazar con `LifecycleError` indicando que recertificar requiere un cambio real del ancla.
4. THE SYSTEM SHALL preservar el guard existente `commit in child_text` (l. 697) que rechaza auto-referenciar el propio SHA en `STATE.md` — el recertify nunca escribe su propio SHA, escribe el de su parent.

### R3 — `LIFECYCLE_TRANSITIONS` admite la transición self-loop sin debilitar las existentes

**As a** mantenedor del state machine, **I want** añadir `("PR_OPEN", "PR_OPEN")` al set `LIFECYCLE_TRANSITIONS`, **so that** la nueva transición sea autorizada sin tener que tocar los demás pares.

Acceptance criteria:

1. THE SYSTEM SHALL seguir rechazando transiciones no listadas (`LIFECYCLE_TRANSITIONS` actúa como allowlist).
2. THE SYSTEM SHALL seguir rechazando cambios de `implementation_sha` por cualquier commit lifecycle que **no** sea `READY_FOR_PR` (mantiene ancla), `LOCAL_VERIFIED` (la captura desde `ACTIVE`) o `PR_OPEN->PR_OPEN` (recertify).
3. THE SYSTEM SHALL seguir tratando `STATE.md` como el único path modificable por commits lifecycle (paths allowlist, igual que ahora).

### R4 — El comando es idempotente y soporta múltiples ciclos sobre el mismo PR

**As a** usuario que itera varias rondas de fix sobre el mismo PR, **I want** que `mark-recertified` sea no-op cuando no hay nuevos commits y permita N ciclos de recertificación encadenados, **so that** el flujo no rompa con re-fixes sucesivos ni requiera limpieza manual entre rondas.

Acceptance criteria:

1. IF `HEAD == implementation_sha` registrado y `state == PR_OPEN`, WHEN el usuario ejecuta `mark-recertified`, THEN THE SYSTEM SHALL devolver un mensaje explícito de "no-op; nada que recertificar" sin crear commit lifecycle y sin tocar `STATE.md`.
2. WHEN el usuario encadena dos ciclos (fix1 → recertify1 → fix2 → recertify2), THE SYSTEM SHALL registrar dos commits `PR_OPEN->PR_OPEN` consecutivos, con `implementation_sha` final apuntando al último HEAD revisado y `pr_url`/`pr_number`/`pr_state` constantes.
3. WHEN se ejecutan múltiples invocaciones de `mark-recertified` sin nuevos commits entremedias, THE SYSTEM SHALL producir cero commits adicionales (idempotencia).
4. WHEN tras N ciclos de recertificación se ejecuta `validate_ship_suffix`, THE SYSTEM SHALL pasar aceptando únicamente los commits lifecycle `PR_OPEN->PR_OPEN` en cada suffix, sin relajar la regla.

### R5 — `mark-recertified` rechaza desde cualquier estado distinto a `PR_OPEN`

**As a** validador de integridad del lifecycle, **I want** que sólo `PR_OPEN` pueda recertificar, **so that** los demás estados (`ACTIVE`, `LOCAL_VERIFIED`, `READY_FOR_PR`, `MERGED`, `ARCHIVED`, `CANCELLED`) permanezcan inmutables y no se "cuelen" re-anclajes espurios.

Acceptance criteria:

1. IF `state ∉ {PR_OPEN}` cuando se invoca `mark-recertified`, THEN THE SYSTEM SHALL abortar con `LifecycleError` indicando el estado actual y el comando correcto para el estado real.
2. IF existe `BLOCKED.md` no vacío en `sdd/changes/<feature>/`, THEN THE SYSTEM SHALL abortar con `LifecycleError` (gate existente en `ensure_local_gates`).
3. IF `tasks.md` tiene tareas sin marcar, THEN THE SYSTEM SHALL abortar (gate existente).
4. IF `local_review ≠ APPROVED` en `STATE.md`, THEN THE SYSTEM SHALL abortar (gate existente en `require_merge` y en la nueva función).
5. IF el working tree tiene cambios fuera de `sdd/changes/<feature>/STATE.md` (untracked, modified o staged), THEN THE SYSTEM SHALL abortar sin modificar nada (regla `ensure_clean_or_only_expected_state`).

### R6 — `/sdd:review` bifurca a recertificación cuando `state == PR_OPEN`

**As a** usuario que detecta un defecto tras abrir el PR, **I want** que `/sdd:review <feature>` reconozca `PR_OPEN` y aplique la rama de recertificación, **so that** el panel se ejecute sobre el rango `old_anchor..HEAD` y el comando adecuado cierre el ciclo.

Acceptance criteria:

1. WHEN `/sdd:review <feature>` se invoca con `state: PR_OPEN`, THE SYSTEM SHALL lanzar el panel sobre el rango `implementation_sha..HEAD` (no sobre la rama completa) y, en PASS, llamar a `mark-recertified` en lugar de la pareja `mark-local-verified + mark-ready`.
2. WHEN `/sdd:review <feature>` se invoca con `state: ACTIVE` o `LOCAL_VERIFIED`, THE SYSTEM SHALL mantener el flujo actual (`mark-local-verified`, `mark-ready`, `validate-ship`).
3. WHEN el panel reporta FAIL persistente tras dos rondas, THE SYSTEM SHALL mantener la regla "two fix rounds, then stop and hand it to the user" (`skills/review/SKILL.md` l. 94-98).
4. THE SYSTEM SHALL documentar en `skills/review/SKILL.md` que un commit de fix tras `PR_OPEN` requiere pushear antes de invocar `/sdd:review`, para que la recertificación encuentre el commit en `commits[]` del PR.

### R7 — `/sdd:ship` en `PR_OPEN` con `HEAD != implementation_sha` redirige sin mezclarse

**As a** usuario que ejecuta `/sdd:ship` por inercia, **I want** que el skill rechace cuando hay un fix no anclado y apunte a `/sdd:review`, **so that** ship no re-anchore ni publique un PR con rango no revisado.

Acceptance criteria:

1. WHEN `/sdd:ship <feature>` se invoca con `state: PR_OPEN` y `HEAD != implementation_sha`, THE SYSTEM SHALL abortar con un mensaje accionable que dice "ejecuta `/sdd:review <feature>` para recertificar el fix" y no invocar `sync-base`, `gh pr create`, ni `record-pr`.
2. WHEN `/sdd:ship <feature>` se invoca con `state: PR_OPEN` y `HEAD == implementation_sha`, THE SYSTEM SHALL mantener el comportamiento actual (`sync-base` opcional + `record-pr` idempotente).
3. THE SYSTEM SHALL NO modificar funcionalmente `sync-base`, `record-pr`, `mark-ready`, `validate_ship_suffix`, `require_merge` ni `publish_archive`.

## Out of scope

- **Nuevos estados lifecycle** (`PR_REVIEW`, `PR_RECERTIFIED`, etc.). La recertificación se modela como self-loop `PR_OPEN → PR_OPEN`; el estado canónico no cambia.
- **Cambios funcionales en `record-pr` o `mark-ready`**. Sólo se ajustará su documentación si una nota en el docstring lo requiere para mantener coherencia con el nuevo flujo.
- **Relajar `validate_ship_suffix`**. El suffix tras recertificar es lifecycle-only por construcción; ningún commit funcional llega al rango nuevo.
- **Manipulación manual de `STATE.md`**. El guard `commit in child_text` y el allowlist de paths siguen activos; editar a mano sigue dando error en `validate_ship_suffix`.
- **Recertificar PR cerrado o mergeado**. `MERGED` y `CLOSED` rechazan; para `MERGED` el camino es `/sdd:archive`, para `CLOSED`-sin-merge el camino es reabrir o abrir PR nuevo vía `/sdd:ship`.
- **Push automático desde `mark-recertified`**. El push sigue siendo responsabilidad de ship; el usuario ejecuta `git push origin <head_branch>` antes de `/sdd:review` cuando hay un fix.
- **Cambios ajenos al lifecycle post-PR**: `scripts/sdd_session.py`, `scripts/sdd-doctor.py`, `scripts/sdd_roadmap.py`, `scripts/sdd_session.py`, `templates/`, `rules.md`, `docs/`, `references/`, `skills/status`, `skills/auto`, `skills/archive` (salvo nota documental) — nada de esto entra en el alcance.

## Affected specs

- `sdd/specs/lifecycle-states.md` *(no existe aún — se creará al archivar)*: documenta formalmente el self-loop `PR_OPEN → PR_OPEN` y la regla "sólo recertifica `PR_OPEN`".
- `sdd/specs/lifecycle-implementation-anchor.md` *(no existe aún — se creará al archivar)*: formaliza que `implementation_sha` cambia exclusivamente desde `LOCAL_VERIFIED`, `READY_FOR_PR` y `PR_OPEN->PR_OPEN` (recertify), y nunca por edición manual.
- `sdd/specs/ship-and-review-contract.md` *(no existe aún — se creará al archivar)*: refleja que `/sdd:ship` en `PR_OPEN` con `HEAD != implementation_sha` redirige a `/sdd:review`, y que `/sdd:review` bifurca a recertificación cuando `state == PR_OPEN`.
