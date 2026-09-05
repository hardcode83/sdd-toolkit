# ADR 0005 — La receta headless de `/sdd:auto`: permisos que funcionan sin nadie delante y un veredicto por sesión

- **Fecha**: 2026-09-05
- **Estado**: aceptada (ola A1 de la validación de auto)
- **Alcance**: `skills/auto/SKILL.md` (sección "The headless recipe", pasos
  "One session per feature" y 6) · `scripts/sdd_auto_outcome.py` (nuevo) ·
  `tests/test_sdd_auto_outcome.py` (nuevo) · regla compartida 11 ·
  `references/context-budget.md` · `README.md`, `docs/guide.md`,
  `docs/faq.md`, `docs/codex.md`
- **Revisa**: la receta de lanzamiento desatendido que el README y la skill
  llevaban desde v0.3x (`claude -p "/sdd:auto 2" --permission-mode acceptEdits`).
- **Continúa**: [ADR 0003](0003-forked-phases.md) (fases en fork) y
  [ADR 0004](0004-run-orchestrator.md) (run como orquestador). Abre la serie de
  la validación de auto; las olas A2 (driver por fases) y A3 (decisiones en
  tres niveles) tendrán su propio ADR.

## Contexto

`/sdd:auto` es la razón de ser del flujo: features del roadmap hasta PR sin
intervención. La skill delega cada feature (con `N > 1`) y siempre la review en
una sesión `claude -p` fresca (regla 11), leyendo el resultado de `STATE.md` y
no de la prosa. Al validar el modo auto sobre el proyecto que más lo necesita
(AutoHostAI, 80 features) apareció algo anterior a cualquier discusión sobre
decisiones o contexto: **auto no había completado nunca una feature**.

## Evidencia

### Las ejecuciones reales

Transcripts de AutoHostAI: tres invocaciones de `/sdd:auto` en total, las tres
el 2026-08-22 con v0.37.0, en Sonnet 5.

| sesión | duración | cómo acabó |
|---|---|---|
| `properties-web` (clon principal) | 32 s | «This command requires approval» × 4 sobre `sdd_roadmap.py validate` / `frontier`; pide al usuario cambiar de modo |
| `timeline-web` | 73 s | mismo bloqueo; intenta `rtk proxy python3 …`, denegado |
| `properties-web` (worktree) | 61 s | llega al bootstrap; `make up` muere con exit 137 |

Ninguna llegó a `/sdd:new`. El log OTel (`.sdd-usage/otel.jsonl`, 398k
datapoints desde el 5 de agosto) atribuye **0 $** a la fase `auto`.

### Los modos de permiso en headless (Claude Code 2.1.261, medido el 2026-09-05)

Comandos de prueba: `python3 -c 'print(6*7)'` y
`python3 <toolkit>/scripts/sdd_roadmap.py --root . validate`, lanzados con
`claude -p … --output-format json` desde una sesión de Claude Code (anidado).

| invocación | resultado |
|---|---|
| `--permission-mode acceptEdits` | denegado (`permission_denials` = 1). Aprueba ediciones y `mkdir`/`mv`/`cp`/`sed`, no otros comandos |
| `--permission-mode dontAsk` | denegado: solo pasa lo que esté en `permissions.allow` |
| `--permission-mode auto --model haiku` | el evento `init` reporta `permissionMode = default`: el modo auto no está disponible para Haiku y la sesión cae a Manual **sin aviso** → denegado |
| `--permission-mode auto --model sonnet` | `permissionMode = auto`: el clasificador aprueba el script del toolkit, 0 denegaciones (igual con Opus, y también fuera de la sesión anidada) |
| `--permission-mode acceptEdits --allowedTools "Bash(python3 *)"` | aprobado (regla de prefijo) |
| `--permission-prompts none` | quita `AskUserQuestion` de la sesión; lo que habría preguntado se deniega sin esperar y el modelo recibe «do not retry» |
| `--json-schema '{…}'` | `structured_output` con el objeto validado |

Dos hechos más de la documentación oficial: en `-p` el modo de arranque es
Manual **en todos los planes** (hay que pedir el modo explícitamente), y
`--bare` no lee OAuth ni el keychain (exige `ANTHROPIC_API_KEY`), así que no
sirve para una sesión que debe cargar el plugin y autenticar con la suscripción.

### Lo que la delegación no daba

El orquestador leía el resultado de la sub-sesión «de disco», pero no tenía
forma de distinguir un fallo de permisos de un fallo de la fase: ambos acababan
en «cualquier otro resultado es un veredicto fallido: BLOCK». Una denegación de
permisos no es una decisión que un humano deba tomar; es una regla que falta, y
el humano necesita el comando exacto para añadirla.

## Decisiones

### D1 — La receta vive en un script, no en prosa

`scripts/sdd_auto_outcome.py run "<prompt>" --cwd <dir>` construye y lanza el
`claude -p`. Un solo hogar (regla 1 del toolkit: lo determinista en Python
testeable, el juicio en las skills) y un test que fija cada flag. La skill deja
de escribir la línea de comandos; escribe la llamada al script.

Descartado: mantener la receta en la skill y el README (dos copias que ya
habían divergido de la realidad medida) o un hook `PermissionRequest` del
plugin que auto-apruebe los scripts (el plugin retiró sus hooks por el coste
fijo por request; las reglas de permiso y el clasificador hacen lo mismo sin
coste).

