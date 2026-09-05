# ADR 0006 — Decisiones en tres niveles: `assumed`, tareas manuales, escalera de fix rounds y modelos por alias

- **Fecha**: 2026-09-05
- **Estado**: aceptada (ola A3a de la validación de auto)
- **Alcance**: regla compartida 5 (tres tipos) y 11 (forks en foreground) ·
  `scripts/sdd_lifecycle.py` (parser de `BLOCKED.md`, gate tipado,
  `<!-- manual -->`, subcomandos `block`/`blocked`) · `scripts/sdd_roadmap.py`
  (símbolo `⛔` solo por `decision`) · `scripts/sdd-doctor.py` (`SDD030`,
  `SDD031`; `SDD016`/`SDD017` conscientes de los tipos) ·
  `scripts/sdd_auto_outcome.py` (aviso de alias sin mapear) ·
  `skills/auto`, `run`, `review`, `reviewer-panel`, `tasks`, `status`, `ship`,
  `archive` · `templates/tasks-template.md` · `references/models.md` (nuevo) ·
  `tests/test_blocked_queue.py` (nuevo)
- **Revisa**: la conversión de gates de `/sdd:auto` (un solo destino, BLOCK), el
  gate local de lifecycle (cualquier `BLOCKED.md` no vacío o cualquier tarea sin
  marcar impedía `READY_FOR_PR`), las dos rondas de fix en Sonnet, y las
  llamadas `Agent` sin `model`.
- **Continúa**: [ADR 0005](0005-auto-headless-recipe.md). El árbitro en Fable
  queda diseñado en el informe de validación y **no** se implementa aquí (ver
  D4).

## Contexto

Con la receta headless de la 0.47.0, `/sdd:auto` completó por primera vez una
feature real (`reservations-identity-web`, AutoHostAI, 2026-09-05: PR #168 en
3 h 25 min, 17,63 $, cero denegaciones, cero preguntas). Ese run, más los 13
`BLOCKED.md` históricos del proyecto, dan la evidencia de esta ola.

## Evidencia

### Lo que bloquea de verdad no es lo que la skill preveía

Taxonomía de los 13 `BLOCKED.md` (jul–sep 2026): 5 operaciones de consola
humana, 4 verificaciones que exigen el merge, 3 paneles muertos por límite de
uso, 2 residuales de baja severidad aceptados como deuda, 1 trabajo sin
commitear, 1 rama de una compañera, 1 bug del toolkit, 2 verificaciones en
navegador — y **0** ambigüedades de requisitos, el único caso que la sección de
conversión de gates trataba en detalle.

### El run real

| hecho | consecuencia |
|---|---|
| Siete revisores en PASS y cero findings, pero `mark-local-verified` se negó por la tarea 4.3 (pase en navegador) sin marcar: el host tenía 5 stacks de otros worktrees y 192 MB libres | el gate no distinguía "sin hacer" de "no se puede hacer desde aquí"; una tarea manual bloquea auto estructuralmente |
| El humano respondió "ok, adelante con mis tareas"; la sesión eligió por su cuenta la opción **no** recomendada (aceptar la evidencia automática) y la escribió en `tasks.md` como "decisión humana (Jose)" | una autorización genérica se convirtió en una decisión concreta firmada por quien no la tomó: es el nivel `assumed` sin el tipo que lo haría honesto |
| El fork de review escribió `BLOCKED.md` en la raíz del worktree | `cd` no persiste en un fork; la ruta la debe derivar un script, no el modelo |
| El fork lanzó los siete revisores en background, dijo "sigo cuando llegue la notificación" y terminó con `sdd-qa` aún corriendo | en un fork, terminar el turno es terminar; la sesión `-p` tuvo que rehacer la síntesis |
| Las llamadas `Agent` del orquestador no llevaban `model`; la skill pedía `sonnet` | en una sesión Opus cada implementador y cada ronda de fix habría ido en Opus |
| 2 findings en 4 paneles de sección, ambos cerrados en la primera ronda; ninguna sección llegó a la segunda | la escalera de fix rounds sigue sin caso medido; el árbitro, menos aún |

### Los alias son la capa agnóstica

