# ADR 0009 — El gate recoge los veredictos del registro del harness; el orquestador no escribe ninguno

- **Fecha**: 2026-10-02
- **Estado**: aceptada
- **Alcance**: `scripts/reviewer_panel.py` (`--collect`, `--invocations`,
  `--wait`, `--transcripts`; `--plan` sin `PASS` prerrelleno) ·
  `scripts/panel_collect.py` (nuevo) · `skills/run`, `review`, `auto`,
  `reviewer-panel` · `references/runtime-provider.md` · `docs/faq.md`,
  `docs/guide.md` · `tests/test_panel_collect.py` (nuevo)
- **Revisa**: ADR 0008 D2 (`--plan` imprimía un `example_results` con
  `"verdict": "PASS"` que el orquestador rellenaba).
- **Continúa**: ADR 0007 (recibo), ADR 0008 (el gate escribe su veredicto).

## Contexto

Desde la 0.54.1 el gate exige, por revisor, un sobre `{invocation_id,
planned_reviewer_id, payload}` en `--results`. El que lo construía era el
orquestador, a mano: copiaba el JSON de cada revisor a la línea de comandos.
Eso tiene dos defectos que no se arreglan con más prosa en la skill:

1. **El orquestador es quien teclea el veredicto.** Nada distingue un `PASS`
   copiado de un `PASS` inventado, y al menos una vez fue inventado: un fork de
   review escribió `PASS` para siete revisores, dos de ellos todavía en marcha,
   con `invocation_id` copiados de los `agentId` y `evidence` rellenado con la
   lista de ficheros del scope.
2. **El modo auto lo trata como lo que parece.** El clasificador de permisos de
   Claude Code ve un agente que fabrica `{"verdict":"PASS","findings":[]}` y se
   lo pasa a un gate de CI, y lo deniega.

## Evidencia

| observado | fuente | consecuencia |
|---|---|---|
| 28 denegaciones `[CI Bypass]`/`[Self-Approval]` del comando del gate, 27 dentro de subagentes/forks de `/sdd:review`, `/sdd:run`, `/sdd:auto` | medición del usuario sobre 3052 transcripts, 2026-09-06 → 10-02 | la fase se corta; en headless no hay nadie para aprobar |
| Las formas denegadas: heredocs `python3 - <<EOF` que escriben sobres a `/tmp`, lambdas que fabrican `{"verdict":"PASS",...}`, lectura de `tool-results` de subagentes | misma medición | la regla `allow` no casa con `G=...; python3 "$G"` ni con heredocs |
| `--plan` imprimía `example_results` con `"verdict": "PASS"` ya relleno | `reviewer_panel.py` 0.54.4 | invitaba justo a pegarlo |
| Llamadas `Agent` hechas desde un fork: `Async agent launched successfully` aunque la skill pida foreground (`requestShape: background` en el meta) | transcripts de `ai-provider-core`, Claude Code 2.1.287 | la regla de foreground no la puede cumplir el modelo; hace falta que alguien espere dentro del turno |
| El harness escribe, por subagente, `subagents/agent-<agentId>.meta.json` con `agentType`, `toolUseId`, `parentAgentId`; el informe final es la llamada `SubagentHandback` con respuesta `{"success":true}` | 869 metas de los últimos 10 días en esta máquina | hay un registro de confianza de qué se lanzó y qué devolvió, que no escribe el orquestador |
| De 1058 transcripts de revisores (14 días): 853 entregan exactamente un objeto JSON del contrato; 152 entregan prosa (sobre todo revisores de proyecto: documentation 51, i18n 37, tenancy 28, cicd 21); 27 sin `SubagentHandback`; 26 con más de un informe (revisores reanudados con `SendMessage`) | medición sobre los transcripts locales, incluye revisiones de design fuera del panel | lo que antes «arreglaba» el orquestador a mano ahora falla cerrado y hay que relanzar |
| 83 de 99 prompts de `sdd-qa` ya llevaban el `scope_id` exacto | mismos transcripts | exigirlo en el prompt cuesta poco |

## Decisiones

### D1 — `--collect`: el orquestador pasa ids, el gate lee los veredictos

`reviewer_panel.py --collect --invocations '{"<revisor planificado>":"<agentId>"}'`.
El `agentId` es el que imprime el resultado de cada llamada `Agent` (también
vale el `toolu_…` de la llamada). Para cada uno, `panel_collect.py`:

- localiza **un único** `agent-<agentId>.meta.json` (acotado a la sesión de
  `CLAUDE_CODE_SESSION_ID` cuando existe; si no, a todos los proyectos, y con
  `toolu_` solo a los metas de las últimas 48 h);
- exige que `agentType` sea el revisor planificado (`<id>` o `sdd:<id>`): **la
  identidad de confianza es lo que el harness lanzó**, no lo que el revisor
  declara;
- busca en el transcript padre (el principal de la sesión o el del subagente
  orquestador) la `tool_use` `Agent` con ese `toolUseId`: su `subagent_type`
  debe coincidir con el meta y su prompt debe llevar el `scope_id` exacto (un
  revisor lanzado para la sección 1 no certifica la 2);
