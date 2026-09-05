# Guía de uso — SDD paso a paso

Esta guía es el paseo narrativo: cómo se *usa* el flujo en el día a día. La referencia completa de cada pieza está en el [README](../README.md).

## El mapa mental (30 segundos)

Todo el estado vive en `sdd/` dentro de tu repo — **specs** (qué hace el sistema hoy), **changes** (qué estamos cambiando), **steering** (las reglas de la casa), **roadmap** (qué viene después). Las skills del plugin (`/sdd:*`) son las que leen y escriben esos archivos con disciplina. El ciclo de cada feature:

```
/sdd:new ──► proposal (requisitos EARS)      ── tú apruebas ──►
/sdd:design ──► decisiones técnicas          ── tú apruebas ──►   (se salta si es trivial)
/sdd:tasks ──► checklist verificable         ── tú apruebas ──►
/sdd:run ──► implementa + panel de revisores por sección
/sdd:review ──► valida localmente y deja READY_FOR_PR
/sdd:ship ──► sync de la base + push + PR + evidencia registrada  (review te lo ofrece)
Pull Request ──► revisión remota + CI ──► MERGED
/sdd:archive ──► verifica el merge, fusiona specs/ y archiva
```

Ninguna fase encadena con la siguiente sola: cada una termina esperándote.

## Instalación (una vez por máquina)

```
/plugin marketplace add hardcode83/sdd-toolkit   # o ruta local al clon
/plugin install sdd@sdd-toolkit
```

## Escenario A: proyecto desde cero con un plan

Tienes un PRD/plan en markdown y un directorio vacío.

**1. Bootstrap:**

```
/sdd:init docs/plan.md
```

El init lee el plan y te propone un **triaje** (confirmas antes de que escriba nada): visión y principios → `steering/product.md`; stack y decisiones ya tomadas → `project.md` + `steering/architecture.md`; la lista de features → `roadmap.md`, una línea por futuro change agrupada en stages (metas, no categorías) y con las dependencias que el plan declare; el análisis largo de una entrada, a `roadmap/<feature>.md`. Después pregunta qué **steering docs** crear (architecture, security, testing, documentation, por componente…), y qué **extras** activar: MCPs según tu stack, LSPs, puntero en CLAUDE.md, métricas de uso.

Importante: el init **no** convierte el plan en proposals. Los proposals se escriben uno a uno, cuando les llega el turno — así el proposal de la feature 5 se escribe contra las specs reales de las features 1-4, no contra lo que el plan imaginaba.

El init analiza y registra los comandos reales del proyecto, pero no instala los
tests del repositorio sdd-toolkit ni su workflow de CI. El proyecto mantiene sus
propios criterios de validación en project.md y steering/testing.md, cualquiera
que sea su lenguaje o framework.

**2. Primer change:**

```
/sdd:new
```

Sin argumento, coge la primera entrada de la **frontera** del roadmap (las que tienen sus dependencias cerradas — no la primera línea del fichero) y la convierte en `changes/<feature>/proposal.md`: 3-7 requisitos como user stories con criterios EARS ("WHEN X, THE SYSTEM SHALL Y"), un *Out of scope* explícito, y las specs que tocará. Lo revisas. Si algo no te cuadra, se corrige aquí — es el momento barato de cambiar de opinión.

**3. Diseño (si hace falta):**

```
/sdd:design
```

Investiga el código, escribe decisiones con sus alternativas rechazadas y te plantea las open questions como preguntas concretas. Para cambios triviales te dirá directamente que lo saltes — no genera documentos ceremoniales.

**4. Tareas y ejecución:**

```
/sdd:tasks     # checklist por secciones; cada tarea cita sus requisitos [R1]
/sdd:run       # implementa en orden
```

Durante el run: cada tarea se verifica (tests/lint del proyecto) antes de marcarse `[x]`; al cerrar cada **sección** que tocó código de producción, se lanza el **panel** — sdd-architect, sdd-security y sdd-qa en paralelo, revisando el diff contra *tus* documentos (design, security.md, criterios EARS). Los findings sin referente citado se descartan; los aceptados se arreglan y se re-revisa (máx. 2 rondas, luego te los presenta a ti).

**5. PR y cierre:**