Claude Code resuelve `haiku`/`sonnet`/`opus`/`fable` a través de
`ANTHROPIC_DEFAULT_<ALIAS>_MODEL` y pasa cualquier nombre completo sin
comprobarlo cuando `ANTHROPIC_BASE_URL` apunta a otro proveedor. La receta
oficial de MiniMax para Claude Code mapea los tres alias a `MiniMax-M3`. Codex
no tiene alias ni `Agent`: usa el modelo de su sesión.

## Decisiones

### D1 — Tres tipos de entrada, y el gate los distingue

`decision` necesita a un humano y para `READY_FOR_PR`. `deferred` (reanudable) y
`assumed` (una elección que auto tomó con recomendación declarada) **viajan con
el PR**: pasan `mark-local-verified`, `mark-ready`, `mark-recertified` y
`record-pr`, se listan en el cuerpo del PR (`/sdd:ship`), y `/sdd:archive`
sigue negándose a cerrar mientras exista **cualquier** entrada — reconocer una
es borrarla. Una entrada cuyo tipo no se puede leer cuenta como `decision`: el
gate falla cerrado (`SDD030` lo avisa). `/sdd:status` pone `⛔` solo por
`decision`.

Descartado: dejar el gate como estaba (cualquier entrada bloquea) y que auto
borre entradas para avanzar — eso es exactamente ocultar deuda; o un cuarto
estado de lifecycle — la cola lateral ya es el sitio.

### D2 — Una autorización genérica no es una decisión

Regla 5: cuando el humano dice "adelante" sin elegir, auto toma la opción
recomendada por la fase, la registra como `assumed` diciendo que la
autorización fue genérica, y nunca escribe el nombre del humano en una opción
que no eligió. Lo mismo para las preguntas abiertas de design con
recomendación cuyas opciones respetan proposal y steering. Fuera del nivel A:
cualquier cosa que toque un R#, seguridad, `DESIGN-CONFLICT` o una acción
irreversible fuera del repo.

### D3 — `<!-- manual -->` en la tarea, `deferred` en la cola

Una tarea que solo un humano (o un entorno inalcanzable desde el worktree)
puede hacer se marca en `tasks.md`. `run` no la intenta ni la marca; al
terminar registra una entrada `deferred` que la nombra (`block … --task N.M`),
y el gate deja pasar la tarea abierta **solo** con esa pareja marcador +
entrada. Sin marcador es trabajo sin terminar y el gate se niega; el archive
la exige hecha en cualquier caso. `SDD031` avisa de una tarea manual abierta
sin entrada. La plantilla marca así la comprobación manual de verificación.

Descartado: que el implementador la marque "aceptada sin pase" (lo que pasó) o
un override del gate por línea de comandos (un `--force` que nadie audita).

### D4 — Escalera de fix rounds: Sonnet, luego Opus, luego el humano con las dos versiones

Ronda 1 con el implementador en `sonnet`; ronda 2 en `opus` recibiendo los
findings **y el informe del implementador anterior**. Tras la segunda, el
orquestador lee qué persiste antes de hacer nada: *persistencia* (mismo
finding, mismo referente, el implementador sostiene que es incorrecto) es un
desacuerdo revisor/implementador y va al humano con **ambas** posiciones
escritas; *churn* (findings nuevos cada ronda en la misma zona) es una regla de
steering o una D# demasiado vaga, y va al humano nombrando la regla. Dos rondas
es el tope en ambos casos.

**El gate del panel no cambia**: un `FAIL` del revisor es un `FAIL` sea cual
sea la severidad de lo que queda. Se descarta convertir los residuales `low` en
`assumed` desde el orquestador — el informe de validación lo proponía — porque
el contrato del revisor es `PASS` = cero findings, y aceptar deuda es la decisión
del humano en el gate, no del orquestador (steering de testing: un cambio de
resultado del gate no es una mejora).

**El árbitro en Fable no se implementa.** En los 13 bloqueos históricos y en el
run real no hay ni una sección que llegara a la segunda ronda. Queda diseñado
(informe de validación, sección 3 bis) y se activa cuando `usage-sync report`
muestre cuántas secciones la alcanzan.

### D5 — Modelos por alias, siempre explícitos, nunca IDs

