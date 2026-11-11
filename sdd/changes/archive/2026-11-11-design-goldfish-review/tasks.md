# Tasks: design-goldfish-review

## 1. Metodología y agente
- [x] 1.1 `references/design-review.md` con las cinco pasadas, formato y veredicto (R1.1–R1.3)
- [x] 1.2 `agents/design-goldfish.md` de solo lectura que remite a la metodología (R2.1, R2.2)

## 2. Integración en skills
- [x] 2.1 Paso de revisión en `skills/design/SKILL.md` (R3.1–R3.3)
- [x] 2.2 Sustituto de aprobación en `skills/auto/SKILL.md` paso 3 (R4.1)

## 3. Validación y release
- [x] 3.1 `validate_design_review` + tests (R5.1)
- [x] 3.2 Bump 0.56.0 (PR #75) → 0.56.1 (arreglos post-merge) en ambos manifests (R5.2); docs guide/codex
- [x] 3.3 `python3 scripts/validate_toolkit.py all` y la suite unittest en verde
