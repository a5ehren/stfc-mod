#!/usr/bin/env python3
"""Compatibility wrapper for ``scripts/il2cpp.py validate``."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.il2cpp_cli import main_validate


if __name__ == "__main__":
    sys.exit(main_validate())
