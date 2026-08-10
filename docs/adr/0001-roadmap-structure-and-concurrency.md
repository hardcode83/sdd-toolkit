# ADR 0001 — Estructura del roadmap y concurrencia de sesiones

- **Fecha**: 2026-08-04
- **Estado**: aceptada · **D1 revisada parcialmente por
  [ADR 0002](0002-isolation-policy.md)** — el mecanismo (registro, evidencias,
  `check`) sigue vigente; lo que cambia es qué se hace con un veredicto `CLEAR`,
  que ahora depende de la política `isolation:` declarada por el proyecto
- **Alcance**: `sdd/roadmap.md` y su formato · `/sdd:new`, `/sdd:auto`, `/sdd:status`, `/sdd:doctor`, `/sdd:archive` · aislamiento de sesiones concurrentes · atribución de métricas
- **Se implementa en**: `roadmap-structure` (D3-D8) y `concurrent-worktrees` (D1-D2), en ese orden — ver *Implementación* al final

## Contexto

Dos problemas reportados a la vez, que resultaron estar acoplados.

**(1) Sesiones que se pisan.** Abrir varias sesiones de Claude Code sobre el mismo
clon para atacar features distintas del roadmap hace que todas compartan
directorio de trabajo y rama. La sesión A hace `git checkout -b sdd/feature-a`;
la B hace `git checkout -b sdd/feature-b` en el **mismo** directorio, arrastra
los cambios sucios de A a su rama, y A sigue escribiendo creyendo estar en la
suya.

**(2) Roadmap sin estructura.** Las entradas se acumulan sin agrupación, orden
por dependencias, tamaño ni relación entre ellas. Con muchas features sueltas en
un mismo tramo es difícil ver cuáles convergen hacia un mismo fin.

## Evidencia medida

Todo lo que sigue se verificó antes de decidir, no se asumió.

### El daño de (1) no es solo "conflictos"

`mark-ready` graba `head_branch` e `implementation_sha` en `STATE.md`, y
`verify_local_merge()` los usa como **la** prueba de merge. Una sesión que cree
estar en otra rama graba evidencia falsa. La concurrencia actual puede corromper
el gate de merge, que es el núcleo del diseño del toolkit.

### El roadmap real (AutoHostAI, 2026-08-04)

| Métrica | Valor |
|---|---|
| Entradas | 51 (21 sin marcar) |
| Encabezados de sección | **1** (`# Roadmap`) |
| Línea más larga | **9.639 caracteres** |
| Tamaño del fichero | **60 KB** (~15-18k tokens) |

La plantilla promete *"una línea por feature — barato de mantener"*. La realidad
son párrafos de 2-9 KB. Y `sdd/roadmap.md` lo leen `/sdd:new`, `/sdd:status`,
`/sdd:auto` y `/sdd:doctor` **en cada fase**.

### La información de dependencias ya se escribe, pero es inerte

Citas literales de ese roadmap:

> "Depende de `domain-foundation-financial` por la entidad `AuditLog`"
> "**Dependencias duras, y son la razón por la que no entró en `reservations`**:
> la entidad `WebhookEvent` pertenece a `domain-foundation-financial` y el job a
> `celery-jobs`"
> "**HEREDA de `pms-beds24-spike`** la medición de webhooks que allí no fue posible"
> "el entregable de esta entrada **no es código de producto**: es la entrada de
> diseño de las dos entradas siguientes"
> "cierra el cuarto ítem de `reservations`, que se entregó sin él"

No falta el dato: falta una estructura donde ponerlo. Nada puede calcular un
orden, un camino crítico ni "qué puedo paralelizar" a partir de prosa.

Se distinguen **cinco tipos de relación**, no uno — modelar solo "depende de"
perdería la mitad: `needs` (dura), `completes` (cierra lo que otra dejó a
medias), `informs-from` (spike → entrada de diseño de las siguientes),
`inherits-from` (medición o requisito aplazado que se transfiere) y
`deferred-until` (condición de disparo externa, que **no** es arista del grafo).

### El grafo es un DAG, no un árbol

`reservations-webhooks` necesita **dos** padres: `domain-foundation-financial`
(por `WebhookEvent`) y `celery-jobs` (por el job). Un árbol por indentación
admite un solo padre: no puede expresar el caso real.

### Restricciones de parseo (verificadas contra el código)

- `ROADMAP_ENTRY_RE` es `^\s*-\s+\[([ xX])\]` en `sdd-doctor.py:28` y equivalente
  en `sdd_lifecycle.py:59`. **Admite sangría**: una sub-entrada indentada se
  parsea como entrada independiente. Un árbol por indentación se vería bien en
  markdown y no le diría nada al tooling.