```
/sdd:review    # panel a escala feature; si pasa, registra READY_FOR_PR
               # y te ofrece publicar en la misma pregunta
/sdd:ship      # sync-base + push + PR + record-pr → PR_OPEN. STATE.md conserva URL, ramas y SHA
# mergeas el PR (eso sigue siendo tuyo)
/sdd:archive   # exige MERGED verificable; entonces actualiza specs/roadmap/archive
```

Un PR abierto o cerrado sin merge no se puede archivar. Las specs vivas y el
tick definitivo del roadmap esperan al merge; una afirmación del agente no
sustituye `gh pr view`.

Y vuelta al paso 2 con la siguiente entrada de la frontera — que puede no ser la siguiente del fichero: cerrar una entrada desbloquea las que la esperaban.

## Escenario B: adoptar SDD en un proyecto existente

```
/sdd:init
```

Sin plan, el init genera el steering **desde el código real** (stack, comandos verificados, convenciones observadas) y te ofrece un **baseline de specs**: detecta las capabilities del sistema, eliges las 3-6 core, y las documenta leyendo el comportamiento real. No hagas backfill total — specs especulativas que nadie audita son peores que ninguna. El resto se cubre solo: cuando un change toque un área sin spec, `/sdd:archive` la creará ("spec on first touch").

¿Trabajo a medio hacer? `/sdd:new` documenta el estado final previsto y `/sdd:tasks` pre-marca `[x]` lo ya construido — tras verificarlo contra el código, nunca por tu palabra.

## Recetario del día a día

**¿Por dónde iba?** → `/sdd:status`: changes activos con progreso + las vistas del roadmap — la **frontera** (qué se puede atacar ya, en paralelo, y cuántas entradas desbloquea cada una), las olas, el camino crítico de cada stage y el grafo.

**¿Qué hago ahora?** → la primera entrada de la frontera. No es la primera línea del fichero: una entrada puede estar esperando algo. Si solo te da para una y hay varias disponibles, coge la que más desbloquee (`/sdd:status` lo anota).

**Añadir una feature al backlog** → edita `sdd/roadmap.md` a mano o pídeselo al agente: una línea en el stage al que pertenece, más su sub-línea de metadatos.

```markdown
- [ ] mi-feature — qué es, en una línea
      needs: la-que-crea-lo-que-necesito · size: M · kind: feature
```

**El orden ya no lo decide la posición, lo decide `needs:`.** Es el cambio de mentalidad importante: si no declaras la dependencia, la entrada se considera atacable desde ya — y `/sdd:auto` puede cogerla antes de que exista lo que necesita. Declarar de menos es el error caro; declarar de más solo la aparca. Si el análisis es largo, no lo metas en la línea: va a `sdd/roadmap/mi-feature.md`, que solo lee el `/sdd:new` de esa entrada.

**Los stages son metas, no categorías** → `## Stage 3 — reservas reales entrando por webhook`, no `## Backend`. Es lo que hace visible qué features convergen hacia el mismo fin, y por eso agrupar por `[FE]`/`[BE]` no sirve: las cadenas cruzan categorías.

**Mi roadmap es una lista plana de hace meses** → sigue funcionando sin tocar nada: sin relaciones declaradas, toda entrada abierta está en la frontera (el comportamiento de siempre) y `/sdd:status` te dice explícitamente que no hay grafo que dibujar. Migras cuando quieras, entrada a entrada — o de golpe con `/sdd:init` sobre el plan, que te lo ofrece con el diff a la vista y **no toca las archivadas**.

**Atacar dos features a la vez** → abre dos sesiones y ya está: la segunda detecta a la primera y te ofrece un worktree aislado (`.claude/worktrees/`), con su rama y su directorio. Di sí. Sin eso comparten HEAD, y la segunda se lleva los ficheros sin commitear de la primera a su rama — que además hace que `STATE.md` grabe una rama y un SHA que no describen el trabajo.

Ojo con el reparto: la **primera** se queda en el clon principal y lo deja en su rama y sucio, así que cualquier shell que abras ahí arranca en la feature ajena. Si eso te molesta —o si sueles lanzar varias sesiones—, escribe `isolation: always` en la sección *Worktree bootstrap* de `sdd/project.md` y entonces **todas** las features van a su worktree, la primera incluida, dejando el clon principal limpio en la rama por defecto. Lo pagas en bootstrap por feature (lo de abajo), que es justo por lo que no viene puesto por defecto.

