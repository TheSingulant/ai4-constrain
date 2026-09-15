"""Minimal Bitcoin-style Base58 helpers for Solana public keys and signatures."""

from __future__ import annotations

_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_INDEX = {char: index for index, char in enumerate(_ALPHABET)}


def b58decode(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("base58 value must be a non-empty string")
    number = 0
    for char in value:
        digit = _INDEX.get(char)
        if digit is None:
            raise ValueError("base58 value contains an invalid character")
        number = number * 58 + digit
    pad = 0
    for char in value:
        if char == "1":
            pad += 1
        else:
            break
    if number == 0:
        raw = b""
    else:
        length = (number.bit_length() + 7) // 8
        raw = number.to_bytes(length, "big")
    return b"\x00" * pad + raw


def b58encode(data: bytes) -> str:
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError("base58 encode requires bytes")
    number = int.from_bytes(data, "big")
    chars: list[str] = []
    while number > 0:
        number, remainder = divmod(number, 58)
        chars.append(_ALPHABET[remainder])
    pad = 0
    for byte in data:
        if byte == 0:
            pad += 1
        else:
            break
    return ("1" * pad) + "".join(reversed(chars))
