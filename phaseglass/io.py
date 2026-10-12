# SPDX-License-Identifier: MIT
"""Strict bounded JSON and no-clobber artifact writing."""

import json
from pathlib import Path

MAX_INPUT = 2 * 1024 * 1024


def reject_constant(value):
    raise ValueError("Non-finite JSON numbers are forbidden")


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON object key: " + key)
        value[key] = item
    return value


def decode(raw):
    if len(raw) > MAX_INPUT:
        raise ValueError("JSON input exceeds 2 MiB")
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        # Explicit structural cap, independent of a Python version's decoder
        # recursion behavior. Quoted/escaped brackets do not contribute depth.
        depth, quoted, escaped = 0, False, False
        for character in text:
            if quoted:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    quoted = False
            elif character == '"':
                quoted = True
            elif character in "[{":
                depth += 1
                if depth > 32:
                    raise ValueError("JSON nesting exceeds 32 levels")
            elif character in "]}":
                depth -= 1
        return json.loads(
            text, parse_constant=reject_constant, object_pairs_hook=unique_object
        )
    except (UnicodeDecodeError, RecursionError) as exc:
        raise ValueError("JSON must be UTF-8 with bounded nesting") from exc


def read_json(path):
    with Path(path).open("rb") as handle:
        return decode(handle.read(MAX_INPUT + 1))


def encoded(value):
    return json.dumps(
        value, allow_nan=False, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def write_new(path, data):
    # Exclusive create preserves an existing artifact, including symlink targets.
    with Path(path).open("xb") as handle:
        handle.write(data)
