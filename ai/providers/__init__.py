"""
LLM Providers for Gromozeka bot, dood!
"""

from .yc_openai_provider import YcOpenaiProvider
from .openrouter_provider import OpenrouterProvider

__all__ = [
    "YcOpenaiProvider", 
    "OpenrouterProvider"
]