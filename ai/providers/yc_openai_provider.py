"""
Yandex Cloud OpenAI-compatible provider for LLM models, dood!
"""
import logging
from typing import Dict, List, Any, Optional
from openai import OpenAI

from ..abstract import AbstractModel, AbstractLLMProvider, ModelMessage, ModelResultStatus, ModelRunResult

logger = logging.getLogger(__name__)


class YcOpenaiModel(AbstractModel):
    """Yandex Cloud OpenAI-compatible model implementation, dood!"""
    
    def __init__(
        self, 
        provider: "YcOpenaiProvider",
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        folderId: str,
        openAiClient: OpenAI,
    ):
        """Initialize YC OpenAI model, dood!"""
        super().__init__(provider, modelId, modelVersion, temperature, contextSize)
        self._client = openAiClient
        self._folderId = folderId
        self._modelURL = f"gpt://{folderId}/{modelId}/{modelVersion}"
            
    def run(self, messages: List[ModelMessage]) -> Any:
        """Run the YC OpenAI model with given messages, dood!
        
        Args:
            messages: List of message dictionaries with role and content
            
        Returns:
            Model response
        """

        # https://yandex.cloud/ru/docs/foundation-models/concepts/openai-compatibility  
        try:
            # Use OpenAI-compatible API
            response = self._client.chat.completions.create(
                model=self._modelURL,
                messages=[message.toDict('content') for message in messages], # type: ignore
                max_tokens=2000,
                temperature=self.temperature,
                #stream=True,
            )
            
            #for chunk in response:
            #   if chunk.choices[0].delta.content is not None:
            #       print(chunk.choices[0].delta.content, end="")
            #TODO: Set proper status
            status = ModelResultStatus.FINAL
            resText = response.choices[0].message.content
            if resText is None:
                resText = ""
                status = ModelResultStatus.UNKNOWN
            return ModelRunResult(response, status, resText)
            
        except Exception as e:
            logger.error(f"Error running YC OpenAI model {self.model_id}: {e}")
            raise


class YcOpenaiProvider(AbstractLLMProvider):
    """Yandex Cloud OpenAI-compatible provider implementation, dood!"""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize YC OpenAI provider, dood!"""
        super().__init__(config)
        self._client : Optional[OpenAI] = None
        self._folderId = str(config.get("folder_id", ""))
        self._init_client()
        
    def _init_client(self):
        """Initialize OpenAI client for Yandex Cloud, dood!"""
        try:
            apiKey = self.config.get("api_key")
            
            if not self._folderId or not apiKey:
                raise ValueError("folder_id and api_key are required for YC OpenAI provider, dood!")
                
            # Yandex Cloud OpenAI-compatible endpoint
            baseURL = f"https://llm.api.cloud.yandex.net/v1"
            
            self._client = OpenAI(
                api_key=apiKey,
                base_url=baseURL,
            )
            
            logger.info("YC OpenAI provider initialized, dood!")
            
        except ImportError:
            logger.error("openai package not available, dood!")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize YC OpenAI client: {e}")
            raise
        
    def addModel(
        self,
        name: str,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int
    ) -> AbstractModel:
        """Add a YC OpenAI model, dood!"""
        if name in self.models:
            logger.warning(f"Model {name} already exists in YC OpenAI provider, dood!")
            return self.models[name]
        
        if not self._client:
            raise ValueError("YC OpenAI client not initialized, dood!" )
            
        try:
            model = YcOpenaiModel(
                provider=self,
                modelId=modelId,
                modelVersion=modelVersion,
                temperature=temperature,
                contextSize=contextSize,
                folderId=self._folderId,
                openAiClient=self._client
            )
            
            self.models[name] = model
            logger.info(f"Added YC OpenAI model {name} ({modelId}), dood!")
            return model
            
        except Exception as e:
            logger.error(f"Failed to add YC OpenAI model {name}: {e}")
            raise