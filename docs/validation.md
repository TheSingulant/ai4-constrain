# Validation (public methodology)

This note describes **how** the v0.7 constrained-authority engineering milestone was validated at a methodology level. It does not publish operational topology, cloud account identifiers, IAM inventories, authority resource names, or internal unresolved-decision identifiers.

## What was validated

- **Authority-gate behavior** under an isolated live validation track for the external monotonic-authority engineering milestone associated with v0.7.
- Independent review artifacts were produced internally; public claims here are limited to: the milestone was reviewed, blockers for that validation track were cleared, and the result supports describing constrained-authority gate behavior as validated in that isolated setting.

## Method (abstract)

1. Define fail-closed expected outcomes for gate allow / deny / mismatch classes.
2. Exercise the gate against isolated fixtures and live probes under a spending and scope cap owned by the operator.
3. Record structured results; require independent adversarial review before treating the track as complete.
4. Keep product runtime claims separate from infrastructure topology: the public Python package does not embed the live gate service.

## What this does **not** claim

- Production safety certification or formal verification.
- That Stage 2D proved condition D superior to C (`null_retained_D_adds_cost` remains).
- That dedicated-context lifecycle / expanded authority-control work is complete (next phase only).
- Any guarantee about third-party model providers.

## Relation to the public package

Public `ai4.constrain` **0.7.0** exports the developer runtime and optional hybrid integration surface. External authority infrastructure remains outside this repository. See [`ROADMAP.md`](../ROADMAP.md).
