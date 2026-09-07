#!/usr/bin/env python3
"""Fail closed if high-risk secret material is committed.

Synthetic fixture PII used by frozen privacy tests (for example the
well-known invalid SSN 078-05-1120) is not a credential and is ignored.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIP_DIRS = {
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "dist",
    "build",
    "__pycache__",
    ".eggs",
    "outputs",
    ".ai4-sessions",
}

SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pyc",
    ".so",
    ".whl",
    ".zip",
}

# High-risk credential shapes. Not a general PII detector.
PATTERNS = (
    ("pem_private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws_secret_access_key", re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*\S{20,}")),
    ("telegram_bot_token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")),
    ("openai_sk", re.compile(r"\bsk-(?:live|proj)-[A-Za-z0-9]{16,}\b")),
    ("generic_bearer", re.compile(r"(?i)authorization:\s*bearer\s+[A-Za-z0-9._\-]{24,}")),
    ("vultr_api_key", re.compile(r"(?i)vultr[_-]?api[_-]?key\s*[:=]\s*\S{16,}")),
)

ALLOW_SUBSTRINGS = (
    "078-05-1120",  # documented synthetic SSN in tests/fixtures
    "AI4_API_KEY=...",
    "AI4_API_KEY=",
)


def _allowed(line: str) -> bool:
    collapsed = line.strip()
    return any(item in collapsed for item in ALLOW_SUBSTRINGS)


def scan(root: Path) -> list[str]:
    hits: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(root).as_posix()
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _allowed(line):
                continue
            for name, pattern in PATTERNS:
                if pattern.search(line):
                    hits.append(f"{rel}:{lineno}: {name}")
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan the tree for committed secrets.")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    hits = scan(args.root)
    if hits:
        sys.stderr.write("secret-scan FAIL\n")
        for hit in hits:
            sys.stderr.write(f"  {hit}\n")
        return 1
    sys.stdout.write("secret-scan OK\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
