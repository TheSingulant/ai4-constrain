# Security

## Reporting

Report suspected vulnerabilities in this public library privately by email to support@thesingulant.ai. Please allow reasonable time to investigate and fix an issue before any public disclosure (responsible, coordinated disclosure).

Do not file public issues that include credentials, tokens, private keys, or production host details.

## Scope

In scope: the public `ai4-constrain` Python package, examples, and CI as published on GitHub.

Out of scope for public disclosure write-ups: third-party model provider outages; social-engineering against non-repo systems; and any private infrastructure not shipped in this repository.

## Handling secrets

- Never commit API keys, PEM private keys, or bot tokens.
- `FileSessionStore` is local trusted storage, not a vault.
- Optional `GoverningIntegration` credential fields are caller-supplied at runtime; this repo must not contain live values.

## Secret scan

```bash
python3 scripts/secret_scan.py
```

The scan fails closed on high-risk credential shapes and selected internal-marker patterns.