Un aviso práctico: un worktree recién creado **no tiene** tu `.env` ni `node_modules` ni tu base de datos local, así que los tests fallarán ahí hasta que `sdd/project.md` declare su sección **Worktree bootstrap** (`/sdd:init` te la pregunta). Si te pasa, no es un bug del código: es esa sección que falta.

**¿Dónde está el trabajo de la otra sesión?** → `/sdd:status` agrega todos los worktrees del repo y lista las sesiones vivas. Un change puede no estar en el directorio desde el que lanzaste el comando.

**Terminé y mergeé** → `/sdd:archive` corre **en el worktree principal** (muta specs, roadmap y mueve directorios: es el punto de serialización del flujo) y te ofrece retirar el worktree y su rama en la misma pregunta de cierre. Si algo quedó sin commitear allí, `git worktree remove` se niega — y eso es lo correcto: trabajo sin commitear es trabajo que nunca llegó al merge.

Dos cosas que sí decomisiona solo, y que antes hacían falta pedir aparte: **estar dentro** del worktree que hay que retirar ya no lo bloquea (`retire` se muda al principal antes de tocar git y te dice a dónde moverte tú), y si el worktree tiene un stack de docker que el proyecto nunca dijo cómo parar, la pregunta de cierre llega con la línea `teardown:` ya escrita a partir de lo que reportó docker — decidir si ese `--volumes` puede correr sigue siendo tuyo, teclearlo no. Declárala una vez en *Worktree bootstrap* y no vuelve a preguntar.

**El PR salió con conflictos porque mergeé otra feature antes** → ya no es tu problema: `/sdd:ship` sincroniza la base en la rama antes de abrir el PR (merge, nunca rebase, para no destruir el `implementation_sha` revisado). El bookkeeping append-only (`roadmap.md`, `metrics.md`) lo une él; un conflicto de código lo resuelve, **vuelve a pasar la verificación del proyecto** y solo entonces publica. Si esa verificación falla, no abre el PR: entrada en `BLOCKED.md` y a `/sdd:review`.

**Una feature para YA** → `/sdd:new mi-feature` directamente; el roadmap no es un peaje. Eso sí: si existe roadmap, te preguntará si registrarla como entrada ad-hoc (con nota de procedencia, tipo *"añadido tras X"*) — di que sí salvo que sea exploratorio: las features fuera del roadmap son invisibles para `/sdd:status` y el tracking de progreso. Cuando nace de otra entrada, esa relación es justo para lo que sirven los metadatos: `completes:` si cierra lo que aquella dejó a medias, `needs:` si depende de algo que crea.

**Tengo los requisitos ya escritos en un doc** → dos vías equivalentes: `/sdd:new mi-feature docs/reqs.md` (el doc como semilla directa), o entrada de roadmap con `(fuente: docs/reqs.md)` para que lo use cuando le llegue el turno. En ambos casos el proposal *convierte* el doc a EARS (no lo copia), señala ambigüedades y huecos, y cuanto mejor esté escrito el doc, menos preguntas te hará — con un doc realmente cerrado, la feature es candidata ideal para `/sdd:auto`.

**¿Doc de una feature o plan entero?** → regla: *documento que describe una feature → `new`; documento que describe el producto/plan → `init`*. Y si te equivocas de comando, no pasa nada: `new` detecta el olor a plan (varias capabilities, decisiones de stack, lista de fases…) y se para antes de escribir, ofreciéndote tratarlo como ingesta de plan ahí mismo (con tu ok — nunca reescribe steering/roadmap por sorpresa) o acotar a una sola feature del doc.

