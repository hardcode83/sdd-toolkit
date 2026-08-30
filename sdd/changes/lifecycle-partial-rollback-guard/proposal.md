# Proposal: lifecycle-partial-rollback-guard

## Why

En SDD Toolkit 0.40.0 se reprodujo una corrupción de la secuencia lifecycle
cuando `mark-local-verified` actualiza `STATE.md`, falla al crear su commit por
un error del índice compartido y el rollback queda incompleto. Un `mark-ready`
posterior puede consumir ese estado local no materializado y crear un único
commit cuyo subject declara `LOCAL_VERIFIED->READY_FOR_PR`, aunque su parent
Git todavía contiene `ACTIVE`; `validate-ship` detecta correctamente la
inconsistencia, pero demasiado tarde. La comprobación remota de la branch del
change no pudo completarse por un fallo DNS hacia GitHub; este change se crea
desde el `main` local actual (`60189ef`) y no depende de validación remota.

La verificación inicial también necesitó el prerequisite independiente
`feb2204` (`test: make ACL cleanup regression deterministic`) para estabilizar
una regresión ambiental de `tests/test_sdd_session.py`. Ese commit permanece
fuera del alcance funcional de este change y no modifica lifecycle; se conserva
como antecedente ya existente, sin reescribir historia, mientras este review
evalúa exclusivamente la implementación lifecycle y sus artefactos SDD.

## What changes

El lifecycle validará la continuidad entre el estado local y el `STATE.md` del
parent Git antes de materializar una transición, y hará que cualquier fallo de
commit o rollback deje el change bloqueado de forma segura, sin permitir que
un comando posterior interprete metadata local parcial como certificada. Se
mantendrá intacta la validación estricta de `validate-ship`, la secuencia
normal `ACTIVE -> LOCAL_VERIFIED -> READY_FOR_PR` y la prohibición de editar
manualmente `STATE.md`; se añadirá cobertura explícita para commit failure,
rollback incompleto y posterior intento de `mark-ready`.

## Requirements

### R1 — Guardar continuidad del estado lifecycle

**As a** mantenedor del toolkit, **I want** cada transición lifecycle validada
contra el estado materializado en Git, **so that** los subjects de los commits
no puedan ocultar saltos de estado.

Acceptance criteria:

1. WHEN `mark-ready` intenta materializar `LOCAL_VERIFIED -> READY_FOR_PR`,
   THE SYSTEM SHALL comprobar que el `STATE.md` del parent Git está en
   `LOCAL_VERIFIED` y rechazar la operación si está en cualquier otro estado.
2. WHEN cualquier comando lifecycle prepara una transición, THE SYSTEM SHALL
   usar como precondición el estado del parent Git además del estado local.
3. IF el estado local y el estado del parent Git divergen, THEN THE SYSTEM
   SHALL fallar cerrado sin crear un commit lifecycle ni avanzar el estado.

### R2 — Rollback seguro ante fallo de commit

**As a** mantenedor del toolkit, **I want** los fallos de persistencia y
rollback tratados como errores bloqueantes, **so that** ningún estado parcial
pueda consumirse como certificado.

Acceptance criteria:

1. WHEN `lifecycle_commit()` falla al crear el commit y no puede restaurar
   completamente staging o `STATE.md`, THE SYSTEM SHALL devolver un error
   explícito de rollback incompleto y SHALL NOT dejar una ruta de continuación
   que trate el estado local como materializado.
2. WHEN un comando lifecycle posterior encuentra un `STATE.md` local no
   materializado respecto a su parent Git, THE SYSTEM SHALL rechazarlo antes de
   escribir o crear otro commit.
3. THE SYSTEM SHALL preserve user-owned changes and SHALL NOT silently overwrite
   una edición manual de `STATE.md`.

### R3 — Preservar la secuencia normal y el gate de ship

**As a** usuario del workflow SDD, **I want** el flujo lifecycle válido sin
   cambios semánticos, **so that** las certificaciones existentes sigan siendo
   compatibles.

Acceptance criteria:

1. WHEN `mark-local-verified` y luego `mark-ready` completan normalmente, THE
   SYSTEM SHALL crear dos commits lifecycle consecutivos:
   `ACTIVE -> LOCAL_VERIFIED` y `LOCAL_VERIFIED -> READY_FOR_PR`.
2. THE SYSTEM SHALL NOT relajar, saltar ni modificar las comprobaciones de
   `classify_lifecycle_commit` o `validate_ship_suffix`.
3. IF la continuidad lifecycle no puede demostrarse, THEN `validate-ship`
   SHALL continue to reject the suffix rather than accepting an inferred state.

### R4 — Cobertura de regresión y diagnóstico

**As a** mantenedor del toolkit, **I want** una prueba reproducible del fallo
   parcial, **so that** futuras refactorizaciones no reintroduzcan el bug.

Acceptance criteria:

1. THE SYSTEM SHALL provide a deterministic test covering commit failure,
   incomplete rollback, and a subsequent `mark-ready` attempt, asserting that
   no invalid combined lifecycle commit is created.
2. THE SYSTEM SHALL retain the existing tests
   `test_mark_ready_commits_state_only_with_stable_anchor` and
   `test_complete_permitted_transition_sequence` as coverage for the normal
   two-commit sequence.
3. THE SYSTEM SHALL expose an actionable error identifying the conflicting
   local/parent state or incomplete rollback.

## Out of scope

- Cambiar `validate-ship` para aceptar o reparar commits lifecycle inválidos.
- Reescribir, amend, rebasear o resetear commits ya creados.
- Modificar la semántica de `ACTIVE -> LOCAL_VERIFIED -> READY_FOR_PR` cuando
  la persistencia funciona normalmente.
- Reintroducir el workaround ACL de `tests/test_sdd_session.py`; su flakiness
  es ambiental y ajena a este change.
- Cambiar `STATE.md` manualmente, el esquema lifecycle, la publicación PR o
  cualquier lógica de reviewer-panel.
- Resolver la comprobación remota fallida por DNS o añadir validación remota.

## Affected specs

- `sdd/specs/lifecycle-states.md` — documentar la precondición de continuidad
  parent/local y el bloqueo ante rollback incompleto.
- `sdd/specs/lifecycle-implementation-anchor.md` — documentar que el anchor y
  la transición solo se materializan desde un parent Git coherente.