- si la `tool_result` de esa llamada es error o interrupción, el revisor está
  muerto aunque haya informe;
- toma el informe de su `SubagentHandback` confirmado (`success: true`) o, en un
  harness sin handback, el texto de la `tool_result` si no es un puntero
  («Async agent launched…», «delivered to you as a message…»);
- extrae **el único** objeto JSON con las siete claves del contrato (crudo o en
  bloque ```json; repeticiones idénticas cuentan como uno).

El sobre resultante entra por el mismo `normalize_reviewer_result` /
`evaluate_panel_gate`, con el mismo recibo, `--section`, `--carry` y
`--worktree`. Todos los revisores deben colgar del mismo orquestador.

### D2 — Todo lo dudoso es `unavailable`, por revisor

Sin registro, registro en dos sesiones, tipo distinto, meta y llamada que no
coinciden, prompt de otro scope, error, interrupción, informe sin JSON, dos
objetos distintos, dos informes entregados distintos, o revisor sin
`invocation`: ese revisor es `unavailable` con un motivo accionable y el gate
falla. Errores de mando (id repetido entre revisores, revisor que el plan no
tiene, `--collect` junto a `--results`) son `FAIL` global. Un revisor que no
ha entregado aún es `pending`; `--wait S` (máx. 3600) sondea cada 5 s hasta que
llegue o venza, y al vencer es `unavailable`. Eso mantiene la recogida dentro
del turno del llamante aunque el harness haya puesto al revisor en background
(`references/runtime-provider.md`).

### D3 — Un comando estático, una regla estrecha

Las skills piden **un único** comando por llamada al gate, con la ruta literal
`${CLAUDE_PLUGIN_ROOT}/scripts/reviewer_panel.py`, sin variables `G=...;`,
heredocs ni ficheros en `/tmp`. Queda prohibido escribir JSON de veredicto o
leer los `tool-results`/transcripts de un revisor para reconstruirlo. Una regla
`Bash(python3 <ruta del plugin>/scripts/reviewer_panel.py *)` lo cubre.

### D4 — `--results` se queda como camino heredado

Para tests, para el handoff de Codex (que no pasa por aquí) y para harnesses
que entregan el JSON ellos mismos. `--plan` ya no imprime un `PASS`: imprime el
comando `--collect` y un `example_results` con un veredicto marcador
(`<copy the reviewer's verdict; legacy --results only>`) que el gate rechaza si
se pega tal cual.

## Alternativas descartadas

- **Pedir al usuario un `allow` amplio de `python3`** (o de heredocs): quita el
  síntoma abriendo ejecución arbitraria, y el clasificador del modo auto juzga
  el contenido, no solo la regla; seguiría viendo un `PASS` fabricado.
- **Seguir con heredocs / ficheros en `/tmp`, mejor redactados**: es la forma
  que se deniega, y sigue siendo el orquestador quien teclea el veredicto.
- **Confiar en la prosa del revisor**: no hay regla determinista que saque un
  veredicto de prosa; el contrato es JSON y lo que no lo cumple falla cerrado.
- **Descubrir los revisores sin ids** (todo `Agent` de la sesión con el tipo y
  el scope): ambiguo con relanzamientos y con forks concurrentes en la misma
  sesión; los ids explícitos dicen qué llamada ocupa cada hueco.
- **Tomar el último informe de un revisor reanudado con `SendMessage`**: se
  propuso para los 26 transcripts con varios informes y el clasificador del
  modo auto lo denegó durante la implementación (`[Security Weaken]`). Se
  mantiene lo estricto: varios informes distintos son ambiguos, y la skill
  pide relanzar con una llamada `Agent` nueva en vez de reanudar. Decisión
  abierta para el mantenedor.

## Consecuencias

- El gate depende del formato de los transcripts de Claude Code (nombres de
  fichero, claves del meta, bloques `tool_use`/`tool_result`,
  `SubagentHandback`). Si cambia, la recogida no encuentra registros o no
  encuentra informes y **falla cerrada**: no puede producir un `PASS` por un
  formato desconocido. El arreglo es adaptar `panel_collect.py`, nunca volver
  a teclear veredictos.
- Los revisores que devuelven prosa (sobre todo los de proyecto) fallan ahora
  donde antes el orquestador los «traducía». Las skills piden cerrar cada
  prompt con el contrato JSON; los ficheros `.claude/agents/sdd-review-*.md`
  de cada proyecto deberían llevarlo.
- El gate lee `~/.claude/projects` (o `$CLAUDE_CONFIG_DIR/projects`). No
  escribe nada fuera de lo que ya escribía.
- Un orquestador que escribiera a mano un transcript falso bajo
  `~/.claude/projects` engañaría al gate; eso ya no es transcribir un
  veredicto sino falsificar el registro del harness, y queda fuera de este
  modelo de amenaza.

## Implementación

0.55.0. `scripts/panel_collect.py` (lógica importable, sin escrituras),
`scripts/reviewer_panel.py` (`--collect`, `--invocations`, `--wait`,
`--transcripts`, `--plan`), `tests/test_panel_collect.py` (transcripts JSONL
sintéticos con la forma de Claude Code 2.1.287).
