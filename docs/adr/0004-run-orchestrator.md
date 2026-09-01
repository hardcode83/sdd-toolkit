# ADR 0004 — `run` es un orquestador: un implementador fresco por sección

- **Fecha**: 2026-09-01
- **Estado**: aceptada (ola 2 de la dieta de tokens)
- **Alcance**: `skills/run` (reescrita) · `skills/tournament` (nueva) ·
  `agents/sdd-*.md` (contrato de salida JSON) · `skills/tasks` y
  `templates/tasks-template.md` (`<!-- hard -->`, `## Implementation Notes`) ·
  `scripts/sdd-doctor.py` (`SDD028`) · `docs/codex.md`
- **Revisa**: la forma de `run` desde v0.1 (el hilo principal implementa,
  verifica y lanza el panel). Los contratos del panel —tres core, referente
  obligatorio, gate cerrado, dos rondas de fix, anotación `panel: PASS`— no
  cambian; cambia quién ejecuta y qué entra en el contexto del orquestador.
- **Continúa**: [ADR 0003](0003-forked-phases.md), que resolvió las fases
  terminales con `context: fork` y dejó `run` para esta ola porque sus gates
  conversan con el usuario a cada paso.

## Contexto

La segunda medición (ADR 0003) dejó `run` como el 56 % del gasto de un proyecto
real, con el hilo principal a 444k tokens de contexto medio por request y el 79
% de su coste en releer ese contexto. `run` no puede ir en fork: pregunta al
usuario en las desviaciones y los bloqueos, y el `HANDOFF` de la regla 11 haría
del run una sucesión de idas y vueltas. Pero tampoco necesita cargar lo que
carga: los diffs, las salidas de test, los siete informes de revisor por
sección y las dos rondas de fix son trabajo de una sección, no del run entero.

## Evidencia

- OTel de AutoHostAI (398k datapoints, 80 features): `run/main` 5.187 $ (42 %
  del total) con 18.041 datapoints a 444k de contexto medio; `run/subagent`
  1.303 $ a 105k. Las ocho sesiones más caras de `run` (113–222 $) promediaron
  526–694k de contexto durante 280–660 requests: la forma de una conversación
  que lo acumula todo.
- `cleaner-app`: 13 secciones × 7 revisores = 91 lanzamientos de revisor; los
  cuatro revisores de proyecto de AutoHostAI no declaran `applies_to`, así que
  el planificador (`UNKNOWN`) los lanzaba en cada sección, tocara lo que tocara.
- El `model: sonnet` del frontmatter de `run` no gobernaba nada (77 % del gasto
  en Opus); el `model` de una llamada `Agent` sí.
- El mercado converge en lo mismo: cc-sdd (*fresh implementer per task*), GSD
  (*main session kept at 30–40 %*), Superpowers (*subagent-driven
  development*), Kiro (*waves en contexto aislado*). Ninguno mide; nosotros sí.
- Documentación oficial: un subagente puede lanzar subagentes hasta tres niveles
  por debajo de la conversación principal, `cd` no persiste entre sus llamadas
  Bash, y el resultado que devuelve al padre es su mensaje final.

## Decisiones

### D1 — El orquestador no implementa

`/sdd:run` lee el plan una vez y, por cada sección con tareas pendientes, lanza
**un** `Agent` general-purpose con un prompt completo: worktree y rama, tareas
verbatim, R# con su texto EARS, D# citadas, steering que aplica, comandos de
test y las `## Implementation Notes`. El implementador implementa en orden,
verifica antes de marcar `[x]`, anota lo que la siguiente sección necesita y
devuelve un informe de ~30 líneas sin diffs ni logs. Los fixes de los findings
van a otro implementador acotado a esos findings. El orquestador comprueba en
disco (`tasks.md`, `git status`) lo que el informe afirma: evidencia sobre
afirmaciones, como la regla 8.

Descartado: un implementador por *tarea* (más lanzamientos y menos contexto
compartido por unidad de trabajo; la sección ya es la unidad de revisión) y un
implementador por *change* (recrea el problema en el subagente).

### D2 — Sonnet por defecto, Opus solo con `<!-- hard -->`

El `model` de la llamada `Agent` sí gobierna. Las secciones corren en Sonnet 5;
una sección cuyo heading lleva `<!-- hard -->` (puesto por `/sdd:tasks` o por el
usuario) corre en Opus 5. El orquestador nunca escala por iniciativa propia: una
sección que resulta más difícil de lo previsto es una nota para el usuario en el
gate, no un cambio silencioso de modelo. `tournament` va siempre en Opus: la
varianza es lo que se compra.

### D3 — La continuidad vive en `tasks.md`

Un implementador fresco por sección pierde lo que el anterior aprendió. El
template de `tasks.md` cierra con `## Implementation Notes`, append-only, un
bullet por decisión/nombre/gotcha; cada implementador lo recibe y lo amplía. Es
la regla 1 aplicada dentro del run: el estado vive en `sdd/`, no en la
conversación de nadie.

### D4 — Los revisores devuelven JSON, no informes

El mensaje final de cada agente del panel es el sobre de resultado que
`reviewer_plan.py` ya validaba (`reviewer_id`, `scope_id`, `lens`, `verdict`,
`findings`, `evidence`, `status`), con `severity`/`referent`/`what`/`fix`/`kind`
por finding, `unreached` para el corte de presupuesto y, en qa, `criteria` y
`tests`. El orquestador lee findings del JSON y nunca carga prosa de revisor.
Es además el mismo sobre que valida el handoff nativo de Codex, así que los dos
runtimes comparten el contrato entero por primera vez.

### D5 — `tournament` es su propia skill

`/sdd:tournament <feature> <task>`; `run … tournament <task>` sigue funcionando
y delega en ella. Saca de `run` un modo que nunca es el default y que costaba
un párrafo en cada carga de la skill más frecuente del flujo.

### D6 — `SDD028`: revisor de proyecto sin `applies_to`/`phases`

Aviso, no error. Sin esa metadata el planificador solo puede responder
`UNKNOWN` y lanzar; con ella, un revisor de i18n solo corre cuando la sección
toca `frontend/**`. `run` lo dice al lanzar el panel y el doctor lo señala.

### D7 — Codex sigue siendo compatible

Sin subagentes, `run` implementa inline con el mismo contrato (orden,
verificación antes de `[x]`, notas). El JSON de los revisores es el que Codex ya
validaba. `tournament` sigue sin soporte en Codex, ahora en su propia skill.

## Consecuencias

- Estimación sobre el corpus: `run/main` de ~5.000 $ a ~1.200 $ (contexto plano
  del orquestador × Sonnet en los implementadores), es decir, otro −30 % del
  total tras el −33 % de la ola 1. La medida real la da `usage-sync.py report`.
- El usuario ve un turno de espera por sección en vez de ver el código
  escribirse; a cambio, el `run` de una feature deja de degradar la sesión para
  todo lo que venga después.
- Los tests de contrato del panel siguen exigiendo las frases y el presupuesto
  de los agentes; se añade el contrato JSON, no se quita ninguna garantía.
- Pendiente (olas 3 y 4): presupuesto por change con corte, artifacts en los
  gates, `/sdd:clarify`, delta specs, converge.

## Implementación

Se entrega con v0.44.0.
