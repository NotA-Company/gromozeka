#!/usr/bin/env ./venv/bin/python3
"""List all fastembed TextEmbedding models supported by the installed version.

Prints a formatted table of every model the installed ``fastembed`` release can
serve: the HuggingFace model name, embedding dimension, download size in GB,
and short description. Useful for picking a model for the memory-embedding
subsystem or verifying which models are available after an upgrade.

Usage::

    ./venv/bin/python3 scripts/fastembed_list_model.py
"""

from __future__ import annotations

import argparse
import sys

from fastembed import TextEmbedding

# Column widths matching the original layout.
_MODEL_COL_WIDTH: int = 55
_DIM_COL_WIDTH: int = 12
_SIZE_COL_WIDTH: int = 12


def listFastembedModels() -> None:
    """Print a formatted table of all supported fastembed TextEmbedding models.

    Each row shows the HuggingFace model name, embedding dimension, download
    size in GB (1 decimal place), and short description. If the installed
    fastembed reports no models (e.g. network/cache issue), a diagnostic
    message is printed instead.
    """
    models: list[dict[str, object]] = TextEmbedding.list_supported_models()

    if not models:
        print("No models available (check network or cache).")
        return

    print(
        f"{'Model':<{_MODEL_COL_WIDTH}} "
        f"{'Dim':<{_DIM_COL_WIDTH}} "
        f"{'Size (GB)':<{_SIZE_COL_WIDTH}} "
        f"{'Description'}"
    )
    print("-" * 110)

    for modelInfo in models:
        name = str(modelInfo.get("model", "unknown"))
        dim = str(modelInfo.get("dim", "?"))
        sizeVal = modelInfo.get("size_in_GB", "?")
        desc = str(modelInfo.get("description", ""))

        if isinstance(sizeVal, (int, float)):
            sizeStr = f"{sizeVal:.1f}"
        else:
            sizeStr = str(sizeVal)

        print(f"{name:<{_MODEL_COL_WIDTH}} {dim:<{_DIM_COL_WIDTH}} {sizeStr:<{_SIZE_COL_WIDTH}} {desc}")


def main() -> int:
    """Entry point: list all supported fastembed TextEmbedding models.

    Returns:
        ``0`` on success.
    """
    parser = argparse.ArgumentParser(
        description="List all fastembed TextEmbedding models supported by the installed version.",
    )
    parser.parse_args()
    listFastembedModels()
    return 0


if __name__ == "__main__":
    sys.exit(main())
