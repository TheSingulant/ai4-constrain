"""Product-report redaction. This is not evaluation and does not change scores.

Default product reports redact common personal-data patterns in caller-
visible strings (prompt, drafts, evidence, feedback, output). Coverage
includes SSN-like numbers, emails, phone numbers, address-like PII that
the frozen privacy rubric already recognizes (``lives at`` / ``home
address is`` plus following address material), and actual password
assignments. Benign prose such as “a password is required” is not treated
as a secret.

Address spans use an explicit street / unit / city-state-ZIP grammar.
Abbreviation periods, quotes, parentheses, and newline continuations can
keep the span open. A completed street that is not followed by unit or
city-state-ZIP is a sentence boundary, even if the next word is
capitalized or ALL CAPS.

Password assignment is parsed as ``password[ is]?[:=] <value>`` or
``password is <value>``. A single assigned value is a credential.
A multi-word complement in the same clause is predicate prose.

Filtering provider metadata keys is not a substitute for this.

Pass ``redact=False`` only for trusted local analysis. The CLI defaults
to redaction; ``--no-redact`` writes raw content.
"""

from __future__ import annotations

import re

_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE = re.compile(r"\b\d{3}[-.]\d{3}[-.]\d{4}\b")

_ADDRESS_TRIGGER = re.compile(
    r"(?i)\b(?P<trigger>lives\s+at|home\s+address\s+is)\b(?P<sep>\s*[:=\-]?\s*)"
)
_PO_BOX = re.compile(r"(?i)P\.?\s*O\.?\s*Box\s+\w+")
_TOKEN = re.compile(
    r"(?P<ws>\s+)"
    r"|(?P<zip>\d{5}(?:-\d{4})?)"
    r"|(?P<num>\d+[A-Za-z]?(?:-[A-Za-z0-9]+)?)"
    r"|(?P<word>[A-Za-z][A-Za-z'-]*\.?)"
    r"|(?P<hash>#)"
    r"|(?P<comma>,)"
    r"|(?P<other>.)"
)
_PASSWORD_LEAD = re.compile(r"(?i)\bpassword(?:\s+is)?\s*[:=]\s*|\bpassword\s+is\s+")

_STREET_SUFFIXES = frozenset(
    {
        "street",
        "st",
        "avenue",
        "ave",
        "av",
        "road",
        "rd",
        "boulevard",
        "blvd",
        "drive",
        "dr",
        "lane",
        "ln",
        "court",
        "ct",
        "place",
        "pl",
        "circle",
        "cir",
        "highway",
        "hwy",
        "terrace",
        "ter",
        "parkway",
        "pkwy",
        "way",
        "trail",
        "trl",
        "alley",
        "aly",
        "pike",
    }
)
_UNIT_WORDS = frozenset(
    {
        "apt",
        "apartment",
        "suite",
        "ste",
        "unit",
        "fl",
        "floor",
        "rm",
        "room",
        "bldg",
        "building",
        "box",
    }
)
_DIRECTIONAL = frozenset(
    {
        "n",
        "s",
        "e",
        "w",
        "ne",
        "nw",
        "se",
        "sw",
        "north",
        "south",
        "east",
        "west",
    }
)
_STATE_ABBR = frozenset(
    {
        "al",
        "ak",
        "az",
        "ar",
        "ca",
        "co",
        "ct",
        "dc",
        "de",
        "fl",
        "ga",
        "hi",
        "ia",
        "id",
        "il",
        "in",
        "ks",
        "ky",
        "la",
        "ma",
        "md",
        "me",
        "mi",
        "mn",
        "mo",
        "ms",
        "mt",
        "nc",
        "nd",
        "ne",
        "nh",
        "nj",
        "nm",
        "nv",
        "ny",
        "oh",
        "ok",
        "or",
        "pa",
        "ri",
        "sc",
        "sd",
        "tn",
        "tx",
        "ut",
        "va",
        "vt",
        "wa",
        "wi",
        "wv",
        "wy",
    }
)
# End-of-clause predicative adjectives that describe password *state*,
# not an assigned value. Multi-word complements are handled separately.
_PASSWORD_PROPERTY_PREDICATES = frozenset(
    {
        "safe",
        "required",
        "needed",
        "necessary",
        "optional",
        "valid",
        "invalid",
        "correct",
        "incorrect",
        "weak",
        "strong",
        "short",
        "long",
        "missing",
        "empty",
        "blank",
        "expired",
        "enabled",
        "disabled",
        "hashed",
        "stored",
        "saved",
        "set",
        "unset",
        "known",
        "unknown",
        "protected",
        "visible",
        "hidden",
        "accepted",
        "rejected",
        "confirmed",
        "verified",
    }
)

