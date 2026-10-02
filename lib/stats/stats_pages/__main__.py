"""Main entry point for the stats-pages CLI module.

This file allows the package to be run as a module:
    ./venv/bin/python3 -m lib.stats.stats_pages generate ...
    ./venv/bin/python3 -m lib.stats.stats_pages delete PAGE_ID
"""

import sys

from .generator import main

if __name__ == "__main__":
    sys.exit(main())
