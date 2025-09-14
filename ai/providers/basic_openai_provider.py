"""
Basic OpenAI provider and model base classes for shared functionality, dood!
"""
import logging
from typing import Dict, List, Any, Optional
from openai import OpenAI

from ..abstract import AbstractModel, AbstractLLMProvider, ModelMessage, ModelResultStatus, ModelRunResult

logger = logging.getLogger(__name__)


class BasicOpenAIModel(AbstractModel):
    """Basic OpenAI model implementation with shared functionality, dood!"""
    
    def __init__(
        self, 
        provider: "BasicOpenAIProvider",
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        openAiClient: OpenAI,
    ):
        """Initialize basic OpenAI model, dood!"""
        super().__init__(provider, modelId, modelVersion, temperature, contextSize)
        self._client = openAiClient
        
    def _getModelId(self) -> str:
        """Get the model name to use in API calls. Override in subclasses, dood!"""
        return self.modelId
        
    def _getExtraParams(self) -> Dict[str, Any]:
        """Get extra parameters for the API call. Override in subclasses, dood!"""
        return {}
        
    def run(self, messages: List[ModelMessage]) -> Any:
        """Run the OpenAI-compatible model with given messages, dood!
        
        Args:
            messages: List of message dictionaries with role and content
            
        Returns:
            Model response
        """
        if not self._client:
            raise RuntimeError("OpenAI client not initialized, dood!")

        try:
            # Prepare base parameters
            params = {
                "model": self._getModelId(),
                "messages": [message.toDict('content') for message in messages],  # type: ignore
                "temperature": self.temperature,
            }
            
            # Add any extra parameters from subclasses
            params.update(self._getExtraParams())
            
            # Use OpenAI-compatible API
            response = self._client.chat.completions.create(**params)

            #for chunk in response:
            #   if chunk.choices[0].delta.content is not None:
            #       print(chunk.choices[0].delta.content, end="")
            
            # TODO: Set proper status based on response
            status = ModelResultStatus.FINAL
            resText = response.choices[0].message.content
            if resText is None:
                resText = ""
                status = ModelResultStatus.UNKNOWN
            return ModelRunResult(response, status, resText)
            
        except Exception as e:
            logger.error(f"Error running OpenAI-compatible model {self.modelId}: {e}")
            raise


class BasicOpenAIProvider(AbstractLLMProvider):
    """Basic OpenAI provider implementation with shared functionality, dood!"""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize basic OpenAI provider, dood!"""
        super().__init__(config)
        self._client: Optional[OpenAI] = None
        self._initClient()
        
    def _getBaseUrl(self) -> str:
        """Get the base URL for the OpenAI API. Override in subclasses, dood!"""
        raise NotImplementedError("Subclasses must implement _get_base_url, dood!")
        
    def _getApiKey(self) -> str:
        """Get the API key from config. Override if needed, dood!"""
        apiKey = self.config.get("api_key")
        if not apiKey:
            raise ValueError("api_key is required for OpenAI-compatible provider, dood!")
        return apiKey
        
    def _getClientParams(self) -> Dict[str, Any]:
        """Get additional client parameters. Override in subclasses if needed, dood!"""
        return {}
        
    def _initClient(self):
        """Initialize OpenAI client, dood!"""
        try:
            api_key = self._getApiKey()
            base_url = self._getBaseUrl()
            
            # Prepare client parameters
            client_params: Dict[str, Any] = {
                "api_key": api_key,
                "base_url": base_url,
            }
            client_params.update(self._getClientParams())
            
            self._client = OpenAI(**client_params)
            
            logger.info(f"{self.__class__.__name__} initialized, dood!")
            
        except ImportError:
            logger.error("openai package not available, dood!")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
            raise
                
    def _createModelInstance(
        self,
        name: str,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int
    ) -> AbstractModel:
        """Create a model instance. Override in subclasses, dood!"""
        raise NotImplementedError("Subclasses must implement _create_model_instance, dood!")
        
    def addModel(
        self,
        name: str,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int
    ) -> AbstractModel:
        """Add an OpenAI-compatible model, dood!"""
        if name in self.models:
            logger.warning(f"Model {name} already exists in {self.__class__.__name__}, dood!")
            return self.models[name]
        
        if not self._client:
            raise RuntimeError("OpenAI client not initialized, dood!")
            
        try:
            model = self._createModelInstance(name, modelId, modelVersion, temperature, contextSize)
            
            self.models[name] = model
            logger.info(f"Added {self.__class__.__name__} model {name} ({modelId}), dood!")
            return model
            
        except Exception as e:
            logger.error(f"Failed to add {self.__class__.__name__} model {name}: {e}")
            raise