- Ambos parsers **ignoran cualquier línea que no case** ese patrón. Por tanto
  encabezados `## Stage N` y líneas de continuación indentadas que no empiecen
  por `- [` son retrocompatibles hoy, sin tocar código.

### La anotación del roadmap sí genera conflictos de merge

Probado con git 2.52.0: dos ramas anotando ` → changes/<feature>/` en entradas
**adyacentes** producen conflicto; con una línea de separación, git fusiona
limpio.

```
<<<<<<< HEAD
- [ ] a
- [ ] b → changes/b/
=======
- [ ] a → changes/a/
- [ ] b
>>>>>>> A
```

Y el caso de uso que motiva todo esto — atacar varias entradas a la vez — toma
justamente entradas **consecutivas**. La causa de fondo es que esa anotación es
*estado derivado* duplicado en un fichero compartido: `▶ in progress` se calcula
de `sdd/changes/*/STATE.md`, que es donde la regla 8 ya pone la verdad.

Esto invalida la afirmación que hacía `README.md` en su *Perfil de conflictos*
("`roadmap.md` conflictos triviales de línea").

### Las métricas ya están rotas, y los worktrees lo empeoran en silencio

- `usage-mark.sh:20` escribe un único `$root/.sdd-usage/current-task`, y el sink
  etiqueta *todos* los datapoints con lo que diga ese fichero en ese instante.
  Con dos sesiones concurrentes gana el último que escribe.
- `.claude/settings.json` está versionado y `OTEL_EXPORTER_OTLP_ENDPOINT` se lee
  al arrancar sesión, así que **todas** las sesiones exportan a
  `127.0.0.1:4318`. Con worktrees solo el primer sink hace bind; el resto muere
  y todas las métricas caen en el ledger del primer worktree con su atribución.
  Sin error visible.
- Arreglo barato: `usage-sink.py:88` **ya captura `at.get("session.id")`** por
  fila. Basta atribuir por sesión en vez de por un puntero global.

### Entorno y herramientas disponibles

- El entorno del Bash tool expone `CLAUDE_CODE_SESSION_ID` y `CLAUDE_PID` →
  permite un registro de sesiones real con liveness por `kill -0`, no una
  heurística.
- `EnterWorktree` cambia el cwd de la sesión de verdad (no solo prefija rutas),
  crea en `.claude/worktrees/`, y su contrato admite que la instrucción venga de
  "project instructions" — una skill lo es. Su `worktree.baseRef` por defecto es
  `fresh`: rama desde `origin/<default>`, ignorando commits locales sin pushear.
- `ExitWorktree` solo toca worktrees creados en **la misma** sesión: no sirve
  para limpiar los de otra.
- `/sdd:diagram` es un generador genérico de arquitectura: saca PNG a
  `~/diagrams/` y necesita `mmdc` (npm global + Chrome de puppeteer). Dependencia
  pesada que falla justo en el escenario desatendido de `/sdd:auto`.

## Decisiones

### D1 — Worktree es el mecanismo de aislamiento, con autodetección y confirmación

Una feature = una rama = un worktree. Se propone cuando hay **conflicto real**
detectado (otra sesión viva en el registro, o HEAD en otra rama `sdd/` con árbol
sucio); `/sdd:auto`, que no pregunta nunca, lo aplica directamente.

*Por qué encaja*: el estado de SDD ya está particionado por feature
(`sdd/changes/<feature>/` no lo comparte nadie). El flujo ya estaba diseñado
como si fuera paralelo, solo le faltaba el aislamiento físico. Y el toolkit ya
usa worktrees para `tournament`.

*Alternativas descartadas*: **siempre worktree** (paga el bootstrap de `.env` /
`node_modules` incluso trabajando en solitario); **opt-in por proyecto** (no
arregla nada hasta que te acuerdas de activarlo, que es justo el problema).

> **Revisado por [ADR 0002](0002-isolation-policy.md).** El camino `CLEAR`
> resultó *fabricar* las evidencias #2 y #3 que este mismo check reporta después
> como `CONFLICT`: la primera feature nunca se aísla, se queda en el clon
> principal y lo deja en la rama de otra feature y sucio. ADR 0002 mantiene esta
> detección y el defecto (`on-conflict`, donde la objeción del bootstrap sigue
> siendo válida), y añade una política declarada por el proyecto —`isolation:
> always`— que aísla también la primera. El opt-in ya no es un sustituto de la
> detección, que era la razón de descartarlo aquí, sino una capa por encima.

### D2 — El registro de sesiones vive en el directorio git común

