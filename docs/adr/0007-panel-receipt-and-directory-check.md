# ADR 0007 — El veredicto del panel es un recibo en disco; el check de aislamiento describe el directorio

- **Fecha**: 2026-09-06
- **Estado**: aceptada
- **Alcance**: `scripts/reviewer_panel.py` (recibo, `--carry`) ·
  `scripts/sdd_lifecycle.py` (`ensure_panel_receipt` en `mark-local-verified` y
  `mark-recertified`, subcomando `receipt`) · `scripts/sdd_session.py`
  (`check` por directorio, `feature_worktrees`, `WORK HERE` en worktree
  enlazado bajo `isolation: always`) · `agents/sdd-*.md` (`maxTurns`) ·
  `skills/review`, `ship`, `run`, `reviewer-panel` · regla compartida 10 y 11 ·
  `references/isolation.md` · `tests/test_panel_receipt.py` (nuevo)
- **Revisa**: ADR 0002 (política de aislamiento: qué es "evidencia" de
  conflicto) y ADR 0003 D4 (`maxTurns` 30/30/40 y "un parcial es no-PASS").
- **Continúa**: ADR 0005 y 0006 (validación de auto).

## Contexto

Depuración pedida por el usuario sobre `auth-session-persistence` (AutoHostAI,
3–5 sep, v0.44.0): "el panel y los tests se corren demasiadas veces", "creo que
el flujo abre otro worktree además del de Orca", "ship me tira el panel". Los
mismos patrones aparecen en `frontend-verification-fixes`.

## Evidencia

### El panel se repetía porque el veredicto no llegaba a disco

| hecho | medida |
|---|---|
| Coste de la feature | 169 $, de los que **101 $ review**; `STATE.md` aún `ACTIVE` sin `implementation_sha` |
| Paneles a escala feature | 8 forks × 7 revisores; QA ejecutando las suites completas de backend y frontend cada vez (25 ejecuciones de tests en review, 26 en run) |
| Cómo acababa cada fork | 6 de 6: lanzaba los 7 en background y terminaba el turno "esperando notificaciones"; **0 llamadas a `sdd_lifecycle.py`** en los 8 forks |
| Qué hacía ship | encontraba `ACTIVE` y, por su paso 1, devolvía a `/sdd:review`; review fresco = otros 7 revisores. En `frontend-verification-fixes`: tres forks de review 18:30–18:56, ship 19:17 "cannot proceed", review 19:18 |
| Cortes por límite de turnos (desde el 1 sep) | 24 en 11 sesiones; **15 son `sdd-qa`** (`maxTurns: 40`). QA a escala feature: mediana 76 turnos, p90 109, máx 148; por sección: mediana 44, p90 77 |
| Re-reviews en el corpus | 52 de 84 features con más de una sesión de review; 1.905 $ de 3.291 $ de review fueron re-review (ADR 0006, adenda) |

Nada del veredicto por revisor persistía: a diferencia del `panel: PASS` por
sección de `run`, un fork nuevo de review no podía ser incremental y relanzaba
los siete aunque seis ya hubieran dado PASS y solo hubiera cambiado un
documento.

### El doble worktree tenía causa en código

La sesión de `/sdd:new` la abrió Orca en su worktree enlazado, limpio, en rama
`hardcode83/auth-session-persistence`. `sdd_session.py check` devolvió
`CONFLICT` porque el registro compartido (`.git/sdd/sessions.json`) listaba
**otras cuatro sesiones vivas en otros cuatro worktrees**, e `ISOLATE` creó
`.claude/worktrees/sdd+auth-session-persistence`. Desde entonces la feature
tuvo dos directorios, dos stacks de Docker y dos carpetas de transcripts; con
cinco features así, el host se quedó sin memoria y bloqueó la tarea manual de
`reservations-identity-web`. El check contaba sesiones del clon cuando la
pregunta de la regla 10 es sobre **este directorio**: otra sesión en otro
worktree no comparte este HEAD.

## Decisiones

### D1 — `reviewer_panel.py` escribe un recibo en el directorio git común

Cada evaluación a escala feature (`review`, `auto`) deja
`<git common dir>/sdd/receipts/<feature>.json`: fase, `scope_id`, HEAD juzgado,
gate, errores y una fila por revisor (veredicto, estado, nº de findings y, para
un PASS, el sobre completo). Vive junto al registro de sesiones: estado de
máquina compartido por todos los worktrees e invisible para `git status` — un
fichero dentro de `sdd/changes/` habría ensuciado el árbol que el commit
STATE-only del lifecycle exige limpio. `run` no escribe recibo: su registro es
la anotación por sección en `tasks.md`.

Descartado: el recibo dentro de `sdd/changes/<feature>/` (rompe la allowlist
del lifecycle y obliga a comitearlo en cada panel) y meter los veredictos en
`STATE.md` (un fichero de estado de lifecycle, no de evidencia).

