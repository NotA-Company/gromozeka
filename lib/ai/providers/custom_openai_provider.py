"""
Custom OpenAI provider for LLM models, dood!
"""

import logging
from typing import Any, Dict

from ..abstract import AbstractModel
from .basic_openai_provider import BasicOpenAIModel, BasicOpenAIProvider

logger = logging.getLogger(__name__)


class CustomOpenAIProvider(BasicOpenAIProvider):
    """Custom OpenAI provider implementation, dood!"""

    def __init__(self, config: Dict[str, Any]):
        """Initialize OpenRouter provider, dood!"""
        super().__init__(config)
        if "base_url" not in config:
            raise ValueError("Base URL not provided, dood!")

    def _getBaseUrl(self) -> str:
        """Get the CustomOpenAI base URL, dood!"""
        return self.config["base_url"]

    def _createModelInstance(
        self,
        name: str,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        extraConfig: Dict[str, Any] = {},
    ) -> AbstractModel:
        """Create an CustomOpenAI model instance, dood!"""
        if not self._client:
            raise RuntimeError("OpenAI client not initialized, dood!")

        return BasicOpenAIModel(
            provider=self,
            modelId=modelId,
            modelVersion=modelVersion,
            temperature=temperature,
            contextSize=contextSize,
            openAiClient=self._client,
            extraConfig=extraConfig,
        )
