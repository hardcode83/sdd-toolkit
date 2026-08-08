# ADR 0002 — El aislamiento en worktree es política del proyecto, no reacción al conflicto

- **Fecha**: 2026-08-08
- **Estado**: aceptada
- **Alcance**: `references/isolation.md` · regla compartida 10 · `/sdd:new`,
  `/sdd:auto`, `/sdd:init`, `/sdd:doctor` · `scripts/sdd_session.py`,
  `scripts/sdd-doctor.py` (`SDD024`, `SDD026`) ·
  `templates/scaffold/project.md`
- **Revisa**: [ADR 0001](0001-roadmap-structure-and-concurrency.md) **D1**
  (*cuándo* se aísla). **D2** (dónde vive el registro, liveness por pid) sigue
  vigente sin un solo cambio, y el mecanismo de detección de D1 —el registro, las
  tres evidencias, `check`— tampoco se toca: lo que cambia es qué se hace con un
  veredicto `CLEAR`.

## Contexto

ADR 0001 D1 decidió que el worktree se propone **cuando hay conflicto real
detectado**. El disparador es `sdd_session.py check --feature <f>`, y la tabla de
`references/isolation.md` lo enrutaba así: en `CLEAR` el flujo sigue en el
directorio actual y solo hace `claim`; en `CONFLICT` se ofrece el worktree
(interactivo) o se aplica sin preguntar (`/sdd:auto`).

`CLEAR` significa «el clon está libre». Por tanto **la primera feature en vuelo
siempre ocupa el clon principal y nunca recibe worktree**. Solo se aísla de la
segunda en adelante.

## Evidencia

### El fallo se observó, no se supuso

En un proyecto real con dos sesiones vivas:

1. La feature A ejecutó `/sdd:new` sobre un clon limpio con HEAD en `main` →
   `CLEAR` → se quedó en el clon principal, movió HEAD a `sdd/A` y dejó el árbol
   sucio.
2. La feature B ejecutó `/sdd:new` después → `CONFLICT` → worktree en
   `.claude/worktrees/sdd+B`. **Correcto.**
3. El clon principal quedó clavado en la rama de otra feature y con ficheros sin
   commitear. Cada shell nuevo abierto ahí arranca en `sdd/A`, sucio. Cualquier
   herramienta que espere que el clon esté en la rama por defecto —un wrapper de
   `git checkout main`, un alias de «abre una sesión nueva en main»— se rompe, y
   la única respuesta segura es «espera a que termine la sesión A».

### El camino `CLEAR` fabrica la evidencia que el check llama `CONFLICT`

Es el argumento central, y es estructural, no una mala racha. De las tres
evidencias de conflicto que documenta `references/isolation.md`, dos las **produce
el propio flujo** al haber dejado trabajar en sitio a la feature anterior:

| Evidencia | Quién la crea |
|---|---|
| #1 otra sesión viva en el registro | El entorno (dos sesiones abiertas) |
| #2 HEAD en la rama de otra feature, peor si el árbol está sucio | **El flujo**, en el `CLEAR` de la feature anterior |
| #3 este clon tiene changes en vuelo de otras features | **El flujo**, ídem |

La regla detecta un estado que el flujo creó una feature antes. Un detector cuyo
propio camino feliz genera la señal que detecta no está midiendo el entorno: está
midiendo su propia historia.

### El coste de segundo orden: las sesiones no son uniformes

La primera sesión es especial y todas las siguientes arrancan de un mundo
distinto —una en el clon con HEAD movido, las demás en worktrees limpios—. «Abre
N sesiones en paralelo, cada una partiendo de la rama por defecto» no es
expresable hoy. Y es justo el caso de uso que ADR 0001 D8 puso como objetivo:
`/sdd:auto N` cogiendo N entradas de la frontera, *cada una en su worktree*.

### Lo que ADR 0001 midió sobre el coste sigue siendo cierto

`references/isolation.md` documenta que cada worktree levanta su propio stack,
arranca con **base de datos vacía**, reinstala dependencias y ocupa su disco; y
que hay una segunda mitad que se olvida, los **recursos exclusivos** (un puerto
publicado, un `container_name` fijo, un daemon en un socket conocido). Hoy la
primera feature esquiva todo eso. Ese coste no ha desaparecido y es la razón por
la que este ADR **no cambia el defecto**.

