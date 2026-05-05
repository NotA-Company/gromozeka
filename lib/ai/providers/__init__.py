"""AI provider implementations for Gromozeka bot.

This module provides various LLM (Large Language Model) provider implementations
that can be used with the Gromozeka bot's AI functionality. Each provider
implements a common interface for interacting with different AI services.

Available Providers:
    - YcAIProvider: Yandex Cloud SDK-based AI provider
    - YcOpenaiProvider: Yandex Cloud OpenAI-compatible API provider
    - OpenrouterProvider: OpenRouter API provider for accessing multiple models

Example:
    >>> from lib.ai.providers import YcAIProvider, YcOpenaiProvider, OpenrouterProvider
    >>> # Use the appropriate provider based on your needs
    >>> provider = YcAIProvider(apiKey="your-api-key")
"""

from .openrouter_provider import OpenrouterProvider
from .yc_openai_provider import YcOpenaiProvider
from .yc_sdk_provider import YcAIProvider

__all__ = ["YcAIProvider", "YcOpenaiProvider", "OpenrouterProvider"]