### D2 — Sin recibo PASS en HEAD no hay hito

`mark-local-verified` y `mark-recertified` llaman a `ensure_panel_receipt`:
recibo presente, fase `review`/`auto`, `gate: PASS` y `sha == HEAD`. El
mensaje de error nombra el arreglo (relanzar el panel; `--carry` si solo
cambiaron documentos). "El panel pasó" en prosa deja de ser un veredicto; el
recibo es el enlace mecánico entre el panel y la certificación que la regla 11
daba por supuesto y que ocho paneles demostraron que no existía.

### D3 — Re-review incremental con `--carry`

`reviewer_panel.py --carry` reutiliza los sobres PASS del recibo anterior para
los revisores que no van en `--results`, **solo** si el commit del recibo es
ancestro de HEAD y el diff desde él no toca código (`sdd/`, `docs/`,
markdown, imágenes). Si cambió código, se niega nombrando las rutas: un PASS
sobre otro código no es un PASS sobre este. La skill de review relanza solo los
revisores que no pasaron, acotados a `<sha del recibo>..HEAD`.

### D4 — Un revisor cortado se relanza solo; los topes suben a lo medido

`maxTurns`: QA 40 → 100, architect y security 30 → 60. El tope duro se dimensiona
con el p90 medido a escala feature; el presupuesto blando por sección (~25/~35
llamadas) se mantiene en la prosa del agente. En cualquier fase, un revisor
cortado se relanza **solo** con su informe parcial y "continúa desde lo que
establecistes"; nunca se relanza el panel. Un parcial sigue siendo no-PASS para
el gate (ADR 0003 D4 no cambia).

### D5 — Ship certifica desde el recibo en vez de devolver a review

En `ACTIVE`/`LOCAL_VERIFIED`, ship ejecuta `sdd_lifecycle.py receipt <feature>`:
`CERTIFIES_HEAD` → registra `mark-local-verified` y `mark-ready` él mismo (base
de `STATE.md`, o la rama por defecto del remoto, o `main`) y sigue, sin
humano; `STALE_OR_MISSING` → `/sdd:review`. Es la conversión del bucle
ship → review → panel → ship en un paso determinista, y la forma del mandato
del usuario para esta ola: el humano solo cuando hay una `decision`.

### D6 — `check` describe este directorio, y un worktree enlazado ya es el aislamiento

Otra sesión viva cuenta como conflicto **solo** si su worktree registrado es
este mismo directorio; las demás se listan como información ("not a conflict
here"). `isolate = conflicto or (always and not in_linked_worktree)`: bajo
`isolation: always`, una sesión ya en un worktree enlazado obtiene `WORK HERE —
this linked worktree already is the isolation the project declares`.
`feature_worktrees` recorre `git worktree list` y `check` avisa (`NOTE … never
a third`) cuando la feature ya tiene otro worktree, por nombre de rama
(`sdd/<feature>` o `<algo>/<feature>`, que cubre la convención de Orca).

Descartado: un código del doctor para el worktree duplicado — es estado de
máquina, no del proyecto comiteado, y los fixtures del doctor son árboles
comiteados (la misma razón por la que `orphans` vive en `sdd_session.py`).

### D7 — Codex

Recibo, `--carry`, `receipt` y el check por directorio son Python de la
biblioteca estándar; el handoff nativo de Codex pasa por el mismo
`reviewer_panel.py` y deja el mismo recibo.

## Consecuencias

- Un panel que pasa certifica **siempre** (recibo + hito en el mismo turno), y
  un panel que pasó no se repite sobre el mismo HEAD. Estimación sobre el caso
  medido: 6 paneles × 7 → 1 × 7 + 5 × (1–2 revisores).
- QA deja de cortarse en el caso normal (p90 109 < 100 seguirá cortando el
  decil alto: se relanza solo, no el panel). Pendiente para otra ola: QA
  ejecutando la suite acotada al change y leyendo la evidencia de la suite
  completa registrada en verificación.
- Una sesión en un worktree de Orca trabaja donde está. Las features que ya
  tienen dos worktrees los conservan hasta que alguien retire uno; el check lo
  dice en cada fase.
- Pendiente (segunda PR de esta depuración): `preflight-archive` y la
  re-atribución de métricas por sesión en `usage-sync`.

## Implementación

Se entrega con v0.50.0. `scripts/reviewer_panel.py`, `scripts/sdd_lifecycle.py`,
`scripts/sdd_session.py`, `agents/sdd-*.md`, las skills citadas, `rules.md`,
`references/isolation.md`, `tests/test_panel_receipt.py` (11 tests),
`tests/test_sdd_session.py` (+3, 1 reescrito), `tests/test_blocked_queue.py`,
`tests/test_decisions_contract.py` (+4), `README.md`, `docs/faq.md`,
`docs/guide.md`, `docs/codex.md`.