**Lanzar features sin intervenir** → `/sdd:auto [N]`: consume N entradas **de la frontera** (nunca las N primeras del fichero, que podrían depender unas de otras) hasta abrir una rama + PR por feature, con panel obligatorio. Relee la frontera entre features, así que cerrar una puede habilitar otra dentro de la misma tirada. Aborta si el grafo tiene errores — no elige un orden a partir de un grafo que ya se sabe mal. Registra `PR_OPEN` y se detiene: no toca specs vivas, archive ni el tick definitivo del roadmap. Tu gate se mueve a revisar/mergear las PRs; después ejecutas `/sdd:archive <feature>`. Todo lo que necesita tu decisión acaba en `BLOCKED.md`. Para lanzarlo desatendido (cron, CI) usa la receta del toolkit — `python3 "$PLUGIN/scripts/sdd_auto_outcome.py" run "/sdd:auto 2" --cwd .` — y no un `claude -p` a mano: la sesión necesita `--permission-mode auto --permission-prompts none` y un modelo Sonnet u Opus, o se queda en Manual y deniega hasta los scripts del propio toolkit (FAQ: «¿Por qué auto lanza sus sub-sesiones con `--permission-mode auto`…»).

**Desbloquear una feature de auto** → lee su `BLOCKED.md` (`sdd_lifecycle.py blocked <feature>` lo lista con tipos), decide, borra la entrada y retoma con las fases normales en su rama `sdd/<feature>` — o `/sdd:auto <feature>` para que auto continúe desde donde quedó (reanuda por fase; nunca regenera tus documentos). Solo las entradas `decision` paran a auto; las `deferred` y `assumed` viajan con el PR y las resuelves allí. Y si contestas "adelante" sin elegir, auto toma la opción recomendada y la registra como `assumed` — no como decisión tuya.

**Una tarea que solo puedes hacer tú** (un pase en navegador sin puerto libre, un paso de consola, un sistema externo) → márcala `<!-- manual -->` en `tasks.md`. `run` no la intenta ni la marca, la registra como `deferred`, y el change llega al PR con ella abierta para que la hagas allí; `archive` sigue exigiéndola hecha. Sin el marcador, una tarea abierta es trabajo sin terminar y el gate se niega.

**Quedó deuda a mitad de un run** (un panel interrumpido por límites, una verificación aplazada, una tarea aparcada) → no depende de que te acuerdes: toda fase que termina dejando algo pendiente lo persiste en el `BLOCKED.md` del change con `sdd_lifecycle.py block` y un tipo (`decision` / `deferred` / `assumed`). `/sdd:status` lo enseña como bandeja de entrada, `/sdd:ship` lista en el PR lo que viaja con él, y `/sdd:archive` **se niega a cerrar** un change con entradas sin resolver, del tipo que sean. Resolver una entrada = ejecutar su comando o decidir, y borrarla.

**Uso MiniMax, un gateway o Codex, ¿qué modelos coge?** → los que tu entorno diga. El toolkit habla en alias (`haiku`/`sonnet`/`opus`/`fable`) y Claude Code los resuelve por `ANTHROPIC_DEFAULT_<ALIAS>_MODEL`; con MiniMax los tres apuntan a `MiniMax-M3` y la escalera se aplana sola. En Codex el modelo es el de la sesión. Detalle y receta: `references/models.md`.

**Delegar solo el final** → aprueba tú proposal/design/tasks como siempre y luego `/sdd:auto <feature>`: detecta la fase y ejecuta run→review→PR. El archive queda explícitamente después del merge.

**En equipo: ¿quién tiene qué?** → la rama remota `sdd/<feature>` es el candado. `/sdd:new` avisa si la feature ya está cogida y ofrece pushear tu claim; `/sdd:status` enseña las de los demás como "en curso por otros". Si al mergear chocan dos `specs/<capability>.md`, no es ruido: dos features tocaron el mismo comportamiento — resolvedlo hablando, el merge textual es lo de menos.

**Cambió el plan/PRD** → pocos cambios: edita roadmap/steering a mano. Revisión gorda: `/sdd:init plan-v2.md` — hace *merge*, nunca regenera: lo hecho es historia, lo nuevo se inserta, y lo que contradice specs ya construidas te lo señala como candidatos a `/sdd:new` (ahí hay código real que cambiar, no solo texto).

**Endurecer una regla** (p. ej. seguridad) → edítala en `sdd/steering/security.md`. Automáticamente guiará la generación en las fases donde carga *y* la exigirá sdd-security en el panel. Regla concreta = panel afilado; regla vaga = panel débil.

