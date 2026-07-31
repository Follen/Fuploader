#!/usr/bin/env python3
"""Fupload command-line entry point."""

from __future__ import annotations

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from fupload_cli.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
