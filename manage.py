#!/usr/bin/env python
"""Django management entry point for the Persian Legal Assistant admin + API."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    # The application package lives under ``src/`` (src layout), so make it
    # importable without requiring an editable install.
    src_path = Path(__file__).resolve().parent / "src"
    if src_path.is_dir() and str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "Django is not installed. Install the API extras: "
            "pip install -e '.[api]'"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