**Añadir un revisor propio al panel** (performance, i18n, compliance…) → dos archivos en *tu repo*, cero cambios al plugin:

1. `sdd/steering/<lente>.md` — las reglas que hará cumplir (frontmatter `phases: [run]` o el que toque).
2. `.claude/agents/sdd-review-<lente>.md` — copia el `templates/reviewer-template.md` del plugin y rellena los huecos (referente, checks concretos, modelo: haiku si es mecánico, opus si el criterio es el producto).

El frontmatter legacy (`description`, `model`, `tools`) sigue siendo válido
para Claude y MiniMax-through-Claude. `phases` y `applies_to` son metadata
opcional del planner compartido; los reviewers existentes no necesitan
migrarse para que Codex los descubra.

El panel lo descubre por el nombre y lo lanza junto a los 3 core en `/sdd:run` y `/sdd:review`. Al estar versionado, todo el equipo lo recibe al clonar. Los core no se desactivan por proyecto (son el suelo de calidad; para secciones triviales está `solo`).

No hace falta que se te ocurran a ti: `/sdd:init` (y sus re-ejecuciones) sugiere revisores para las lentes que detecta en tu plan/código sin cobertura core — solo cuando las reglas dan para un referente afilado, porque un revisor con referente vago no encontrará nada que el contrato no descarte.

**El panel insiste en un finding que no compartes** → tras 2 rondas se detiene y decides tú. Si el finding revela que el *documento* está mal (no el código), eso es un `DESIGN-CONFLICT`: se actualiza el design/proposal contigo y se sigue — los documentos mandan, y por eso deben mantenerse verdaderos.

**Sección de puro scaffolding** → `/sdd:run <feature> solo` (sin panel).

**Una sección difícil dentro de un change normal** → márcala en `tasks.md` con `<!-- hard -->` al final de su heading (`## 3. State machine <!-- hard -->`). `run` implementa cada sección con un subagente fresco en sonnet; las marcadas van en opus. Es lo único que escala el modelo, así que úsalo a propósito. Y si un revisor de proyecto te sale en cada sección aunque no toque su ámbito, es que le falta `applies_to` en el frontmatter (`/sdd:doctor` lo avisa como `SDD028`).

**Una tarea endiablada dentro del change** (algoritmo, state machine, concurrencia — donde dos implementaciones correctas pueden diferir mucho en calidad) → tournament, señalando la tarea por su número en `tasks.md`:

```
/sdd:tournament timeline-state-machine 2.1
/sdd:run timeline-state-machine tournament 2.1   # equivalente
```

Solo esa tarea compite: 3 agentes la implementan en paralelo en worktrees aislados con ángulos distintos (simple-correcto / performance / defensivo), el panel juzga los 3 diffs contra los mismos referentes, el ganador se aplica y se injertan las ideas buenas de los perdedores. ~3× el coste de *esa tarea*; el resto del change va por run normal. No lo uses para CRUD — el panel normal ya cubre eso.

**Ver el plan de tareas de una feature grande, para navegarlo quirúrgicamente** → `/sdd:status <feature> [filtro]` — lectura pura del `tasks.md`, sin regenerarlo ni tocarlo:

```
/sdd:status cleaning           # el plan completo, con su numeración
/sdd:status cleaning 4         # solo la sección 4
/sdd:status cleaning 2.3       # solo esa tarea (con su sección de contexto)
/sdd:status cleaning pending   # todo lo que falta, numerado — para copiar el número y pasarlo a /sdd:run
/sdd:status cleaning R5        # todas las tareas que implementan el requisito R5
```

Es el complemento de lectura de los scopes de `run`: primero localizas el número exacto con `status`, luego lo ejecutas con `run <feature> <n.n>`.

**Ejecutar solo una parte del tasks.md** → el scope de `run` usa la numeración del propio archivo:

```
/sdd:run cleaning              # todas las tareas pendientes (panel por sección)
/sdd:run cleaning next         # solo la siguiente tarea, y para
/sdd:run cleaning next 3       # las 3 siguientes, y para
/sdd:run cleaning 2            # solo la sección 2 completa (panel al cerrarla)
/sdd:run cleaning 2.3          # solo la tarea 2.3 (y sus subtareas)
```

