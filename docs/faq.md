# FAQ — decisiones de diseño y preguntas reales

Respuestas a las preguntas que surgieron construyendo y usando el toolkit. La [guía](guide.md) explica *cómo* usarlo; esto explica *por qué* es así.

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

## ¿Cuándo merece la pena `/sdd:review` antes de archivar?

| Situación | ¿Review? |
|---|---|
| Run interactivo con panel completado en todas las secciones | Opcional — añade solo la vista transversal (interacciones entre secciones, scope creep). En changes grandes sí; en uno de 2 secciones, sobra |
| Panel incompleto o saltado (`solo`, límites de sesión) | **Obligatorio** — review a escala feature es el mecanismo de recuperación |
| Modo auto | Siempre (cableado): nadie humano miró durante la ejecución |
| Cambio trivial sin design | Innecesario |

El drift check (`/sdd:review` sin argumento) es otra cosa: mantenimiento periódico specs↔código, fuera del ciclo de cualquier change.

## ¿El panel se lanzó solo — quién decidió eso?

Nadie decidió nada creativo: es la regla del paso 3 de `run` — *última tarea de una sección marcada + la sección tocó código de producción → panel*. Dos criterios objetivos, cero discrecionalidad. Tournament, en cambio, **jamás** se autodispara: requiere que tú lo pidas (`tournament <tarea>`).

## ¿Qué diferencia hay entre los revisores de `agents/` y "los agentes del tournament"?

`agents/` contiene **solo revisores**: identidades persistentes, read-only, con contrato de findings. Los 3 implementadores del tournament son **efímeros** — agentes genéricos lanzados con worktree aislado y un ángulo distinto cada uno (simple-correcto / performance / defensivo); escriben código y desaparecen. En tournament, los revisores hacen de *juez* de los 3 diffs. Mnemotécnica: `agents/` = quien verifica; tournament = quien compite.

## ¿Cómo llegan las actualizaciones del plugin a quien lo usa?

Si el marketplace se registró **desde git** (`/plugin marketplace add hardcode83/sdd-toolkit`): pull en background automático, y el campo `version` de `plugin.json` marca cuándo hay release (subir el número = distribuir). Solo distribuye lo que está en **`main`** — una PR sin mergear no le llega a nadie. Registrado por **ruta local**: siempre manual (`/plugin marketplace update` + `/plugin update`). Y el plugin se instala **por usuario**, no por repo: lo que el proyecto versiona (`enabledPlugins` en settings) es la *declaración* de que lo usa.

## ¿Dónde queda lo que se interrumpe a medias (un panel cortado, una duda, una tarea aparcada)?

En la **cola de pendientes** del change: `sdd/changes/<feature>/BLOCKED.md`. Regla compartida nº 5: ninguna fase puede terminar dejando deuda solo en la conversación — la persiste con tipo (`decision`: te toca a ti / `deferred`: reanudable, con su comando exacto). `/sdd:status` la muestra como bandeja de entrada; `/sdd:archive` se niega a cerrar con entradas vivas (salvo override explícito). Un panel interrumpido se reanuda como `/sdd:review <feature>` — cubre lo pendiente y las interacciones.

## ¿Por qué los modelos por fase son del plugin y no por proyecto?

Porque el plugin se instala una vez por usuario y las skills se comparten: editar frontmatter afectaría a todos los proyectos igualmente — así que se asume y se documenta (editar `skills/<fase>/SKILL.md` o `agents/*.md`, commit, subir versión). El perfil por-proyecto existió en la era pre-plugin y se sacrificó a cambio de distribución centralizada. Las **reglas** sí son por proyecto (steering) — y son el mando de calibración que de verdad importa.

## ¿Por qué el roadmap no se convierte en proposals desde el día uno?

Porque el proposal de la feature 5 escrito el día uno estaría anclado a lo que el plan *imaginaba*; escrito cuando le toca, se ancla a las **specs reales** de las features 1-4. El roadmap es una línea por feature (barato de mantener y reordenar); el proposal es caro y caduca. Just-in-time no es pereza — es precisión.

## ¿En equipo, quién tiene qué feature? ¿Y si dos personas cogen la misma?

El candado es la **rama remota `sdd/<feature>`**: `/sdd:new` comprueba si existe (y avisa con el dueño), y ofrece pushear tu claim antes de escribir; auto lo publica *antes* de trabajar. `/sdd:status` enseña las ramas de otros como "en curso por otros". Los conflictos de merge restantes son señal, no ruido: dos features tocando la misma `specs/<capability>.md` tenían que coordinarse igualmente.
