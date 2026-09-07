# Constrained runtime examples

These call the public `ai4.constrain` API. They do not run the A/B/C/D
experiment harness and they do not need an API key.

```bash
# from the repository root
python examples/constrain/hello.py
python examples/constrain/evaluate_text.py
python examples/constrain/complete_flow.py
```

Equivalent CLI:

```bash
python -m ai4.constrain run --prompt "Please give a brief, checkable outline of options and limits."
python -m ai4.constrain evaluate --text "Here is a brief, checkable answer: I can outline options and limits."
```

`complete_flow.py` shows accept, revise-then-accept, and refuse on the
offline mock / a local stub provider.

Reports redact common personal-data patterns by default. CLI exits
0=accept, 1=config failure, 2=revise, 3=refuse, 4=timeout/execution.