`$(git rev-parse --git-common-dir)/sdd/sessions.json`, una entrada por sesión
(`session_id`, `pid`, `worktree`, `feature`, `branch`, `started`, `last_seen`).

*Por qué ahí*: `--git-common-dir` es compartido por todos los worktrees y vive
dentro de `.git`, así que nunca aparece en `git status` ni se puede committear
por accidente. La liveness por `kill -0` purga las entradas muertas: no hay
locks zombis.

Compone con el mecanismo existente sin sustituirlo: **rama remota
`sdd/<feature>` = claim de equipo; registro local = claim de máquina.**

### D3 — Los stages agrupan por resultado, y el orden se deriva del DAG

Encabezados `## Stage N — <objetivo>` que agrupan por **fin a alcanzar** ("PMS
real en producción"), no por categoría. Las etiquetas de categoría del proyecto
(`[FE]`, `[BE]`, `[INFRA]`…) se quedan como eje ortogonal.

*Por qué no agrupar por categoría*: esconde las cadenas, porque las cadenas
cruzan categorías (`user-management` `[BE]` depende de
`domain-foundation-financial` `[BE]`, pero `hardening-release` `[FE]` consume sus
endpoints).

*Alternativas descartadas*: **solo dependencias sin stages** (21 entradas
sueltas siguen sin narrativa de destino); **stages con timeline explícito**
(introduce fechas que envejecen y hay que mantener a mano).

### D4 — Los metadatos van en una sub-línea de continuación

```
- [ ] reservations-webhooks — [BE] cierra el cuarto ítem de `reservations`…
      needs: domain-foundation-financial, celery-jobs · size: M · kind: feature
```

*Por qué*: legible, editable a mano, retrocompatible sin tocar parsers, y no
alarga la línea de la entrada.

*Alternativas descartadas*: **sufijo en la misma línea** (al final de una línea
de 9 KB no lo encuentra nadie); **comentario HTML** (hay precedente con
`<!-- panel: PASS -->` en `tasks.md`, pero aquí el metadato se quiere *ver*);
**fichero aparte `roadmap.deps.yaml`** (rompe el "editable a mano, barato" de la
plantilla y crea dos fuentes de verdad).

### D5 — El roadmap deja de anotarse; el estado se deriva

Se elimina la escritura de ` → changes/<feature>/` durante el flujo. `▶ ✓ PR ⛔`
se derivan de `sdd/changes/*/STATE.md`. El tick de `/sdd:archive` se mantiene:
es post-merge y está serializado.

*Por qué*: elimina la clase de conflicto medida arriba, y quita una duplicación
de estado derivado en un fichero compartido.

### D6 — El roadmap es un índice; el análisis largo se carga selectivamente

`sdd/roadmap.md` queda como índice escaneable (línea de entrada + sub-línea de
metadatos). El análisis largo va a `sdd/roadmap/<feature>.md`, que solo lee
`/sdd:new` de esa entrada.

*Por qué*: mismo principio de carga selectiva que ya usa `sdd/steering/` con
`applies_to`/`phases`. En el caso medido, 60 KB → ~3 KB: ~90% menos de contexto
por fase. El razonamiento de esas entradas es valioso (es material del futuro
proposal), así que se mueve, no se borra.

*Alternativas descartadas*: **solo un índice de stages arriba** (los 60 KB se
siguen leyendo); **no tocarlo** (el coste se queda).

### D7 — Las vistas son texto primero; el DAG se calcula, no se dibuja

`scripts/sdd_roadmap.py` (determinista, stdlib, patrón de `sdd_lifecycle.py`)
concentra el grafo: `parse` · `validate` · `frontier` · `waves` ·
`critical-path` · `mermaid`. `/sdd:status` imprime olas, frontera, camino crítico
y bucket de hojas en texto; el DAG se emite como bloque ` ```mermaid ` (se
renderiza en GitHub y en visores de markdown). PNG solo a demanda, delegando en
`/sdd:diagram`.

**El grafo se renderiza solo donde hay aristas.** En los datos medidos, las
entradas `[INFRA]` de hardening son mayormente hojas independientes mientras las
`[BE]` de dominio forman cadenas reales. Para las hojas se lista plano con la
etiqueta *"sin dependencias, cualquier orden"*, en vez de dibujar un árbol de un
nivel que finge información.

*Alternativas descartadas*: **comando propio `/sdd:roadmap`** (solape claro con
`status`); **fichero de vista versionado** (estado derivado versionado: se
desincroniza y da conflictos de merge, justo lo que D5 acaba de quitar).

### D8 — El roadmap se arregla antes que la concurrencia

*Por qué*: el DAG es prerequisito real del otro arreglo — define **qué** es
paralelizable. Hoy `/sdd:auto N` coge las N primeras **en orden de fichero**, y
puede arrancar `reservations-webhooks` antes de que exista `WebhookEvent`. Con
el grafo, coge N entradas **de la frontera**, paralelizables por construcción,
cada una en su worktree.

Además los dos changes tocan el mismo fichero, la misma plantilla y los mismos
parsers (D5 vive en `update_roadmap()` y `pointer_checks()`): hacerlo en este
orden lo toca una vez.

*Alternativa descartada*: **un solo change conjunto** (contradice el principio
de 3-7 requisitos por change del propio toolkit).

## Consecuencias

**Se gana**

- Concurrencia real de features sin corromper la evidencia de merge.
- Un orden de ejecución calculable, validable y con camino crítico visible.
- `/sdd:auto` paraleliza sobre la frontera en vez de sobre el orden del fichero.
- `/sdd:new` gana un gate: avisa si abres una entrada con `needs` sin cerrar.
- `doctor` valida ciclos, dependencias inexistentes y violaciones de orden (una
  entrada archivada cuya dependencia sigue abierta) — caza errores reales.
- ~90% menos de contexto de roadmap por fase.
- Atribución de métricas correcta por sesión.

**Se paga**

- Los metadatos de dependencias son **manuales**: nadie los infiere, y un
  roadmap sin ellos degrada a lo de hoy (lista plana, orden por posición). El
  formato tiene que seguir siendo barato o no se mantendrá.
- Migración one-off de los roadmaps existentes. Las entradas **archivadas no se
  tocan**: son historial, y la regla 8 ya dice que los registros históricos no
  se reescriben.
- Un worktree necesita bootstrap de lo no versionado (`.env`, `.venv`,
  `node_modules`). Es la fricción nº1 real de los worktrees, y se declara en
  `sdd/project.md` (regla 9: los comandos del proyecto son del proyecto).
- `/sdd:archive` queda serializado en el worktree principal: muta `sdd/specs/`,
  tickea el roadmap y mueve directorios. Es post-merge, así que ya era cierto de
  hecho; ahora es precondición explícita.
- El adaptador de Codex no tiene `EnterWorktree`, así que allí el aislamiento es
  manual (los scripts sí funcionan tal cual).

## Implementación

`roadmap-structure` (D3-D8): `templates/roadmap-template.md`,
`scripts/sdd_roadmap.py` + sus tests, `update_roadmap()` en `sdd_lifecycle.py`,
`graph_checks()` en `sdd-doctor.py` (`SDD018`-`SDD023`), y los gates en `new`,
`auto`, `status`, `doctor`, `init`.

`concurrent-worktrees` (D1-D2): `scripts/sdd_session.py` + sus tests,
`references/isolation.md` (el protocolo, para no repetirlo en cinco skills),
regla compartida 10, gates en `new`/`design`/`tasks`/`run`/`review`/`auto`/
`archive`/`status`/`init`, sección *Worktree bootstrap* en
`templates/scaffold/project.md`, `SDD024`, y el arreglo de métricas
(`usage-dir.sh` nuevo + `usage-mark.sh`, `usage-sink.py`, `usage-phase.sh`,
`usage-sync.py`).

### Desviaciones respecto al plan

**Los checks de worktree en el doctor se quedaron en uno, no cuatro.** El plan
preveía `SDD024`-`SDD027` (worktree huérfano, gitignore ausente, claim obsoleto,
rama del worktree ≠ feature ligada). Al implementarlo apareció una frontera que
el plan no había visto: los fixtures de `sdd-doctor.py` son **árboles de proyecto
commiteados**, y tres de esos cuatro checks dependen del registro de sesiones, que
es estado de **máquina** en el directorio git compartido. Un fixture no puede
expresarlo, y `tests/test_sdd_doctor.py` exige —con razón— que el registro de
fixtures cubra todos los códigos publicados.

Se resolvió respetando la frontera en vez de debilitar el test: el doctor
conserva solo `SDD024` (`.claude/worktrees/` sin ignorar, puro sistema de
ficheros), y los huérfanos del registro los reporta `sdd_session.py orphans`, que
la skill `/sdd:doctor` ejecuta también, etiquetando cuál es estado de proyecto y
cuál de máquina. Coincide además con la tabla de propiedad del README, que ya
distinguía *Proyecto* de *Máquina*. El check de "rama del worktree ≠ feature" se
descartó: `/sdd:run` ya lo verifica **antes de la primera edición**, que es donde
sirve para prevenir el daño en vez de constatarlo.
