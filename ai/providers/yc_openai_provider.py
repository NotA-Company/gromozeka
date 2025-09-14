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
    ):
        """Initialize YC OpenAI model, dood!"""
        super().__init__(provider, modelId, modelVersion, temperature, contextSize, openAiClient)
        self._folderId = folderId
        self._modelURL = f"gpt://{folderId}/{modelId}/{modelVersion}"
            
    def _getModelId(self) -> str:
        """Get the YC-specific model URL, dood!"""
        return self._modelURL
        
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
        super().__init__(config)
        
    def _getBaseUrl(self) -> str:
        """Get the Yandex Cloud OpenAI-compatible base URL, dood!"""
        return "https://llm.api.cloud.yandex.net/v1"
        
    def _getApiKey(self) -> str:
        """Get the API key and validate folder_id, dood!"""
        apiKey = self.config.get("api_key")
        
        if not self._folderId or not apiKey:
            raise ValueError("folder_id and api_key are required for YC OpenAI provider, dood!")
            
        return apiKey
        
    def _createModelInstance(
        self,
        name: str,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int
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
        )