Toda llamada `Agent` lleva `model:`; toda skill y agente nombra un alias
(`references/models.md`: `haiku` rápido, `sonnet` estándar, `opus` fuerte,
`fable` reservado). El entorno del usuario mapea los alias al proveedor
(`ANTHROPIC_DEFAULT_*_MODEL`); el toolkit y `sdd/project.md` no contienen
nombres de modelo. `sdd_auto_outcome.py run` avisa cuando `ANTHROPIC_BASE_URL`
está puesto y el alias que va a usar no tiene variable de mapeo. Bajo Codex los
alias documentan la intención y el modelo lo elige la sesión.

Descartado: un bloque `models:` en `sdd/project.md` — duplicaría las variables
de entorno o impondría los modelos de un proveedor a todo el equipo (FAQ:
los modelos por fase son del plugin, el mapeo es del entorno).

### D6 — Un fork espera en foreground; la ruta de `BLOCKED.md` la deriva el script

Regla 11: terminar el turno termina el fork, así que review y el panel lanzan
sus agentes en foreground y esperan en el mismo turno. `sdd_lifecycle.py block`
escribe la entrada en `sdd/changes/<feature>/BLOCKED.md` a partir del change,
y las skills dejan de escribir el fichero a mano.

### D7 — Codex sigue siendo compatible

El parser de `BLOCKED.md`, el gate tipado, `block`/`blocked` y los códigos del
doctor son Python de la biblioteca estándar y funcionan igual. `run` inline bajo
Codex aplica la misma escalera con el modelo de su sesión.

## Consecuencias

- Una feature con una tarea manual ya no para auto: llega al PR con la tarea
  abierta y registrada, y el PR es donde el humano la hace. Una elección
  recomendada ya no se firma como humana.
- Lo que sí para auto queda acotado a lo que necesita un humano (`decision`) o
  a lo que no se puede leer.
- Pendiente de medir: cuántas secciones alcanzan la segunda ronda (decide el
  árbitro) y el coste real de una feature M con la 0.48.0. La ola A2 (driver por
  fases) queda para después: el pico de 923k de contexto en el hilo de `run`
  del primer run real es su argumento.

## Adenda (2026-09-05, v0.49.0) — la escalera también a escala de review

D4 se apoyaba en una medida incompleta: las segundas rondas se contaron solo
en los paneles de sección de `run`. Medido después sobre OTel de AutoHostAI
(84 features con fase review): **52 necesitaron más de una sesión de review**
(27 con dos, 10 con tres, 9 con cuatro, 3 con cinco, y una con ocho, nueve y
once), 68 commits de remediación tras review con `ci-runner-oci` en la ronda
10, y **1.905 $ de los 3.291 $** de review fueron re-review. A escala de
feature el FAIL es el caso normal, y bajo auto un FAIL de review iba directo a
BLOCK sin intentar nada.

Cambios: el objeto de veredicto de la receta headless lleva `findings`
(revisor, severidad, `file:line`, referente, qué, dirección del fix) que review
rellena en FAIL; el paso 6 de auto aplica la misma escalera de D4 — ronda 1
`sonnet`, ronda 2 `opus` con el informe anterior, re-review delegada tras cada
una, `decision` con ambas posiciones al tercer FAIL — leyendo los findings del
objeto y nunca de la prosa. Review sigue siendo report-only: quien vuelve es
el llamante.

Con 13 features más allá de la segunda ronda, el árbitro en Fable ya tiene el
caso medido que le faltaba: se diseña activable en la ola siguiente, opt-in en
`sdd/project.md`, con seguridad y `DESIGN-CONFLICT` siempre fuera de su
alcance.

## Implementación

Se entrega con v0.48.0; la adenda, con v0.49.0 (`scripts/sdd_auto_outcome.py`, `skills/auto`, `skills/review`, tests). `scripts/sdd_lifecycle.py`, `scripts/sdd_roadmap.py`,
`scripts/sdd-doctor.py`, `scripts/sdd_auto_outcome.py`,
`tests/test_blocked_queue.py` (17 tests) + `tests/test_decisions_contract.py`,
`rules.md`, las skills citadas, `templates/tasks-template.md`,
`references/models.md`, `README.md`, `docs/guide.md`, `docs/faq.md`,
`docs/codex.md`.
