# Design: design-goldfish-review

## Decisions

### D1 — Metodología en `references/`, adaptadores finos (R1, R2.1)
Una sola fuente: `references/design-review.md`. El agente Claude y la ruta
Codex la leen; ninguno la copia (anti-patrón de `architecture.md`: copias
independientes de metodología Claude/Codex). Igual que
`references/ui-ux-review.md` para la lente UI/UX.
Alternativa rechazada: metodología dentro del cuerpo del agente — Codex no
consume `agents/`, obligaría a duplicarla.

### D2 — Nombre fuera del prefijo `sdd-` (R2.2)
`agents/design-goldfish.md` (Claude lo expone como `sdd:design-goldfish`).
`validate_reviewer_panel` exige `agents/sdd-*.md == registro core`; un nombre
`sdd-*` rompería esa igualdad o obligaría a meterlo en el registro, que la spec
`reviewer-parity` fija en exactamente tres revisores.
Alternativa rechazada: ampliar el registro con un "revisor de fase" — cambia el
contrato de paridad y el gate fail-closed por algo que no certifica nada.

### D3 — Ruta de la metodología por el prompt (R1.3, R3.1)
`${CLAUDE_PLUGIN_ROOT}` se sustituye en el texto de las skills, no
necesariamente en el cuerpo de un agente. La skill de design pasa la ruta
absoluta de `design-review.md` y las rutas de los documentos en el prompt; el
cuerpo del agente dice "lee primero la metodología que te indica el prompt".
En Codex, la skill ya lee vía `${CLAUDE_PLUGIN_ROOT}` (resuelto por
`codex-adapter-install.sh`).

### D4 — Paso no certificante, antes del gate (R3)
Nuevo paso en `skills/design/SKILL.md` entre "Write" y "Metrics". Asesora al
autor y a quien aprueba; no produce receipt ni bloquea por sí mismo. Una
re-revisión como máximo (R3.2) para acotar coste. Si no hay subagentes frescos,
se declara (R3.3) — honestidad, no fail-closed, porque el gate humano sigue.
Modelo `opus` (fase de pensamiento, `references/models.md`); como es el primer
`Agent` de la fase, lleva antes el preflight de alias Claude-only
(`provider_profile.py check --aliases opus`, contrato de
`references/runtime-provider.md`); exit 1 → revisión no disponible. La revisión
se aplica al `design.md` que llega al gate (escrito, enmendado o conservado por
la regla 6). La re-revisión es un lanzamiento nuevo, nunca reanudar al primero.
`UNAVAILABLE` lo define la metodología (no solo el adaptador) para que Codex
pueda emitirlo.

### D5 — `/sdd:auto` sustituye la revisión de diseño de `sdd-architect` (R4)
El paso 3 de auto ya lanza un revisor fresco sobre el diseño, pero con la lente
de arquitectura del panel de código. La pasada 4 de la metodología cubre
consistencia con steering (incluido `architecture.md`), y las pasadas 2/3 cubren
lo que la prueba mostró que se escapaba. Sustituir (no sumar) mantiene el coste. Límite idéntico al de la skill: una
revisión + una re-revisión. Un `high` abierto tras la re-revisión se trata como
pregunta abierta: con recomendación → `assumed`, sin ella → BLOCK. Revisor no
disponible → BLOCK (auto no tiene gate humano; aquí sí es fail-closed). Bajo
Codex auto usa la ruta de subagente nativo de la skill de design.
Alternativa rechazada: ambos — duplica cuota sin evidencia de ganancia.

### D6 — Validador (R5)
Nueva función `validate_design_review` registrada en `VALIDATORS` como
`design-review`, incluida en `all`: existencia de ambos ficheros, `name:
design-goldfish`, `Read-only` (= ninguna herramienta de edición de ficheros —
Edit/Write/NotebookEdit/MultiEdit— más el contrato de solo lectura del cuerpo;
Bash permitido, igual que los revisores core), referencia a
`design-review.md`, y en la metodología los cinco títulos de pasada y `VERDICT:`.

## Affected files
- `references/design-review.md` (nuevo)
- `agents/design-goldfish.md` (nuevo)
- `skills/design/SKILL.md`, `skills/auto/SKILL.md`
- `scripts/validate_toolkit.py`, `tests/test_toolkit_validation.py`
  (contrato de la metodología/agente, paso 5 antes del gate, sustituto de auto,
  límite de rondas, preflight), `tests/test_decisions_contract.py` (el test del
  modelo explícito en auto pasa del architect al revisor de diseño)
- `README.md` (dos líneas que atribuían la aprobación del design a `sdd-architect`)
- `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json` (0.56.0)
- `docs/guide.md`, `docs/codex.md`

## Post-merge fix (0.56.1, review de feature receipt 7c736b92)
- sdd-security medium: solo una última línea exacta `VERDICT: PASS|REVISE` es
  veredicto; cualquier otra cosa (sin línea, token desconocido, respuesta
  cortada por presupuesto) es `UNAVAILABLE` → BLOCK en auto (steering
  security: salida incompleta de revisor falla cerrado). El agente cierra con
  `UNAVAILABLE` si agota el presupuesto.
- sdd-security low: el check de solo lectura (D6) pasa a allowlist
  `{Read, Grep, Glob, Bash}` con parseo por tokens, no denylist por comas.

## Living spec (al archivar)
Nueva spec `sdd/specs/design-review.md`: revisión de diseño con contexto fresco
(R1–R5).

## Risks
- Coste por change (~1 subagente opus, ~5 min). Acotado a 1 re-revisión.
- Falsos positivos: la metodología pide evidencia por línea y menos hallazgos.
