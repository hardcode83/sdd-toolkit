# ADR 0003 — Las fases terminales corren en un subagente sin historial (`context: fork`)

- **Fecha**: 2026-09-01
- **Estado**: aceptada (ola 1 de la dieta de tokens)
- **Alcance**: regla compartida 11 · `skills/review`, `skills/ship`,
  `skills/archive`, `skills/status`, `skills/history` (frontmatter y gates) ·
  `agents/sdd-security.md` (modelo), `agents/sdd-*.md` (`maxTurns`) ·
  `scripts/sdd-doctor.py` (`SDD027`) · `references/context-budget.md` ·
  `docs/codex.md`
- **Revisa**: la regla 11 tal como quedó en v0.3x ("el modelo no puede vaciarse
  el contexto; decirlo en el gate *es* el mecanismo"). El diagnóstico de aquella
  medición sigue siendo cierto; el mecanismo ya no es el mejor disponible.

## Contexto

El coste del flujo lo manda dónde corre una fase, no lo que hace
(`references/context-budget.md`). La primera medición (38 sesiones, julio) llevó
a la regla 11: cada gate recomienda `/clear` antes de la fase siguiente, y
`/sdd:auto` delega review en una sesión headless. Conforme el proyecto consumidor
creció (AutoHostAI: 80 features en siete semanas, panel de 7 revisores) el gasto
se disparó, sobre todo en `run` y `review`, y la sospecha era el panel: se
levanta por sección en run y otra vez por feature en review.

## Evidencia

Log OTel de AutoHostAI (`.sdd-usage/otel.jsonl`, 398.308 datapoints, 17 jul –
1 sep 2026, 12.255 $ estimados API-equivalente). Agregado por `task`, `source`,
`model` y `session`.

### El panel no es el gasto

| dónde | coste | % |
|---|---:|---:|
| hilo principal, todas las fases | 9.245 $ | 75 |
| subagentes (panel, tournament) | 2.329 $ | 19 |
| auxiliar (títulos, resúmenes de compactación) | 683 $ | 6 |

Por fase: `run` 56 %, `review` 20 %, `archive` 8,5 %, `new`+`design`+`tasks`
11 %. Dentro de `run`, el hilo principal solo son 5.187 $ (42 % de todo el
corpus), con **444k tokens de contexto medio por request** y sesiones que
promedian 526–694k durante 280–660 requests.

### Lo que se paga es releer

Descomposición del coste de `run/main` a precios de Opus 5 (5 $/25 $ por
millón; lectura de caché 0,1×, escritura 1,25×): cache-read 79 %, cache-write
10 %, output 9 %, input 1 %. El modelo reproduce el coste medido con un 4 % de
error. Casi todo el dinero es la conversación acumulada, releída a cada turno.

### El modelo que las skills pedían no era el que corría

Opus 5 fue el 77 % del gasto; Sonnet 5, el 13 %. `run`, `review` y `ship`
declaran `model: sonnet` en su frontmatter, pero una skill inline no gobierna el
modelo de la sesión interactiva (verificado en transcripts: la sesión sigue en
su modelo). Los subagentes sí respetan su `model:` — por eso `sdd-security`
(Opus) fue el revisor más caro.

### El consejo no se seguía

256 de 415 sesiones (62 %) tocaron más de una feature. La regla 11 pedía
`/clear` en el gate; el humano no lo hacía, y el flujo no tenía forma de
hacerlo por él.

### El mecanismo existe

Documentación oficial de Claude Code (consultada el 2026-09-01):

- Frontmatter de skill: `context: fork` ejecuta la skill en un subagente **sin
  acceso al historial de la conversación**; `agent:` elige el tipo; `model:` y
  `effort:` pasan a gobernar ese subagente; `background: false` hace que el
  llamante espere el resultado en el mismo turno (≥ 2.1.218).
- Un subagente puede lanzar subagentes hasta tres niveles por debajo de la
  conversación principal, así que un `review` en fork sigue lanzando su panel.
- Límites: **ningún subagente tiene `AskUserQuestion`** (ni `EnterPlanMode`,
  `ExitPlanMode`, `Workflow`); `cd` no persiste entre llamadas Bash de un
  subagente; un fork en background pierde además la mayoría de herramientas
  integradas (por eso `background: false`).
- Agentes: `maxTurns` corta al subagente y devuelve el resultado marcado como
  parcial (≥ 2.1.246); `effort` y `memory` también existen.

## Decisiones

### D1 — `review`, `ship`, `archive`, `status` e `history` declaran `context: fork`

Con `background: false` y el `model:`/`effort:` que cada fase merece: `review`
Sonnet (esfuerzo heredado), `ship` y `archive` Sonnet a esfuerzo medio, `status`
Haiku bajo, `history` Haiku medio. `new`, `design`, `tasks` y `run` siguen
inline: sus gates conversan con el usuario a cada paso y son el 11 % del gasto
(`run` se trata en la ola 2: orquestador fino con implementador por sección).

Descartado: seguir con el consejo de `/clear` (no se cumple), o delegar cada
fase en `claude -p` desde la sesión interactiva (pierde el hilo de permisos y la
conversación; es lo correcto para `auto`, no para el uso interactivo).

### D2 — Una fase en fork no pregunta: termina con un bloque `HANDOFF`

Como no hay `AskUserQuestion`, la fase hace todo lo que no depende de una
respuesta, persiste lo que exige la regla 5 y termina su turno con `HANDOFF`:
qué hizo, qué hay que decidir (con recomendación) y el **comando exacto por
respuesta**. La conversación llamante, que sí tiene la herramienta, pregunta y
ejecuta. Casos concretos:

- `review` sin argumento con changes activos: devuelve las opciones
  (`/sdd:review <feature>` o el nuevo `/sdd:review drift`).
- `review` con veredicto PASS: devuelve la oferta de `/sdd:ship <feature>`.
- `archive`: el paso 8 devuelve sus dos preguntas (commit+publish, retire) y la
  secuencia del paso 9 con los comandos rellenos; el **llamante** ejecuta el
  cierre en ese orden, con el autorretiro como última tool call de la sesión.
  Nada por debajo del paso 7 se comitea, publica ni retira dentro del fork.

Descartado: que el fork comitee sin preguntar (un "no" del usuario debe seguir
siendo un "no"), o que la fase se corte en dos skills (`archive` y
`archive-close`): el `HANDOFF` ya es esa frontera sin duplicar texto.

### D3 — Directorio de trabajo por comando

`cd` no persiste en un subagente y `EnterWorktree` no es fiable ahí. Las fases
en fork resuelven el worktree una vez (`sdd_session.py … resolve`) y prefijan
cada comando con `cd <path> &&` (o `--root <path>`), leyendo ficheros por ruta
absoluta. `archive` ya lo hacía desde v0.42 por otra razón (sesiones pinned);
ahora es la norma de todas las fases en fork.

### D4 — `sdd-security` corre en Sonnet por sección y en Opus por feature

El agente declara `model: sonnet`; `/sdd:review` lo lanza con `model: opus` en
la llamada. Los paneles por sección son un orden de magnitud más frecuentes que
el de feature, y la escala feature (límites de confianza entre secciones) es
donde el modelo grande aporta. Los tres agentes core llevan además `maxTurns`
(30/30/40): la forma dura del presupuesto "~25/~35 tool calls" que ya llevaban
en prosa; un resultado parcial es un no-PASS para el gate cerrado del panel.

### D5 — `SDD027`: un steering de más de 150 líneas es un aviso

`steering/security.md` del proyecto medido pesa 93 KB (~23k tokens, 285 líneas)
y se cargaba entero en design, en run y en cada revisor de seguridad de cada
panel. La carga selectiva solo puede dejar fuera lo que está en *otro* fichero,
así que el tamaño es lo único que el doctor puede ver. Aviso, no error: el coste
se arregla a propósito, nunca bloquea un run.

### D6 — Codex sigue siendo compatible

Codex ignora `context`, `background` y `effort` (como ya ignoraba `model`) y
ejecuta la skill inline. Las skills no dependen del fork: el `HANDOFF` es la
forma correcta de un gate donde `AskUserQuestion` nunca existió, y bajo Codex el
llamante y la fase son la misma sesión. Documentado en `docs/codex.md`.

## Consecuencias

- Estimación sobre el corpus medido: `review/main` 351k → ~40k de contexto,
  `archive/main` 291k → ~40k, `ship` y `status` análogo; unos 4.000 $ de los
  12.255 $ (−33 %), sin quitar ningún gate ni ningún revisor. Es una estimación
  a partir de la composición medida; la medida real la da `usage-sync.py
  report` sobre las próximas diez features.
- El usuario ve un turno de espera mientras la fase corre en el fork y recibe
  el `HANDOFF` como texto; las preguntas llegan por `AskUserQuestion` desde la
  conversación principal, como antes.
- Los tests de contrato siguen exigiendo las frases de gate ("this is advice,
  not a gate", "both questions in the same call", "Skip this question entirely
  under `/sdd:auto`"); cambiaron los actores, no las garantías.
- Pendiente (ola 2): `run` como orquestador con implementador fresco por
  sección; panel de sección ligero; salida de revisor en JSON del contrato.

## Implementación

Este ADR se entrega con v0.43.0. `rules.md` (regla 11), `references/context-budget.md`
(segunda medición y los cuatro mecanismos), las cinco skills, los tres agentes,
`scripts/sdd-doctor.py` + `tests/test_sdd_doctor.py` (`SDD027`), `README.md`,
`docs/faq.md`, `docs/codex.md`, `references/steering.md`.