REDACTION_POLICY = (
    "Default product DecisionReports redact SSN-like numbers, email "
    "addresses, phone numbers, address-like PII recognized by the frozen "
    "privacy rubric (lives at / home address is plus a street / unit / "
    "city-state-ZIP span), and actual password assignments. Address "
    "punctuation and newline continuation stay inside the span; a "
    "completed street not followed by unit or city-state-ZIP is a "
    "sentence boundary. Password assignment is parsed from clause "
    "context: a single assigned value is a credential, a multi-word "
    "complement is predicate prose. Scores and verdicts are not altered."
)


def _norm_word(token: str) -> str:
    return token.rstrip(".").lower()


def _is_street_suffix(token: str) -> bool:
    return _norm_word(token) in _STREET_SUFFIXES


def _is_unit(token: str) -> bool:
    return _norm_word(token) in _UNIT_WORDS


def _is_directional(token: str) -> bool:
    return _norm_word(token) in _DIRECTIONAL


def _is_state(token: str) -> bool:
    word = token.rstrip(".")
    if len(word) != 2 or not word.isalpha() or word.lower() not in _STATE_ABBR:
        return False
    return True


def _skip_space(text: str, index: int, *, newlines: bool = False) -> int:
    while index < len(text):
        char = text[index]
        if char in " \t":
            index += 1
        elif newlines and char in "\r\n":
            index += 1
        else:
            break
    return index


def _city_state_zip_end(text: str, pos: int) -> int | None:
    """Match City[, ] ST ZIP. Does not match an unrelated next sentence."""
    index = _skip_space(text, pos, newlines=True)
    if index >= len(text):
        return None
    city_words = 0
    while index < len(text):
        token = _TOKEN.match(text, index)
        if token is None:
            return None
        kind = token.lastgroup
        raw = token.group(0)
        if kind == "ws":
            if "\n" in raw or "\r" in raw:
                return None
            index = token.end()
            continue
        if kind == "comma":
            if city_words < 1:
                return None
            index = token.end()
            continue
        if kind == "word":
            if city_words >= 1 and _is_state(raw):
                after = _skip_space(text, token.end())
                zip_tok = _TOKEN.match(text, after)
                if zip_tok is not None and zip_tok.lastgroup == "zip":
                    return zip_tok.end()
                return None
            city_words += 1
            index = token.end()
            continue
        return None
    return None


def _unit_body_end(text: str, pos: int) -> int | None:
    index = _skip_space(text, pos)
    if index >= len(text):
        return None
    if text[index] == "#":
        index += 1
    token = _TOKEN.match(text, index)
    has_unit_word = False
    has_number = False
    if token is not None and token.lastgroup == "word" and _is_unit(token.group(0)):
        has_unit_word = True
        index = token.end()
        index = _skip_space(text, index)
    if index < len(text) and text[index] == "#":
        index += 1
    number = _TOKEN.match(text, index)
    if number is not None and number.lastgroup in {"num", "zip"}:
        has_number = True
        index = number.end()
    if not has_unit_word and not has_number:
        return None
    return index


def _unit_end(text: str, pos: int) -> int | None:
    index = _skip_space(text, pos)
    if index >= len(text):
        return None
    if text[index] == "(":
        inner = _unit_body_end(text, index + 1)
        if inner is None:
            return None
        inner = _skip_space(text, inner)
        if inner < len(text) and text[inner] == ")":
            return inner + 1
        return None
    return _unit_body_end(text, index)


def _extend_address_tail(text: str, index: int, last_good: int) -> int:
    """After a street suffix or PO box, accept only unit / city-state-ZIP."""
    while True:
        unit = _unit_end(text, index)
        if unit is not None:
            last_good = unit
            index = unit
            continue
        city = _city_state_zip_end(text, index)
        if city is not None:
            return city
        comma_at = _skip_space(text, index)
        if comma_at < len(text) and text[comma_at] == ",":
            after_comma = comma_at + 1
            unit = _unit_end(text, after_comma)
            if unit is not None:
                last_good = unit
                index = unit
                continue
            city = _city_state_zip_end(text, after_comma)
            if city is not None:
                return city
            return last_good
        return last_good


