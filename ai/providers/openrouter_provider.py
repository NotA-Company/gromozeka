"""
OpenRouter provider for LLM models, dood!
"""
import logging
from typing import Dict, List, Any, Optional
from openai import OpenAI

from ..abstract import AbstractModel, ModelMessage, ModelResultStatus, ModelRunResult
from .basic_openai_provider import BasicOpenAIModel, BasicOpenAIProvider

logger = logging.getLogger(__name__)


class OpenrouterModel(BasicOpenAIModel):
    """OpenRouter model implementation, dood!"""

    def __init__(
        self,
        provider: "OpenrouterProvider",
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        openAiClient: OpenAI,
        supportTools: bool = False,
    ):
        """Initialize OpenRouter model, dood!"""
        super().__init__(provider, modelId, modelVersion, temperature, contextSize, openAiClient, supportTools)
        
    def _getExtraParams(self) -> Dict[str, Any]:
        """Get OpenRouter-specific extra parameters, dood!"""
        return {
            "extra_headers": {
                "HTTP-Referer": "https://sourcecraft.dev/notacompany/gromozeka",  # Optional. Site URL for rankings on openrouter.ai.
                "X-Title": "Gromozeka AI Bot",  # Optional. Site title for rankings on openrouter.ai.
            },
            # "max_tokens": min(4096, self.context_size)  # Reasonable default
        }


class OpenrouterProvider(BasicOpenAIProvider):
    """OpenRouter provider implementation, dood!"""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize OpenRouter provider, dood!"""
        super().__init__(config)
        
    def _getBaseUrl(self) -> str:
        """Get the OpenRouter base URL, dood!"""
        return "https://openrouter.ai/api/v1"
        
    def _createModelInstance(
        self,
        name: str,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        extraConfig: Dict[str, Any] = {},
    ) -> AbstractModel:
        """Create an OpenRouter model instance, dood!"""
        if not self._client:
            raise RuntimeError("OpenRouter client not initialized, dood!")
            
        return OpenrouterModel(
            provider=self,
            modelId=modelId,
            modelVersion=modelVersion,
            temperature=temperature,
            contextSize=contextSize,
            openAiClient=self._client,
            supportTools=bool(extraConfig.get("support_tools", False)),
        )
