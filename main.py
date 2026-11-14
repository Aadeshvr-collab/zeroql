#!/usr/bin/env python3
"""Entry point: `python3 main.py examples/employees.csv -q "SELECT ..."`."""
import sys

from zeroql.cli import main

if __name__ == "__main__":
    sys.exit(main())
