"""Small JSON file readers shared by entry scripts (2026-11-22, helper dedupe).

Each reader replaced private copies that were identical line for line. What a reader does on a
missing file, a broken file and a non-UTF-8 file IS its contract — copies that differ even
slightly (another exception set, a default argument, `Path.read_text`, a 1a `enforcing()` exit)
stay private on purpose. Do not widen a reader here; add a separate one.

Stdlib only and Python 3.9 compatible: the correction agent runs gates on the system 3.9.
"""
import json
import os
import sys
from pathlib import Path


def load_json_or_none(path):
    """UTF-8 JSON file -> value. Missing, unreadable, not UTF-8 or not JSON -> None (no output)."""
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def load_json_warn(path):
    """UTF-8 JSON file -> value. Missing -> None silently; any other failure -> one WARN line on
    stderr, then None."""
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f'WARN: could not read {path}: {e}', file=sys.stderr)
        return None


def load_json_missing_none(path):
    """UTF-8 JSON file -> value. Missing -> None; anything else (broken JSON, not UTF-8, a
    directory) raises as before."""
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None


def load_json_strict(path):
    """UTF-8 JSON file -> value. Every failure raises."""
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def load_json_if_exists(path):
    """Falsy path or `os.path.exists(path)` false -> None; otherwise as `load_json_strict`."""
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def load_json_path(path):
    """`json.loads(Path(path).read_text(encoding='utf-8'))` — needs a path (`Path(path)`), every
    failure raises."""
    return json.loads(Path(path).read_text(encoding='utf-8'))
