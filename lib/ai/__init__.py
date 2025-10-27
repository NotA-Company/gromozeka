"""
AI module for Gromozeka bot - LLM management system, dood!
"""

from .abstract import AbstractLLMProvider, AbstractModel
from .manager import LLMManager

__all__ = ["AbstractModel", "AbstractLLMProvider", "LLMManager"]