El panel salta al *completarse una sección* — una tarea suelta solo lo dispara si era la última pendiente de la suya. Y si pides algo fuera de orden (la `3.2` con la sección 1 a medias), te avisará antes: el orden del tasks.md existe para que el sistema siga funcionando tras cada sección.

**¿Cuánto costó cada feature?** → activa métricas en `/sdd:init` (extras) y reinicia la sesión. Cada fase deja su fila (tokens in/out/cache por modelo + coste estimado, subagentes incluidos) en `changes/<feature>/metrics.md`; al archivar se consolida en `sdd/metrics.md`. Úsalo para calibrar el panel: si en tu proyecto una lente no paga su coste, quítala.

**Auditar que specs y código siguen de acuerdo** → `/sdd:review` sin argumento: drift check con findings Broken/Undocumented/Stale. Si hay changes activos (en este worktree o en otro) te preguntará primero cuál de las dos cosas querías — el drift check y la review de un change son igual de legítimos y sin argumento no se distinguen.

**¿Por qué esto es así? / ¿Qué se ha hecho ya?** → `/sdd:history`: sin argumento, timeline de lo archivado (fecha, qué, coste); con feature, su ficha completa (decisiones con alternativas rechazadas, tareas, commits); con una pregunta libre ("¿por qué infra va por entorno?"), busca en el archivo y responde **con cita** (change, fecha, D#) y chequeo de vigencia — te dice si la decisión sigue en pie o la superó un change posterior. El archivo es tu registro de decisiones (ADRs gratis); esta es la forma de consultarlo.

## Mantenimiento del plugin

- **Actualizar**: `/plugin marketplace update sdd-toolkit` + `/plugin update sdd@sdd-toolkit`. Tus `sdd/` no se tocan — son datos del proyecto.
- **Cambiar el modelo de una fase o de un agente del panel**: frontmatter `model:` de `skills/<fase>/SKILL.md` o de `agents/sdd-*.md` en el repo del plugin, commit y subir versión. Aplica a todos tus proyectos (la configuración de modelos/agentes es del plugin, no del proyecto) — la tabla completa fase→modelo→agentes está en el README.
- **Ajustar el panel**: los agentes leen *tus* steering docs como referente, así que su agresividad se calibra sobre todo ahí (reglas concretas = findings útiles). Para cambiar su contrato (qué chequean, formato de findings), edita `agents/sdd-*.md`.
- **Añadir MCPs/LSPs/plugins a los catálogos**: `references/mcp-catalog.md` / `lsp-catalog.md` / `plugin-catalog.md`. Cada entrada dice cuándo ofrecerla, qué cuesta al usarla, con qué solapa y si vale en Codex; la sección "no ofrecemos" del catálogo de plugins guarda los porqués de lo que se descartó.

## Las reglas de oro

## Integridad del lifecycle

La identidad de implementación vive en `implementation_sha` y no cambia cuando
se persiste metadata. `mark-ready` y `record-pr` crean commits lifecycle
STATE-only, sin self-reference; `record-pr` no hace push. El gate ejecutable es
`scripts/sdd_lifecycle.py validate-ship`, invocado por `skills/ship`, y valida
ancestry y todos los commits del sufijo uno por uno, recorridos por
`--first-parent`. Pasan dos formas: el commit lifecycle STATE-only (allowlist
`sdd/changes/<feature>/STATE.md`) y el merge de sync de la base que registra
`sync-base` —dos padres, el segundo contenido en la base, `STATE.md` intacto—.
El push sigue siendo exclusivo de ship.

1. **Los documentos mandan.** Si el código y la spec discrepan, se arregla el que esté mintiendo — nunca se divergen en silencio.
2. **Tú eres el gate.** Ninguna fase avanza sola; aprobar el proposal es la decisión más barata e importante del ciclo.
3. **Proposals just-in-time.** El roadmap es un índice: una línea por feature más sus dependencias; el detalle se escribe cuando toca.
4. **Specs = presente.** `sdd/specs/` describe lo que el sistema *hace*, no un changelog de lo que se hizo.
5. **Changes pequeños.** Si un proposal pide más de 7 requisitos, son dos changes.
6. **Sin referente no hay finding.** El panel es tan bueno como tus steering docs sean concretos.
