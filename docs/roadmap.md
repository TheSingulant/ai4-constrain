# Roadmap

v0.1 is an offline evaluator and experiment harness plus the public
`ai4.constrain` product wrapper (frozen condition D, not a claim D beat
C; Stage 2D remains `null_retained_D_adds_cost`). `ConstrainedSession`
holds that path across turns. See
`docs/constrain-session.md`. Evaluator **implementation** interchange
is allowed only behind the frozen v0.1 scoring/control contract
(Option A). There is no live/LLM judge and no second production
evaluator. Evaluator implementation interchange does not demonstrate
alignment persistence or correctness across judges.

`ai4.identity` is a sibling offline identity/provenance kernel
(`docs/identity.md`). It is not on the governing constrain path.
Identity is not trust. `.ai4` resolution is a discovery adapter
(`docs/identity-resolution.md`), not kernel verification and not
constraint-policy authority.


Production Telegram work stays off this path. See `docs/protocol-v0.1.md`.