### D2 — `--permission-mode auto --permission-prompts none`, Sonnet u Opus, nunca Haiku

Es la única combinación medida que ejecuta los scripts del toolkit, git y los
tests del proyecto sin allowlist y sin nadie delante, conservando los bloqueos
del clasificador (force-push, exfiltración, despliegues). `--permission-prompts
none` convierte «auto nunca pregunta» en mecánica: la herramienta de preguntar
no existe en la sesión. El script **se niega** a lanzar con Haiku como modelo de
sesión, porque el fallo es silencioso y total.

Descartado: `dontAsk` + allowlist (`Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/*)`,
`Bash(git *)`, `Bash(gh pr *)`, tests del proyecto). Funciona y es más rígido,
pero exige mantener la lista por proyecto y falla en el primer comando que nadie
previó; queda documentado como alternativa para CI cerrado, no como default.
`bypassPermissions` solo tiene sentido en contenedor y no se recomienda.

### D3 — La sub-sesión termina en un objeto de veredicto, y la última línea del script es el veredicto

`--json-schema` obliga a la fase a acabar con `{outcome: PASS|BLOCKED|FAILED,
next_command, decisions[], summary}`. El script lo cruza con
`permission_denials`, `is_error`/`terminal_reason` y la presencia del propio
objeto, y devuelve una de siete clases en su última línea `AUTO_OUTCOME:` —
la misma convención de «obedece la última línea» que ya usa
`sdd_session.py check`:

| clase | origen | lo que hace auto |
|---|---|---|
| `PASS` / `BLOCKED` / `FAILED` | el objeto de veredicto | confirmar en disco y seguir / adoptar el bloqueo / bloquear |
| `DENIED` | `permission_denials` no vacío (gana sobre un PASS declarado) | entrada `deferred` con los comandos exactos denegados; no es una decisión |
| `ERROR` | `is_error` o `terminal_reason` distinto de `completed` | reintentar una vez; después `deferred` con la razón |
| `INCOMPLETE` | sin objeto de veredicto | leer el disco; si no prueba el hito, `FAILED` |
| `UNAVAILABLE` | sin `claude` en PATH o no arranca | ejecutar la fase inline y decirlo en el informe |

La regla 8 sigue mandando: un `PASS` que el disco no confirma es `FAILED`. El
objeto es el resumen de la sub-sesión; `STATE.md`, `BLOCKED.md` y `tasks.md`
son los hechos.

### D4 — Señal de «corro bajo auto» para las fases delegadas

Una sesión `-p` que ejecuta `/sdd:review <feature>` no sabe que la lanzó auto,
y las skills tienen cláusulas «under `/sdd:auto`». El script exporta
`SDD_AUTO_DELEGATED=1` (el guard existente contra la delegación recursiva) y
`SDD_AUTO=1`, y añade un `--append-system-prompt` con las conversiones de gate.
La regla 11 lo consagra: cualquier «under `/sdd:auto`» aplica cuando la variable
está presente.

### D5 — Codex sigue siendo compatible

Sin `claude`, el script devuelve `UNAVAILABLE` y auto ejecuta la fase inline:
exactamente el fallback que ya estaba documentado para review. `docs/codex.md`
lo anota.

## Consecuencias

- `/sdd:auto` pasa de no poder arrancar a poder completar una feature
  desatendido. No hay medida de coste de una feature completa en auto todavía;
  la primera la dará `usage-sync.py report` sobre una feature pequeña de
  AutoHostAI, y es el prerequisito de la ola A3.
- El clasificador del modo auto es ahora parte del contrato de auto: lo que él
  bloquee aparece como `DENIED` con el comando exacto, y el proyecto lo resuelve
  con `autoMode.environment` o una regla `permissions.allow`, no con un cambio en
  el toolkit. Un proyecto que quiera un checkpoint humano antes del PR pone
  `permissions.ask: ["Bash(gh pr create *)"]`; en headless eso es una
  denegación y auto lo deja como `deferred` con `/sdd:ship <feature>`.
- Pendiente (olas siguientes, del informe de validación del 2026-09-05):
  **A2** — auto como driver que lanza *cada fase* (new, design, tasks, run) en
  su propio `claude -p` con `--model`/`--effort`/`--max-budget-usd`, y el bucle
  en un `scripts/sdd_auto.py` determinista; **A3** — decisiones en tres niveles
  (`assumed` como tercer tipo de entrada de la regla 5, `deferred` con reintento
  automático, `decision`), escalera de fix rounds Sonnet → Opus distinguiendo
  persistencia de churn, con hueco para un árbitro en Fable activable solo tras
  medir; **A4** — cuerpo del PR con las entradas `assumed`, commit por fase
  verificado, tareas de verificación en navegador.

## Implementación

Se entrega con v0.47.0. `scripts/sdd_auto_outcome.py` + `tests/test_sdd_auto_outcome.py`
(17 tests: receta, clasificación, `run` con un `claude` falso, contrato de la
última línea), `skills/auto/SKILL.md`, `rules.md` (regla 11),
`references/context-budget.md`, `README.md`, `docs/guide.md`, `docs/faq.md`,
`docs/codex.md`.
