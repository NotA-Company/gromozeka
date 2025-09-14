"""
AI module for Gromozeka bot - LLM management system, dood!
"""

from .abstract import AbstractModel, AbstractLLMProvider
from .manager import LLMManager

__all__ = [
    "AbstractModel",
    "AbstractLLMProvider",
    "LLMManager"
]