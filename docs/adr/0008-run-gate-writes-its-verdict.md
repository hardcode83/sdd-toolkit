# ADR 0008 — El gate de sección escribe su propio veredicto; ship publica la rama; la sesión sabe qué versión corre

- **Fecha**: 2026-09-06
- **Estado**: aceptada
- **Alcance**: `scripts/reviewer_panel.py` (`--plan`, `--section`, recibo por
  sección, anotación) · `scripts/sdd-doctor.py` (`SDD032`) ·
  `scripts/sdd_session.py` (aviso de versión del plugin) · `skills/run`,
  `review`, `ship`, `auto`, `reviewer-panel` · `templates/tasks-template.md` ·
  `tests/test_run_gate.py` (nuevo)
- **Revisa**: ADR 0004 D4 (los revisores devuelven JSON y el orquestador anota
  `panel: PASS`) y el paso 4 de ship desde v0.3x (el push inicial es del
  humano si `/sdd:new` no lo hizo).
- **Continúa**: ADR 0007 (recibo a escala feature).

## Contexto

Dos runs observados con monitor tras las releases 0.47–0.51: `guest-link-delivery`
(auto, 0.50.0, seis secciones, BE+FE) y la sesión de `auth-session-persistence`
que llegó a ship. Las violaciones de instrucción que aparecieron son todas del
mismo tipo: una regla escrita en la skill que el modelo interpretó a su manera
donde no había mecanismo.

## Evidencia

| observado | dónde | consecuencia |
|---|---|---|
| El orquestador anotó `panel: PASS` a mano en tres secciones sin ejecutar el gate; su único intento fue `--scope '{}' --results '[]'`, y después pasó turnos haciendo `grep`/`sed` sobre `reviewer_panel.py` para adivinar las formas JSON | guest-link-delivery, secciones 1–3 | una anotación manual es indistinguible de una real; review la hubiera tratado como PASS |
| Saltó el panel de la sección 1 ("84 tests en verde, lanzo la sección 2") | guest-link-delivery | corrección temprana perdida; el panel combinado 1–2 tardó 80 min |
| QA lanzado en un mensaje aparte de los otros tres revisores | guest-link-delivery, secciones 1–2 | pierde la independencia que la regla "un solo mensaje" compra |
| Dos implementadores de la sección 3 terminaron su turno "esperando la notificación del pytest en background"; el pytest murió y nadie volvió | guest-link-delivery, 5 h 40 min de sección, ~30 $ | un subagente que termina el turno esperando, termina |
| El arquitecto de la fase design lanzado sin `model` (dos veces) | guest-link-delivery | hereda el modelo de la sesión |
| Ship devolvió al humano `git push -u origin <rama>` porque la rama no existía en el remoto, por la regla "el bootstrap lo hace `/sdd:new`" | auth-session-persistence | el humano tuvo que teclear el push y relanzar ship; el paso siguiente lo hizo ship sin problema |
| Una sesión abierta el día 5 corría la **0.44.0** el día 6 con la 0.51.0 instalada: forks que terminaban al lanzar, QA cortado a 40 turnos, seis paneles, 50 $ | auth-session-persistence, sesión 96e79788 | nada de lo corregido aplicaba y nadie lo sabía |
| Seis stacks de Docker (35 contenedores, ~6,9 GiB de 7,65) en la máquina | host de AutoHostAI | QA 80 min, implementadores sin poder verificar |

## Decisiones

### D1 — El gate es el único que escribe `panel: PASS`

`reviewer_panel.py --phase run --section N` exige la sección, deja su recibo en
`<git common dir>/sdd/receipts/<feature>-run-<N>.json` (mismo hogar que el de
feature, ADR 0007) y, con `gate: PASS`, anota él mismo el heading `## N.` de
`tasks.md`: `<!-- panel: PASS <fecha> receipt:<id> -->`, conservando
`<!-- hard -->`. El orquestador nunca escribe ese marcador. Un skip deliberado
se escribe como `<!-- panel: skipped — <motivo> -->`, y ninguna sección N+1
arranca mientras la N no lleve uno u otro.

`/sdd:review` solo cuenta como PASS las anotaciones con `receipt:<id>` cuyo
recibo existe y coincide; las demás son "sin PASS" (alcance completo). El
doctor las señala (`SDD032`, aviso). La anotación manual deja de valer.

Descartado: exigir el recibo desde el lifecycle para cada sección (el lifecycle
certifica a escala feature; la sección es incremental, no un hito).

### D2 — `--plan` y la ayuda dicen las formas; nadie lee el código del gate

`reviewer_panel.py --plan` imprime los revisores planificados
(`reviewer_id`, `lens`, `scope_id`, tipo de agente) y un `example_results`
para el alcance dado; el epílogo de `--help` muestra las formas exactas de
`--scope` y `--results`. La skill de run reduce el panel a tres comandos.

### D3 — Tests en primer plano, con presupuesto, y nunca "esperar a"

Implementadores y revisores ejecutan los tests como llamadas en primer plano con
timeout explícito, acotadas a lo que toca la sección; la suite completa una vez,
en verificación. Con contención del host: acotar al change, registrar
`comando · sha · resultado` en `## Implementation Notes` y seguir. Terminar el
turno para esperar un test en background es terminar el subagente.

### D4 — Ship publica la rama si nadie la ha publicado

`git ls-remote --heads origin <rama>`: ausente → `git push -u` propio (nadie ha
reclamado la feature); presente y ancestro de HEAD → es nuestra; presente y
divergente → `decision` con ambas cabezas y stop, nunca force-push. La regla
anterior devolvía al humano el único push que faltaba.

### D5 — La sesión avisa cuando corre una versión distinta de la instalada

`sdd_session.py check` compara la versión de `CLAUDE_PLUGIN_ROOT` con la de
`installed_plugins.json` para el proyecto y añade `NOTE — this session runs
sdd-toolkit X but Y is installed: end this session and start a new one`. El
plugin se fija al arrancar la sesión; las fases reanudan desde disco, así que
reiniciar no cuesta nada y no hacerlo cuesta todas las correcciones.

### D6 — El arquitecto de auto lleva `model` explícito

`skills/auto` paso 3: `Agent` con `model: sonnet`, dos rondas como máximo,
`assumed` para preguntas abiertas con recomendación.

### D7 — Codex

`--plan`, `--section`, el recibo por sección y `SDD032` son Python estándar y
valen igual bajo Codex; el panel nativo de Codex pasa por el mismo gate.

## Consecuencias

- Una sección con `panel: PASS` pasó por el gate, o review y doctor lo dicen.
- El orquestador de run pierde dos decisiones que tomaba mal (anotar, saltar) y
  gana tres comandos que no puede interpretar.
- Ship ya no devuelve al humano una acción que es suya.
- Lo que sigue sin resolver es del entorno: seis stacks en una máquina virtual
  de 7,6 GiB. El toolkit lo señala (D3) pero no lo arregla; compartir
  postgres/redis entre worktrees o limitar las features en paralelo es decisión
  del proyecto.

## Implementación

Se entrega con v0.52.0. `scripts/reviewer_panel.py`, `scripts/sdd-doctor.py`,
`scripts/sdd_session.py`, `skills/run`, `skills/review`, `skills/ship`,
`skills/auto`, `skills/reviewer-panel`, `templates/tasks-template.md`,
`tests/test_run_gate.py` (12 tests), `tests/test_reviewer_panel_cli.py`
(`--section`), `tests/test_decisions_contract.py` (+4), `README.md`,
`docs/faq.md`, `docs/guide.md`, `docs/codex.md`.