## Decisiones

### D1 — La política la declara el proyecto; el defecto no se toca

Una línea en la sección **Worktree bootstrap** de `sdd/project.md`:

```markdown
isolation: always
```

Valores: `always` (cada feature en su worktree, la primera incluida) y
`on-conflict` (**defecto**: worktree solo con evidencia). Un proyecto que no
declara nada se comporta exactamente igual que antes de este ADR.

*Por qué del proyecto y no del toolkit*: la regla compartida 9 ya dice que esta
clase de decisión —lo que cuesta levantar y verificar este proyecto— es del
proyecto, y `references/isolation.md` ya enrutaba las compensaciones de worktree a
`sdd/project.md`. El coste de bootstrap y la existencia de recursos exclusivos son
propiedades del proyecto, no del flujo.

**Esto revisa dos alternativas que ADR 0001 D1 descartó, y hay que ser explícito
sobre por qué:**

- *«siempre worktree»* se descartó porque **paga el bootstrap incluso trabajando
  en solitario**. Esa objeción sigue en pie y por eso `always` **no** pasa a ser
  el defecto: quien trabaja solo sobre un stack pesado no paga nada nuevo.
- *«opt-in por proyecto»* se descartó porque **«no arregla nada hasta que te
  acuerdas de activarlo, que es justo el problema»**. Esa objeción era válida
  contra un opt-in que **sustituyera** a la detección: si activar el worktree
  fuese la única defensa, olvidarlo devolvía el fallo original. Aquí no
  sustituye a nada. La detección de ADR 0001 D1 sigue entera y sigue siendo el
  suelo: un proyecto que nunca declara la política sigue protegido en `CONFLICT`
  igual que hoy. Lo que el opt-in añade es la única cosa que la detección no
  puede dar por construcción —aislar cuando **todavía no hay** evidencia—, y se
  paga una vez por proyecto, no una vez por feature: `/sdd:init` hace la pregunta
  y `/sdd:doctor` dice qué política está en vigor.

*Alternativa descartada*: **derivar la política de la actividad** (p. ej. aislar
siempre si el proyecto ya tuvo dos sesiones a la vez alguna vez). Es exactamente
la heurística que ADR 0001 D2 evitó al elegir liveness por pid en vez de
adivinanzas: convierte una decisión del proyecto en un estado de máquina
inobservable, y el usuario no puede predecir qué hará el flujo mañana.

### D2 — El veredicto describe la evidencia; la política decide la acción

`check` sigue imprimiendo `CLEAR` (exit `0`) o `CONFLICT` (exit `1`) según la
evidencia, y la política **no** los mueve. La acción se emite aparte, como última
línea: `ISOLATE` o `WORK HERE`, con el campo `isolate` en el JSON.

*Por qué*: hacer que `always` imprimiera `CONFLICT` sobre un clon libre habría
sido más barato de implementar y habría convertido en mentira cada lectura
posterior del veredicto —el `check` es read-only y lo llaman `/sdd:status` y
`/sdd:doctor`, que reportan evidencia a un humano—. Un flag que degrada un
diagnóstico para forzar un comportamiento es la misma clase de error que la regla
8 prohíbe en el gate de merge: la evidencia no se fabrica.

Además `check` pasa a reportar los **hechos de base** (`base:`): rama por defecto,
si está publicada, y cuántos commits locales no están en `origin`. El
`baseRef: fresh` de `EnterWorktree` (rama desde `origin/<default>`) deja de ser un
caso raro y pasa al camino caliente de **todas** las features, así que sus dos
formas de salir mal se reportan antes en vez de descubrirse después.

### D3 — Se aísla antes de la rama y antes del primer documento

El orden en `/sdd:new` queda: claim remoto → `check` → aislar → `claim` local →
proposal. Aislar después de escribir `sdd/changes/<feature>/proposal.md` dejaría
el documento en el clon principal, que es justo el estado que la política existe
para evitar; y aislar antes del claim remoto crearía una rama local con un nombre
que quizá ya es de otro.

