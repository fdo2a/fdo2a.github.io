"""Small JSON file readers shared by entry scripts (2026-11-22, helper dedupe).

Each reader replaced private copies that were identical line for line. What a reader does on a
missing file, a broken file and a non-UTF-8 file IS its contract — copies that differ even
slightly (another exception set, a default argument, `Path.read_text`, a 1a `enforcing()` exit)
stay private on purpose. Do not widen a reader here; add a separate one.

Stdlib only and Python 3.9 compatible: the correction agent runs gates on the system 3.9.
"""
import json


def load_json_or_none(path):
    """UTF-8 JSON file -> value. Missing, unreadable, not UTF-8 or not JSON -> None (no output)."""
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None

