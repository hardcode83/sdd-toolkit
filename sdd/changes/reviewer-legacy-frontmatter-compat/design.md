# Design: reviewer-legacy-frontmatter-compat

## Context

El parser compartido de `skills/reviewer-panel/reviewer_plan.py` descubre
reviewers en `.claude/agents/sdd-review-*.md`, valida el archivo y transforma
su `name`, cuerpo, ruta, `phases` y `applies_to` en un `ReviewerDefinition`.
Actualmente rechaza cualquier otra clave del frontmatter, por lo que el
frontmatter que genera `templates/reviewer-template.md` se vuelve
`unavailable` aunque el archivo sea válido para Claude.

La spec viva `sdd/specs/reviewer-parity.md`, R1, exige que un reviewer
malformado, inseguro o no resoluble sea `unavailable` y no pueda pasar; R2
define `phases`/`applies_to` como metadata de aplicabilidad y permite ejecutar
`UNKNOWN`. El design archivado
`sdd/changes/archive/2026-08-28-codex-reviewer-parity/design.md`, en la sección
“Legacy project reviewer ambiguity”, también establece explícitamente que solo
se aceptan campos de frontmatter documentados y que las definiciones ambiguas o
inseguras quedan `unavailable` (D5 y la sección de riesgos, líneas 396–402).

La política de R4.1, por tanto, sí está respaldada por contrato existente. Este
change amplía el conjunto de campos documentados con la unión de los dos
formatos existentes; no define una política general para metadata futura ni
introduce un mecanismo extensible.

## Decisions

### D1 — Aceptar la unión explícita de los dos contratos existentes

**Chosen:** `_parse_project()` reconocerá `name`, `description`, `model`,
`tools`, `phases` y `applies_to`, rechazando duplicados y conservando las
validaciones actuales de archivo local, nombre y frontmatter. `name` seguirá
siendo obligatorio; `description`, `model`, `tools`, `phases` y `applies_to`
serán opcionales individualmente, de forma que funcionen legacy-only,
new-only y formatos mixtos.

La unión es deliberada: `description`, `model` y `tools` son los campos que
continúa generando `templates/reviewer-template.md`, mientras que
`phases`/`applies_to` son el contrato nuevo del planner. Así se corrige la
regresión concreta sin inventar defaults ni exigir migración.

Rejected: aceptar cualquier clave no vacía — reintroduciría una política
abierta no definida y ocultaría errores tipográficos o metadata no comprendida.

### D2 — Mantener separadas las declaraciones Claude de la política Codex

**Chosen:** la ruta Claude continuará consumiendo el archivo `.md` existente,
incluidos `description`, `model`, `tools`, `name` y el cuerpo, sin reescritura ni
migración. La normalización compartida usará el cuerpo como criterios del
reviewer y `phases`/`applies_to` para aplicabilidad; `model` y `tools` no se
añadirán como permisos ni como selección de modelo en `ReviewerDefinition` o
en el handoff Codex.

El prompt Codex seguirá envolviendo el cuerpo con la política toolkit-owned de
identidad, alcance, solo lectura, resultados y evidencias que ya implementa
`build_reviewer_prompt()`. Por tanto el parser acepta y no destruye la
semántica Claude, mientras Codex no interpreta declaraciones específicas de
Claude como capacidades propias.

Rejected: mapear `model`/`tools` a configuración Codex — no existe una
equivalencia segura y ampliaría el alcance hacia un contrato entre proveedores.

### D3 — Tratar la ausencia de aplicabilidad nueva como UNKNOWN runnable

**Chosen:** conservar la semántica actual de `evaluate_applicability()`: un
reviewer de proyecto sin `phases` o `applies_to` produce `UNKNOWN`, se planifica
y se ejecuta; solo un `NO MATCH` definitivo se marca `skipped`. Los campos
legacy no se usarán para inferir una aplicabilidad distinta.

Esto hace que un reviewer creado con el template histórico siga siendo
aditivo y runnable, a la vez que conserva la regla fail-safe de no omitir
cobertura por falta de información.

Rejected: tratar la ausencia de metadata nueva como exclusión — contradice R2
de `sdd/specs/reviewer-parity.md` y volvería a inutilizar reviewers legacy.

### D4 — Conservar el fail-closed y el alcance de R4.1

**Chosen:** mantener R4.1 tal como fue aprobada: entradas con frontmatter
malformado, campos duplicados o no documentados, identidad inválida, ruta
insegura, symlink, mismatch de nombre o contenido ilegible serán
`unavailable`; no serán `skipped` ni podrán producir `PASS`. La implementación
solo considerará documentados los seis nombres de D1 para este change.