### D4 — Los repos degenerados tienen comportamiento decidido, no descubierto

Bajo `on-conflict` eran raros; bajo `always` los pisa cada feature. Cada caso
tiene fila en `references/isolation.md` y los hechos que la eligen salen del
propio `check`: **sin remoto** (`fresh` no resuelve nada → `git worktree add`
explícito desde la base local y `EnterWorktree` por `path`), **HEAD desacoplado**
(no es una base: confirmar con el usuario; en `/sdd:auto`, BLOCK), **ya estás en
un worktree enlazado** (no anidar: crear bajo el `.claude/worktrees/` del clon
principal, que `check` reporta como `main_worktree`) y **repositorio vacío** (no
hay base; se dice y se para).

### D5 — En Codex la política degrada a handoff manual, nunca a no-op

El adaptador de Codex no tiene `EnterWorktree`, así que nada puede cambiar el
directorio de trabajo de la sesión. Bajo `always`, la fase **crea el worktree, lo
liga con `claim --worktree <path>` y se detiene**, indicando al usuario que
ejecute la fase desde ahí; en `/sdd:auto` eso es una entrada de `BLOCKED.md` con
su comando de reanudación. Seguir en el clon principal ignorando en silencio una
política declarada es el único desenlace inaceptable.

### D6 — Una política irreconocible es un error, y el aviso de gitignore se adelanta

`SDD026` (ERROR) reporta un `isolation:` con un valor que no es ninguno de los
dos: sin él, un `alway` volvería al defecto sin decir nada y el proyecto creería
estar aislando. Y `SDD024` (gitignore de `.claude/worktrees/`) pasa a dispararse
también cuando la política es `always` **antes de que el directorio exista**:
después ya hay un checkout anidado commiteable, que es tarde. Ambos son estado de
proyecto commiteado, así que caben en los fixtures del doctor — la frontera que
ADR 0001 documentó en sus *Desviaciones* se respeta, no se debilita.

## Consecuencias

**Se gana**

- El clon principal se queda como base pristina: rama por defecto y árbol limpio,
  siempre. Deja de ser rehén de la primera feature.
- Sesiones uniformes: N sesiones arrancan del mismo mundo, que es el caso de uso
  que ADR 0001 D8 perseguía.
- La evidencia #2 y #3 dejan de ser autoinducidas; cuando aparecen, describen el
  entorno de verdad.
- El check de base local-por-delante deja de ser un paso manual y opcional: lo
  calcula `check` en cada llamada.
- Los casos degenerados están decididos por escrito en vez de improvisados por
  fase.

**Se paga**

- **El bootstrap lo paga cada feature**, incluida la primera. BD vacía, reinstalar
  dependencias, disco por worktree. Por eso se dice **una vez, al crear el
  worktree y antes de levantar nada**, y por eso el defecto no cambia.
- Un proyecto con un **recurso exclusivo** se topa con él en la primera feature en
  lugar de la segunda. Es adelantar el problema, no crearlo — pero conviene tener
  escrita la regla operativa antes de activar `always`.
- Una decisión más que `/sdd:init` tiene que plantear, con su respuesta correcta
  dependiendo del proyecto: es el precio de no imponer el coste a todo el mundo.
- Los proyectos inicializados antes de este ADR no tienen la línea, así que nunca
  se les preguntó. `/sdd:init` ofrece revisitarlo y `/sdd:doctor` dice que están
  en el defecto.

## Implementación

`scripts/sdd_session.py`: `read_isolation_policy` + `IsolationPolicy`,
`default_branch`, `base_facts`, los campos nuevos de `check`
(`policy`, `isolate`, `base`, `main_worktree`), `render_policy`/`render_base`, el
subcomando `policy` y sus tests. `scripts/sdd-doctor.py`: `SDD026` y el disparador
adelantado de `SDD024`. Documentos: `references/isolation.md` (tabla *When to
isolate*, creación, repos degenerados, límite de Codex), regla compartida 10,
`skills/new`, `skills/auto`, `skills/init` (3b), `skills/doctor`,
`templates/scaffold/project.md`, `README.md` y `docs/codex.md`.
