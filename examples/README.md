# Examples

Product runtime (clone-and-run, no experiment harness):

```bash
python examples/constrain/hello.py
python examples/constrain/session_demo.py
python -m ai4.constrain run --prompt "Please give a brief, checkable outline of options and limits."
python -m ai4.constrain session demo
```

See `examples/constrain/README.md`.

Experiment harness (A/B/C/D pilot):

```bash
python -m src.main experiment --condition all
```

`run_offline_pilot.py` is a thin wrapper around that command.
