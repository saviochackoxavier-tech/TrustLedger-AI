#!/usr/bin/env python3
"""Django's command-line utility for administrative tasks."""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
# Guarantee the project root is importable even under `python -P` /
# PYTHONSAFEPATH-style interpreters that omit the script directory.
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Activate your virtualenv and "
            "`pip install -r requirements.txt` first."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
