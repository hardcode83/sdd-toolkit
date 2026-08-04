# SDD — Spec-Driven Development

Este directorio es la **capa de persistencia** del proyecto para el flujo SDD (plugin [`sdd-toolkit`](https://github.com/hardcode83/sdd-toolkit) de Claude Code): specs, cambios en curso, reglas y roadmap viven en archivos, no en la sesión.

**¿Nuevo en el flujo?** Empieza por la [guía de uso paso a paso](https://github.com/hardcode83/sdd-toolkit/blob/main/docs/guide.md); la referencia completa está en el [README del plugin](https://github.com/hardcode83/sdd-toolkit#readme). Para tener los comandos `/sdd:*` en tu Claude Code:

```
/plugin marketplace add hardcode83/sdd-toolkit
/plugin install sdd@sdd-toolkit
```

Convenciones para humanos y agentes:

- `project.md` — steering core: stack, comandos de build/test/lint, convenciones. Generado por `/sdd:init`, editable a mano. Se lee al inicio de toda fase SDD.
- Los comandos de validación son los de este proyecto, no los tests o scripts internos del plugin. Si el stack aún no está definido, déjalo pendiente en `project.md` hasta descubrirlo o decidirlo.
- `steering/` — reglas permanentes ricas: `product.md` (visión), `architecture.md`, `security.md`, `testing.md`, `documentation.md`, docs por componente/lenguaje. Cada doc declara en su frontmatter (`applies_to`, `phases`) cuándo se carga — las fases SDD solo leen los que aplican al cambio en curso.
- `specs/` — **verdad viva**: qué hace el sistema hoy. Una capability por archivo, en presente, con requisitos EARS. Solo se actualiza al archivar un cambio completado (`/sdd:archive`). En proyectos que adoptaron SDD con código existente, la cobertura crece por "spec on first touch".
- `changes/` — cambios en curso. Cada carpeta es un cambio con `proposal.md` (por qué + requisitos), `design.md` (opcional, decisiones técnicas), `tasks.md` (checklist), `STATE.md` (lifecycle/PR/merge) y `metrics.md` (uso, si está activado). `BLOCKED.md` sigue siendo la cola lateral de bloqueos.
- `changes/archive/` — cambios completados, con prefijo de fecha.
- `roadmap.md` — (opcional) **índice** de futuros changes: una línea por entrada, agrupada en `## Stage N — <resultado>`, con una sub-línea de metadatos que declara sus dependencias (`needs`, `completes`, `informs-from`, `inherits-from`) y su clasificación (`size`, `kind`). Editable a mano. El orden lo decide el grafo, no la posición en el fichero: `/sdd:new` coge la siguiente entrada **de la frontera** (las que tienen todas sus dependencias cerradas) y la convierte en proposal just-in-time. Ninguna fase anota el roadmap durante el ciclo — el progreso se deriva de `STATE.md`; solo `/sdd:archive` lo tickea, tras el merge.
- `roadmap/<feature>.md` — (opcional) el análisis largo de una entrada. El índice se mantiene corto porque lo leen todas las fases; esta nota solo la lee el `/sdd:new` de esa entrada.
- `metrics.md` — (opcional) resumen de tokens/coste por feature archivada.

Flujo: `/sdd:new` → `/sdd:design` (opcional si trivial) → `/sdd:tasks` → `/sdd:run` → `/sdd:review` → PR → merge → `/sdd:archive`, con `/sdd:status` y `/sdd:doctor` como apoyo. Specs vivas y roadmap solo se finalizan al archivar después de comprobar el merge. `doctor` valida el estado de forma determinista y read-only. Cada fase requiere aprobación humana antes de la siguiente.

`/sdd:status` no lista el roadmap tal cual: enseña la **frontera** (qué se puede atacar ya, en paralelo), las olas de dependencias, el camino crítico de cada stage y el grafo.

**Varias features a la vez**: una feature = una rama = un directorio de trabajo. Si abres una segunda sesión sobre este clon, el flujo lo detecta y te ofrece aislar la feature en un git worktree (`.claude/worktrees/`, ignorado). Sin eso comparten HEAD y la segunda se lleva los ficheros sin commitear de la primera. Si tu proyecto necesita algo que git no versiona (`.env`, `node_modules`, una BD local) para que sus tests pasen, decláralo en la sección **Worktree bootstrap** de `project.md` — sin eso, la verificación falla dentro de un worktree y el fallo parece un bug.
