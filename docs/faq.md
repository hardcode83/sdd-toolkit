# FAQ — decisiones de diseño y preguntas reales

Respuestas a las preguntas que surgieron construyendo y usando el toolkit. La [guía](guide.md) explica *cómo* usarlo; esto explica *por qué* es así.

Las decisiones grandes —las que se investigaron con datos y descartaron alternativas— viven en [`adr/`](adr/) y se enlazan desde aquí. Este FAQ da la respuesta corta; la ADR da la evidencia y lo que se descartó.

## ¿Por qué los revisores core son architect/security/qa y no otros?

No es un estándar del sector — es la terna con **referente garantizado**: el contrato del panel prohíbe findings sin referente citado, y el flujo SDD produce exactamente tres tipos de verdad-escrita en todo proyecto: el design (D# → architect), el steering de seguridad (reglas → security) y los criterios EARS (R# → qa). Además cubren las tres clases ortogonales de fallo: ¿está construido *como se decidió*?, ¿hace *daño*?, ¿hace *lo que se pidió*?

Lo excluido fue igual de deliberado: **estilo/mantenibilidad** no tiene agente porque es la lente más propensa a opinión-sin-referente (los linters cubren su parte objetiva; si tu proyecto tiene reglas de estilo con dientes, van a un steering doc y las aplica architect). Cualquier otra lente (performance, i18n, tenancy…) es legítima *donde exista su referente* — por eso son revisores de proyecto (`.claude/agents/sdd-review-*`), no core.

## ¿Qué hago con el PRD después del init? ¿Lo borro cuando el flujo lo haya absorbido?

No — pero entiende qué absorbió el init y qué no. El init extrae solo la **capa de dirección** (visión → product.md, decisiones → project/architecture, features → roadmap). El detalle (entidades, endpoints, flujos) se consume **just-in-time**: cada `/sdd:new` lee sus secciones cuando le llega el turno. Borrar el PRD rompería la materia prima de las entradas pendientes y las citas de los proposals archivados (`/sdd:history` resuelve contra él).

El ciclo de vida es una **degradación de autoridad**, no un borrado: fuente de dirección (init) → fuente de requisitos just-in-time (mientras el roadmap lo consume) → referencia histórica (roadmap agotado; las specs son la verdad). Convención: vive en `docs/`, nombre limpio y versionado (`docs/PRD-v5.md`).

## Llega un PRD v6 — ¿qué pasa con v5 y con lo construido?

`/sdd:init prd6.md` hace **merge, nunca regenera**, con una bifurcación crítica por cada decisión cambiada:

- **v6 solo añade features** → entradas nuevas en el roadmap donde toque; lo hecho y lo en curso, intocable; v5 queda como estrato histórico y `project.md` apunta a v6.
- **v6 revierte decisiones**: si afectan a lo *no construido* → se edita steering/roadmap con diff a la vista (papel contra papel, barato). Si contradicen **specs construidas** → el init NO toca ni spec ni código: te las señala como **candidatos a `/sdd:new`** — hay código real que discrepa, y cambiar el documento no cambia el sistema. Cada contradicción se vuelve un change correctivo, y solo su archive actualiza la spec. Las specs nunca mienten en ningún momento intermedio.

Y la regla de granularidad: **documento que describe el producto → `init`; documento que describe una feature → `new`**. Si te equivocas, `new` detecta el olor a plan y te ofrece el camino correcto antes de escribir nada.

## ¿No es tirar tokens panelar dos veces (run por sección + review por feature)?

Era una redundancia real y se eliminó estructuralmente: el panel por sección **persiste su veredicto** (`<!-- panel: PASS <fecha> -->` en el heading de la sección en tasks.md), y `/sdd:review` es **incremental** — las secciones ya en PASS no se re-auditan línea a línea; sobre ellas solo se revisa lo que la escala sección no puede ver (interacciones entre secciones, coherencia global de D#, archivos de una sección tocados por otra posterior). Lo que siempre corre a escala feature: la matriz R#→met/unmet y el scope creep acumulado. Las secciones sin PASS (panel saltado con `solo`, interrumpido por límites) sí reciben review completo — review es también el mecanismo de recuperación. Los dos niveles compran cosas distintas: la sección compra *feedback temprano* (arreglar el bug de la sección 2 antes de construir encima); la feature compra *lo transversal*.

## ¿Cuándo corre `/sdd:review` antes del PR?

| Situación | ¿Review? |
|---|---|
| Run interactivo con panel completado en todas las secciones | **Obligatorio pero incremental** — valida lo transversal y persiste `READY_FOR_PR` sin volver a pagar la revisión línea a línea |
| Panel incompleto o saltado (`solo`, límites de sesión) | **Obligatorio** — review a escala feature es el mecanismo de recuperación |
| Modo auto | Siempre (cableado): nadie humano miró durante la ejecución |
| Cambio trivial sin design | Obligatorio para registrar aprobación local; el scope del panel puede ser mínimo |

El drift check (`/sdd:review` sin argumento) es otra cosa: mantenimiento periódico specs↔código, fuera del ciclo de cualquier change.

## ¿El panel se lanzó solo — quién decidió eso?

Nadie decidió nada creativo: es la regla del paso 3 de `run` — *última tarea de una sección marcada + la sección tocó código de producción → panel*. Dos criterios objetivos, cero discrecionalidad. Tournament, en cambio, **jamás** se autodispara: requiere que tú lo pidas (`tournament <tarea>`).

## ¿Qué diferencia hay entre los revisores de `agents/` y "los agentes del tournament"?

`agents/` contiene **solo revisores**: identidades persistentes, read-only, con contrato de findings. Los 3 implementadores del tournament son **efímeros** — agentes genéricos lanzados con worktree aislado y un ángulo distinto cada uno (simple-correcto / performance / defensivo); escriben código y desaparecen. En tournament, los revisores hacen de *juez* de los 3 diffs. Mnemotécnica: `agents/` = quien verifica; tournament = quien compite.

## Un compañero lleva semanas con una versión vieja del plugin y nadie se enteró — ¿por qué?

Porque `autoUpdate` viene **apagado** para todo marketplace que no sea oficial de Anthropic, y sin él una instalación se queda clavada en la versión con la que nació. Sin aviso, sin prompt, sin nada. Medido en una instalación real: tres días y dos releases de retraso antes de que alguien lo notara, y solo porque fue a mirar.

El arreglo es un campo en el `.claude/settings.json` **versionado del proyecto** (no en el tuyo personal), hermano de `source`:

```json
"extraKnownMarketplaces": {
  "sdd-toolkit": {
    "source": { "source": "github", "repo": "hardcode83/sdd-toolkit" },
    "autoUpdate": true
  }
}
```

`/sdd:init` lo escribe por ti al configurar la distribución de equipo, y al re-ejecutarlo sobre un proyecto que no lo tenga te ofrece añadirlo.

Y no es cosmético: las garantías del flujo —reglas compartidas, códigos del doctor, gates del lifecycle— **solo se sostienen si todo el equipo corre la misma versión**. Un `STATE.md` que escribe una versión con campos que otra no conoce, o un `SDD0xx` que una reporta y la otra no, convierte "el flujo lo valida" en "el flujo lo valida en mi máquina". Quien quiera control manual lo desactiva en su `.claude/settings.local.json`, que es gitignorado y tiene precedencia.

Detalle de comportamiento, verificado: refresca marketplace **e** instalación en una sola operación, **al arrancar sesión** (la sesión en curso no se entera), y solo para el proyecto en el que abres la sesión.

## ¿Cómo llegan las actualizaciones del plugin a quien lo usa?

Si el marketplace se registró **desde git** (`/plugin marketplace add hardcode83/sdd-toolkit`): pull en background automático, y el campo `version` de `plugin.json` marca cuándo hay release (subir el número = distribuir). Solo distribuye lo que está en **`main`** — una PR sin mergear no le llega a nadie. Registrado por **ruta local**: siempre manual (`/plugin marketplace update` + `/plugin update`). Y el plugin se instala **por usuario**, no por repo: lo que el proyecto versiona (`enabledPlugins` en settings) es la *declaración* de que lo usa.

## ¿Dónde queda lo que se interrumpe a medias (un panel cortado, una duda, una tarea aparcada)?

En la **cola de pendientes** del change: `sdd/changes/<feature>/BLOCKED.md`. Regla compartida nº 5: ninguna fase puede terminar dejando deuda solo en la conversación — la persiste con tipo (`decision`: te toca a ti / `deferred`: reanudable, con su comando exacto). `/sdd:status` la muestra como bandeja de entrada; `/sdd:archive` se niega a cerrar con entradas vivas. Un panel interrumpido se reanuda como `/sdd:review <feature>` — cubre lo pendiente y las interacciones.

## ¿Por qué auto ya no archiva antes de abrir el PR?

Porque implementación local, revisión remota, merge y archive son hechos
distintos. El flujo anterior podía actualizar specs vivas y roadmap antes de
tener CI o merge. Ahora `STATE.md` distingue `READY_FOR_PR`, `PR_OPEN`,
`MERGED` y `ARCHIVED`: auto termina en PR, y archive consulta `gh` para exigir
repositorio/ramas/SHA revisado, estado `MERGED` y merge commit. Los archives
históricos sin metadata se conservan; a un change activo legacy se le exige
asociar evidencia real, nunca inventarla.

## ¿Por qué los modelos por fase son del plugin y no por proyecto?

Porque el plugin se instala una vez por usuario y las skills se comparten: editar frontmatter afectaría a todos los proyectos igualmente — así que se asume y se documenta (editar `skills/<fase>/SKILL.md` o `agents/*.md`, commit, subir versión). El perfil por-proyecto existió en la era pre-plugin y se sacrificó a cambio de distribución centralizada. Las **reglas** sí son por proyecto (steering) — y son el mando de calibración que de verdad importa.

## ¿Por qué el roadmap no se convierte en proposals desde el día uno?

Porque el proposal de la feature 5 escrito el día uno estaría anclado a lo que el plan *imaginaba*; escrito cuando le toca, se ancla a las **specs reales** de las features 1-4. El roadmap es un índice —una línea por feature más sus dependencias, barato de mantener y de reordenar—; el proposal es caro y caduca. Just-in-time no es pereza — es precisión.

## ¿En equipo, quién tiene qué feature? ¿Y si dos personas cogen la misma?

Y del lado del PR, `/sdd:ship` sincroniza la base en la rama antes de abrirlo (merge, nunca rebase): el bookkeeping append-only lo une él, y un conflicto de código lo resuelve, lo vuelve a verificar con el comando del proyecto y solo entonces publica.

El candado es la **rama remota `sdd/<feature>`**: `/sdd:new` comprueba si existe (y avisa con el dueño), y ofrece pushear tu claim antes de escribir; auto lo publica *antes* de trabajar. `/sdd:status` enseña las ramas de otros como "en curso por otros". Los conflictos de merge restantes son señal, no ruido: dos features tocando la misma `specs/<capability>.md` tenían que coordinarse igualmente.

Ese candado es de *equipo*. El caso de **varias sesiones tuyas en la misma máquina** es otro problema y tiene su propia respuesta, abajo. Los dos checks corren, porque la rama de un compañero y el proceso de un compañero son hechos distintos.

## Abro dos sesiones para dos features y se pisan — ¿por qué worktree y no simplemente ramas?

Porque el problema no son las ramas, es que **comparten el directorio de trabajo**. Dos sesiones sobre el mismo clon comparten HEAD: la segunda hace `git checkout -b sdd/<otra>` y git se lleva con ella los ficheros sin commitear de la primera, que sigue escribiendo creyendo estar en su rama.

Y el daño no se queda en un conflicto: `mark-ready` graba `head_branch` e `implementation_sha` como **la** prueba del gate de merge (regla 8). Una sesión descolocada graba evidencia falsa — se corrompe el núcleo del diseño, no un detalle de ergonomía. Por eso `/sdd:run` verifica la rama **antes de la primera edición** y para en seco si no cuadra, en vez de "arreglarlo" con un checkout que arrastraría ficheros ajenos.

Un worktree da rama *y* directorio propios compartiendo el object store, así que es barato. Encaja especialmente bien porque el estado de SDD ya estaba particionado por feature: `sdd/changes/<feature>/` no lo comparte nadie. El flujo ya estaba diseñado como si fuera paralelo — solo le faltaba el aislamiento físico.

## Mi clon principal acaba siempre en la rama de otra feature y sucio — ¿eso es normal?

Era el comportamiento, sí, y ya no tiene por qué serlo. `check` responde `CLEAR`
cuando el clon está libre, así que la **primera** feature en vuelo se quedaba
donde estaba: movía HEAD a `sdd/<primera>` y dejaba el árbol sucio. Solo se
aislaba de la segunda en adelante. El detalle incómodo es que ese estado —HEAD en
la rama de otra feature, changes en curso de otras features— es **exactamente la
evidencia #2 y #3** que el check le reporta después a la siguiente: el camino
feliz fabricaba la señal que el detector detecta.

El arreglo es declararlo en la sección *Worktree bootstrap* de `sdd/project.md`:

```markdown
isolation: always
```

Entonces cada feature entra en su worktree, la primera incluida, y el clon
principal se queda en la rama por defecto y limpio — todas las sesiones arrancan
del mismo mundo. El defecto sigue siendo `on-conflict` (lo de siempre), porque
`always` hace que **cada** feature pague el bootstrap del worktree que antes la
primera esquivaba: BD vacía, reinstalar dependencias, su propio disco. Es una
decisión del proyecto, no del toolkit: `/sdd:init` la pregunta y `/sdd:doctor`
dice cuál está en vigor. Razonamiento completo en
[ADR 0002](adr/0002-isolation-policy.md).

## ¿Por qué el registro de sesiones vive en `.git/` y no en `sdd/`?

Porque es estado de **máquina**, no de proyecto, y las dos propiedades que necesita las da ese sitio y no otro: `$(git rev-parse --git-common-dir)` es **compartido por todos los worktrees** del repo (así que las sesiones se ven entre ellas) y está **dentro de `.git`** (así que nunca aparece en `git status` ni se puede committear por accidente).

La liveness sale del `pid` registrado (`kill -0`), lo que elimina la peor propiedad de un candado: **no hay candados zombis**. Una sesión que muere se lleva su claim. Y guarda dos cosas distintas a propósito — las *sesiones* se podan por liveness, los *bindings feature→worktree* sobreviven, porque el trabajo a medias también sobrevive a la conversación que lo empezó.

Misma frontera en `/sdd:doctor`: valida estado de proyecto (sus fixtures son árboles commiteados) y delega el estado de máquina en `sdd_session.py orphans`.

## Activé worktrees y ahora los tests fallan — ¿está roto?

Casi seguro que no: un worktree recién creado no tiene lo que git no versiona — `.env`, `.venv`, `node_modules`, tu base de datos local. Es la fricción número uno real de los worktrees, y por eso se declara en la sección **Worktree bootstrap** de `sdd/project.md`: qué hace falta y el comando exacto para conseguirlo (regla 9 — los comandos del proyecto son del proyecto, el plugin no los adivina).

Si la verificación falla por un fichero local que esa sección no menciona, **eso es el hallazgo**: se documenta ahí. El flujo tiene instrucciones explícitas de no adivinar qué copiar, porque copiar el fichero equivocado es peor que fallar.

## ¿Y las métricas por feature con dos sesiones en marcha?

Estaban rotas antes de esto, y los worktrees lo empeoraban en silencio. Dos causas: `usage-mark.sh` escribía un único `current-task` global (last-writer-wins, así que una sesión facturaba sus tokens a la feature de la otra), y como el endpoint OTLP está en el `settings.json` **versionado** y se lee al arrancar sesión, todas las sesiones exportan al mismo puerto — con worktrees solo el primer sink bindea y todo cae en su log.

El arreglo salió barato porque el sink ya recibía `session.id` en cada datapoint: **un sink y un log por repositorio** (resuelto al worktree principal) y **atribución por sesión**. El `current-task` sigue existiendo como fallback para datapoints sin sesión identificable, así que nada que se atribuía antes deja de atribuirse.

## ¿Por qué el roadmap tiene stages y una sub-línea de metadatos, y no es una lista plana?

Porque una lista plana no puede responder a "¿qué puedo atacar ya?" ni a "¿qué features convergen hacia el mismo fin?". La información de dependencias se escribía igualmente — pero en prosa dentro de la entrada, donde es inerte: nada podía calcular un orden.

Tres decisiones detrás, con su evidencia medida en [ADR 0001](adr/0001-roadmap-structure-and-concurrency.md):

- Los **stages agrupan por resultado**, no por categoría (D3). Agrupar por `[FE]`/`[BE]` escondería las cadenas, porque las cadenas cruzan categorías.
- Los metadatos van en **sub-línea de continuación** (D4), no en la propia línea de la entrada: al final de un párrafo de varios KB no los encuentra nadie.
- El grafo **se calcula, no se dibuja** (D7) — y solo se renderiza donde hay aristas. Un árbol de un nivel sobre entradas independientes finge información que no existe. Y no es un árbol: una entrada puede necesitar dos padres, así que la indentación no daba para expresarlo.

## ¿Por qué el roadmap ya no se anota con `→ changes/<feature>/` al empezar una entrada?

Porque era estado derivado duplicado en un fichero compartido, y se medía el coste: dos ramas anotando entradas **adyacentes** dan conflicto de merge garantizado — y trabajar en paralelo toma justamente entradas consecutivas. El estado (`▶ ✓ PR ⛔`) se deriva de `sdd/changes/*/STATE.md`, que es donde la regla 8 ya pone la verdad. El tick de `/sdd:archive` se mantiene: es post-merge y está serializado. Detalle en [ADR 0001](adr/0001-roadmap-structure-and-concurrency.md) D5.

## ¿Por qué review, ship, archive, status e history corren en un subagente (`context: fork`)?

Porque la regla 11 como consejo no funcionaba y se midió: en 80 features de un proyecto real (sep 2026), el 62 % de las sesiones tocó más de una feature, el hilo principal fue el 75 % del gasto, `run` promedió 444k de contexto por request y el 79 % de su coste fue releer ese contexto; el panel de subagentes, del que sospechábamos, fue el 19 %. Y el 77 % del gasto fue Opus aunque las skills pidieran Sonnet: el `model:` de una skill inline no gobierna la sesión. `context: fork` resuelve las dos cosas a la vez: la fase arranca sin historial, y su `model:`/`effort:` se respetan de verdad. El precio es que ningún subagente tiene `AskUserQuestion`, así que las fases en fork terminan con un bloque `HANDOFF` (qué hicieron, qué hay que decidir, el comando exacto por respuesta) y la conversación que las llamó pregunta y ejecuta; en `archive`, eso significa que el cierre (commit → publish → doctor → retire) lo ejecuta el llamante desde ese bloque. Codex no tiene fork ni `AskUserQuestion`, e ignora esas claves del frontmatter: para él el `HANDOFF` es, simplemente, el gate. `run`, `new`, `design` y `tasks` siguen inline porque sus gates conversan con el usuario a cada paso. Detalle y cifras en [ADR 0003](adr/0003-forked-phases.md).

## ¿Por qué `run` delega cada sección a un subagente en vez de implementar él?

Porque `run` era el 56 % del gasto medido y casi nada de eso era trabajo: el hilo principal iba a 444k de contexto por request y el 79 % de su coste era releer ese contexto acumulado (diffs, salidas de test, siete informes de revisor por sección, dos rondas de fix). Un implementador fresco por sección arranca en ~30k, recibe en el prompt todo lo que necesita (tareas, R# con EARS, D# citadas, steering, comandos) y devuelve treinta líneas sin diffs; el orquestador solo comprueba en disco lo que el informe afirma. Es el patrón de cc-sdd, GSD y Superpowers, y la razón de que el `model:` importe: el de un subagente sí gobierna, así que las secciones corren en sonnet salvo las marcadas `<!-- hard -->`. Lo que se pierde —la continuidad entre secciones— lo recupera `## Implementation Notes` en `tasks.md`, que cada implementador lee y amplía (regla 1: el estado vive en `sdd/`). Los revisores devuelven solo su sobre JSON por lo mismo. Bajo Codex, sin subagentes, `run` implementa inline con el mismo contrato. Cifras en [ADR 0004](adr/0004-run-orchestrator.md).