def _unwrapped_address_end(text: str, start: int) -> int:
    """Consume a street locator plus optional unit and city-state-ZIP.

    Sentence termination is a completed street that is *not* followed by
    a unit or a city-state-ZIP pattern. Capitalization of the next word
    is not enough to keep the span open.
    """
    if start >= len(text):
        return start
    box = _PO_BOX.match(text, start)
    if box:
        return _extend_address_tail(text, box.end(), box.end())

    index = start
    seen_locator = False
    last_good = start
    while index < len(text):
        token = _TOKEN.match(text, index)
        if token is None:
            break
        kind = token.lastgroup
        raw = token.group(0)
        if kind == "ws":
            if "\n" in raw or "\r" in raw:
                if seen_locator:
                    return _extend_address_tail(text, index, last_good)
                break
            index = token.end()
            continue
        if kind in {"zip", "num"}:
            seen_locator = True
            last_good = token.end()
            index = token.end()
            continue
        if kind == "comma":
            if not seen_locator:
                break
            last_good = token.end()
            index = token.end()
            continue
        if kind == "hash":
            index = token.end()
            continue
        if kind == "other" and raw == "-" and seen_locator:
            last_good = token.end()
            index = token.end()
            continue
        if kind == "other" and raw == "(" and seen_locator:
            unit = _unit_end(text, index)
            if unit is None:
                break
            last_good = unit
            return _extend_address_tail(text, unit, last_good)
        if kind == "word":
            if not seen_locator and not _is_directional(raw) and _norm_word(raw) != "box":
                break
            last_good = token.end()
            index = token.end()
            if _is_street_suffix(raw):
                return _extend_address_tail(text, index, last_good)
            continue
        break
    return last_good if seen_locator else start


def _address_end(text: str, start: int) -> int:
    """Return exclusive end of address material after a privacy trigger."""
    if start >= len(text):
        return start
    opened = _skip_space(text, start)
    closers = {"\"": "\"", "'": "'", "(": ")"}
    if opened < len(text) and text[opened] in closers:
        closer = closers[text[opened]]
        inner_end = _unwrapped_address_end(text, opened + 1)
        if inner_end > opened + 1:
            after = _skip_space(text, inner_end)
            if after < len(text) and text[after] in ".!?":
                after += 1
                after = _skip_space(text, after)
            if after < len(text) and text[after] == closer:
                return after + 1
            return inner_end
    return _unwrapped_address_end(text, start)


def _redact_addresses(text: str) -> str:
    pieces: list[str] = []
    last = 0
    for match in _ADDRESS_TRIGGER.finditer(text):
        end = _address_end(text, match.end())
        if end <= match.end():
            continue
        pieces.append(text[last:match.start()])
        trigger = match.group("trigger").lower()
        label = "home address is" if "home" in trigger else "lives at"
        pieces.append(f"{label} [redacted-address]")
        last = end
    pieces.append(text[last:])
    return "".join(pieces)


def _split_assigned_value(raw: str) -> tuple[str, bool]:
    """Return (credential, ended_clause) for a ``\\S+`` assignment token.

    Wrapping quotes and a trailing sentence period close the clause.
    ``s3cret!`` keeps the bang as part of the credential.
    """
    ended = False
    core = raw
    while core and core[0] in "'\"":
        core = core[1:]
    while core and core[-1] in "'\";,":
        core = core[:-1]
    if core.endswith("."):
        core = core[:-1]
        ended = True
    elif raw.rstrip("'\"").endswith("."):
        ended = True
    return core, ended


def _same_clause_rest(rest: str) -> str:
    trimmed = rest.lstrip()
    if trimmed.startswith(("'", '"')):
        trimmed = trimmed[1:].lstrip()
    for index, char in enumerate(trimmed):
        if char in ".!?":
            return trimmed[:index].strip()
        if char in "\r\n":
            return trimmed[:index].strip()
    return trimmed.strip()


def _is_password_assignment(lead: str, value: str, rest: str, *, ended_clause: bool) -> bool:
    """True when the clause assigns a credential, not a password property."""
    if re.search(r"[:=]", lead):
        return bool(value)
    if ended_clause:
        rest = ""
    clause_rest = _same_clause_rest(rest)
    if clause_rest:
        return False
    if not value:
        return False
    return value.lower() not in _PASSWORD_PROPERTY_PREDICATES


def _redact_passwords(text: str) -> str:
    pieces: list[str] = []
    last = 0
    for match in _PASSWORD_LEAD.finditer(text):
        value_match = re.match(r"\S+", text[match.end() :])
        if value_match is None:
            continue
        raw = value_match.group(0)
        value, ended_clause = _split_assigned_value(raw)
        if not value:
            continue
        value_end = match.end() + value_match.end()
        rest = text[value_end:]
        if not _is_password_assignment(match.group(0), value, rest, ended_clause=ended_clause):
            continue
        pieces.append(text[last:match.start()])
        pieces.append("password [redacted]")
        last = value_end
    pieces.append(text[last:])
    return "".join(pieces)


def redact_text(text: str) -> str:
    text = _SSN.sub("[redacted-ssn]", text)
    text = _EMAIL.sub("[redacted-email]", text)
    text = _PHONE.sub("[redacted-phone]", text)
    text = _redact_addresses(text)
    text = _redact_passwords(text)
    return text
