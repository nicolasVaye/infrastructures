#!/usr/bin/env python3
"""i18n completeness gate: every key must exist in en/de/fr, no duplicates.

Parses the _TRANSLATIONS dict with the AST (no import needed — the module
pulls in NiceGUI). Exit 1 with a precise report when the gate fails; used by
CI and by the manual pre-release checklist.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

I18N = Path(__file__).resolve().parent.parent / "frontend" / "app" / "services" / "i18n.py"
LANGS = ("en", "de", "fr")


def main() -> int:
    tree = ast.parse(I18N.read_text())
    table = None
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "_TRANSLATIONS":
            table = node.value
    if table is None:
        print("FAIL: _TRANSLATIONS not found in", I18N)
        return 1

    errors: list[str] = []
    keys: list[str] = []
    for key_node, value_node in zip(table.keys, table.values):
        key = key_node.value
        keys.append(key)
        langs = {k.value for k in value_node.keys}
        missing = [lg for lg in LANGS if lg not in langs]
        if missing:
            errors.append(f"{key}: missing {', '.join(missing)}")

    dupes = sorted({k for k in keys if keys.count(k) > 1})
    for k in dupes:
        errors.append(f"{k}: duplicate key")

    if errors:
        print(f"FAIL: {len(errors)} i18n problem(s):")
        for e in errors:
            print("  -", e)
        return 1
    print(f"OK: {len(keys)} keys, all complete in {LANGS}, no duplicates.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
