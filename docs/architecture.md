# Architecture

v0.1 research modules are described in `docs/protocol-v0.1.md`.

The callable product wrapper is `ai4.constrain` (`docs/constrain-runtime.md`).
It productizes frozen condition D. Stage 2D did not establish D as superior
to C; the frozen evidence class remains `null_retained_D_adds_cost`.
It does not replace the experiment harness.

`ConstrainedSession` (`docs/constrain-session.md`) holds that wrapper
across turns as persistent constrained state. It is not
production `@AI4DemoBot` and it is not an HTTP service.

Evaluator implementations may be substituted behind the frozen v0.1
contract. They do not define policy. Evaluator implementation
interchange does not demonstrate alignment persistence or correctness
across judges.

`ai4.identity` (`docs/identity.md`) is a sibling offline identity and
provenance kernel. It is not imported by `run` / `evaluate` / session
walls. A signed AI⁴ identity record binds claims and provenance to an
agent identity; it does not prove the agent is aligned, safe, or
correctly governed. Identity is not trust.

This scaffold file is not an active design spec and does not describe production `@AI4DemoBot`.
