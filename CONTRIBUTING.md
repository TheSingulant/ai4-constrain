# Contributing

## Setup

```bash
python3 -m pip install -e ".[dev]"
```

Python **3.10+** required.

## Tests

```bash
python3 -m pytest
python3 scripts/secret_scan.py
```

Offline tests must pass without API keys. Do not commit credentials, `.env` files with secrets, deployment manifests, or private validation artifacts.

## Pull requests

1. Branch from `main`.
2. Keep changes scoped (runtime vs docs vs CI).
3. Update `CHANGELOG.md` for user-visible API changes.
4. Ensure `tests/test_frozen_byte_identity.py` is updated when intentionally changing locked product bytes.
5. Do not add AWS account material, host wiring, or bot tokens.

## Code of conduct (minimal)

Be precise. Prefer fail-closed behavior. Do not overclaim safety, alignment, or formal verification.
