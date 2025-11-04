#!venv/bin/python3
# -*- coding: utf-8 -*-

"""
Utility for showing profiler stats from log
"""

from __future__ import annotations

import logging
import pstats
import sys
from pstats import SortKey

# Configure basic logging first
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.DEBUG)
logger = logging.getLogger(__name__)


def main():
    if len(sys.argv) < 2:
        logger.error(f"Usage: {sys.argv[0]} <log_file>")
        sys.exit(1)

    logger.debug(f"{sys.argv}")
    logFile = sys.argv[1]
    p = pstats.Stats(logFile)
    p.sort_stats(SortKey.CUMULATIVE).print_stats(30)


if __name__ == "__main__":
    main()