La base contractual es `sdd/specs/reviewer-parity.md` R1 (malformed,
duplicate, unsafe y unresolved son unavailable) y el design archivado
`codex-reviewer-parity`, D5 y su sección “Legacy project reviewer ambiguity”
(solo campos documentados; definiciones inseguras o ambiguas son
`unavailable`). El resultado normalizado seguirá pasando por
`build_reviewer_plan()` y `evaluate_panel_gate()`, sin cambiar el gate ni la
certificación del ciclo de vida.

Rejected: convertir campos desconocidos futuros en una nueva política de
compatibilidad durante este change — quedaría fuera del problema reproducido y
requeriría diseñar un sistema general de metadata, explícitamente fuera de
scope.

### D5 — Probar la matriz de compatibilidad en el contrato existente

**Chosen:** ampliar `tests/test_reviewer_plan.py` y sus fixtures, siguiendo la
convención `unittest` del proyecto, para cubrir: legacy-only con los cuatro
campos; new-only; mezcla de ambos; body y identity preservados; ausencia de
metadata nueva como `UNKNOWN` planned; duplicados/campos fuera de la unión como
`unavailable`; y gate no aprobable. También se verificará que la generación de
prompt Codex mantenga el wrapper de contenido no confiable y no trate
`model`/`tools` como permisos.

La documentación de `templates/reviewer-template.md`, `docs/guide.md` y
`docs/codex.md` se alineará con el contrato efectivo. No se añadirá una prueba
de runtime Claude que reimplemente su invocación: la preservación se verifica
por ausencia de cambios en esa ruta y por la lectura intacta del archivo.

Rejected: probar solo que el parser no lanza una excepción — no demostraría
identidad, criterios, aplicabilidad ni el límite fail-closed.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Parser y normalización | `skills/reviewer-panel/reviewer_plan.py` | Aceptar los seis campos conocidos; conservar el cuerpo, identidad y metadata nueva; mantener la normalización segura y el wrapper Codex. |
| Tests y fixtures | `tests/test_reviewer_plan.py`, `tests/fixtures/` si se requieren fixtures compartidos | Cubrir legacy/new/mixed, campos desconocidos, metadata inválida, UNKNOWN y gate fail-closed. |
| Contrato de template y guía | `templates/reviewer-template.md`, `docs/guide.md`, `docs/codex.md` | Explicar la compatibilidad dual, la semántica Claude de `model/tools` y el uso opcional de `phases/applies_to`. |
| Living spec | `sdd/specs/reviewer-parity.md` | En archive, documentar la unión legacy+nuevo y la separación de metadata Claude/Codex; no cambiar el contrato de gate. |

No se modificarán el design archivado, los reviewers core ni los comandos de
certificación del ciclo de vida.

## Data & interfaces

No hay cambios de persistencia, schema, estado o dependencias. La interfaz
externa de los archivos de proyecto sigue siendo Markdown con frontmatter.

La interfaz lógica continúa siendo `ReviewerDefinition`; `description`,
`model` y `tools` se validan como campos aceptados del archivo y permanecen
fuera de la política de capacidades Codex. `phases` y `applies_to` siguen
normalizándose como tuplas para `evaluate_applicability()`. El cuerpo completo
continúa siendo `criteria` del reviewer de proyecto.

## Risks & mitigations

- **Regresión Claude:** una refactorización podría dejar de servir el archivo
  original al agente Claude. Mitigación: no modificar el path de dispatch Claude
  y añadir una prueba que confirme la preservación del frontmatter/body.
- **Allowlist demasiado estricta:** futuras ediciones podrían volver a romper
  metadata legítima. Mitigación: hacer explícita en documentación y tests la
  unión actual de los seis campos, sin ampliar este change a una política futura.
- **Relajación del gate:** un reviewer inválido podría convertirse en skip.
  Mitigación: mantener `lens == "unavailable"`, `UNKNOWN` runnable y
  `NO_MATCH` como único skip; cubrir cada caso en la matriz de tests.
- **Escalada de capacidades Codex:** `tools` podría interpretarse como
  autorización. Mitigación: el handoff seguirá usando solo la política
  toolkit-owned y no propagará esos valores como permisos.

## Requirement traceability

| Requirement | Design coverage | Verification |
|---|---|---|
| R1 | D1, D3 | Legacy-only, new-only, mixed y ausencia de metadata nueva. |
| R2 | D2 | Preservación del archivo Claude y prompt/handoff Codex sin reinterpretar `model/tools`. |
| R3 | D1, D3, D5 | Body, identity, scope, descubrimiento aditivo y criterios preservados. |
| R4 | D4 | Casos malformed, duplicate, unknown, unsafe, mismatch, unavailable y gate FAIL. |
| R5 | D5 | Tests deterministas y documentación alineada, sin runtime pagado obligatorio. |

## Open questions

No quedan decisiones abiertas para esta fase. La política sobre metadata futura
desconocida queda deliberadamente fuera de este change; D4 solo aplica al
conjunto explícito de seis campos actualmente documentados.
