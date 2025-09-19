"""
Yandex Cloud OpenAI-compatible provider for LLM models, dood!
"""
import logging
from typing import Dict, List, Any, Optional
from openai import OpenAI

from ..abstract import AbstractModel, ModelMessage, ModelResultStatus, ModelRunResult
from .basic_openai_provider import BasicOpenAIModel, BasicOpenAIProvider

logger = logging.getLogger(__name__)

# See
# https://yandex.cloud/ru/docs/foundation-models/concepts/openai-compatibility  
# For compatibility details

class YcOpenaiModel(BasicOpenAIModel):
    """Yandex Cloud OpenAI-compatible model implementation, dood!"""
    
    def __init__(
        self,
        provider: "YcOpenaiProvider",
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,        
        openAiClient: OpenAI,
        folderId: str,
        extraConfig: Dict[str, Any] = {},
    ):
        """Initialize YC OpenAI model, dood!"""
        super().__init__(provider, modelId, modelVersion, temperature, contextSize, openAiClient, extraConfig)
        self._folderId = folderId
            
    def _getModelId(self) -> str:
        """Get the YC-specific model URL, dood!"""
        if not self._folderId:
            raise ValueError("folder_id is required for YC OpenAI provider, dood!")
            
        return f"gpt://{self._folderId}/{self.modelId}/{self.modelVersion}"
        
    def _getExtraParams(self) -> Dict[str, Any]:
        """Get YC-specific extra parameters, dood!"""
        return {
            # "max_tokens": 2000,
            # "stream": True,  # Commented out for now
        }


class YcOpenaiProvider(BasicOpenAIProvider):
    """Yandex Cloud OpenAI-compatible provider implementation, dood!"""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize YC OpenAI provider, dood!"""
        self._folderId = str(config.get("folder_id", ""))
        if not self._folderId:
            raise ValueError("folder_id is required for YC OpenAI provider, dood!")
        
        super().__init__(config)
        
    def _getBaseUrl(self) -> str:
        """Get the Yandex Cloud OpenAI-compatible base URL, dood!"""
        return "https://llm.api.cloud.yandex.net/v1"
        
    def _createModelInstance(
        self,
        name: str,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        extraConfig: Dict[str, Any] = {},
    ) -> AbstractModel:
        """Create a YC OpenAI model instance, dood!"""
        if not self._client:
            raise ValueError("YC OpenAI client not initialized, dood!")
            
        return YcOpenaiModel(
            provider=self,
            modelId=modelId,
            modelVersion=modelVersion,
            temperature=temperature,
            contextSize=contextSize,
            openAiClient=self._client,
            folderId=self._folderId,
            extraConfig=extraConfig,
        )