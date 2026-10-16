"""Typed configuration models for the Gromozeka bot.

This module holds the ``TypedDict`` shapes returned by
[`ConfigManager`](internal/config/manager.py) accessors. Config-specific
models live here so ``manager.py`` stays focused on loading, merging, and
serving configuration, and new config models have a natural home alongside
the existing ones.

Example:
    >>> from internal.config.models import VisionConfigDict
    >>> visionConfig: VisionConfigDict = {"image-format": "image/jpeg"}
"""

from typing import TypedDict

#: Configuration shape of the ``[bot.vision]`` table (nested under ``[bot]``).
#: Defined with the functional TypedDict syntax because the TOML keys are
#: dashed and therefore not valid identifiers for the class-based syntax.
#: Keys are individually optional (``total=False``) so partial overrides
#: merged from additional config dirs remain valid and the "section absent"
#: fallback can be an empty mapping. Key strings match
#: ``configs/00-defaults/vision.toml`` exactly.
VisionConfigDict = TypedDict(
    "VisionConfigDict",
    {
        "max-image-dimension": int,
        "image-format": str,
        "image-quality": int,
        "ttl-days": int,
        "alpha-background": str,
    },
    total=False,
)

__all__ = ["VisionConfigDict"]
