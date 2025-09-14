"""
OpenRouter provider for LLM models, dood!
"""
import logging
from typing import Dict, List, Any, Optional
from openai import OpenAI

from ..abstract import AbstractModel, AbstractLLMProvider

logger = logging.getLogger(__name__)


class OpenrouterModel(AbstractModel):
    """OpenRouter model implementation, dood!"""

    def __init__(
        self, 
        provider: "OpenrouterProvider",
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        openAiClient: OpenAI,
    ):
        """Initialize OpenRouter model, dood!"""
        super().__init__(provider, modelId, modelVersion, temperature, contextSize)
        self._client = openAiClient
        self._modelURL = "TODO" #f"gpt://{folderId}/{modelId}/{modelVersion}"

    def run(self, messages: List[Dict[str, str]]) -> Any:
        """Run the OpenRouter model with given messages, dood!
        
        Args:
            messages: List of message dictionaries with role and content
            
        Returns:
            Model response
        """
        if not self._client:
            raise RuntimeError("OpenRouter client not initialized, dood!")

        try:
            # Use OpenAI-compatible API through OpenRouter
            response = self._client.chat.completions.create(
                #extra_headers={
                #    "HTTP-Referer": "<YOUR_SITE_URL>",  # Optional. Site URL for rankings on openrouter.ai.
                #    "X-Title": "<YOUR_SITE_NAME>",  # Optional. Site title for rankings on openrouter.ai.
                #},
                model=self.model_id,
                messages=messages, # type: ignore
                temperature=self.temperature,
                # max_tokens=min(4096, self.context_size)  # Reasonable default
            )

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"Error running OpenRouter model {self.model_id}: {e}")
            raise


class OpenrouterProvider(AbstractLLMProvider):
    """OpenRouter provider implementation, dood!"""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize OpenRouter provider, dood!"""
        super().__init__(config)
        self._client: Optional[OpenAI] = None
        self._initClient()
        
    def _initClient(self):
        """Initialize OpenAI client for OpenRouter, dood!"""
        try:
            api_key = self.config.get("api_key")
            
            if not api_key:
                raise ValueError("api_key is required for OpenRouter provider, dood!")
                
            # OpenRouter endpoint
            base_url = "https://openrouter.ai/api/v1"
            
            self._client = OpenAI(
                api_key=api_key,
                base_url=base_url
            )
            
            logger.info("OpenRouter provider initialized, dood!")
            
        except ImportError:
            logger.error("openai package not available, dood!")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize OpenRouter client: {e}")
            raise
            
    def get_openai_client(self):
        """Get the OpenAI client instance configured for OpenRouter, dood!"""
        return self._client
        
    def addModel(
        self,
        name: str,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int
    ) -> AbstractModel:
        """Add an OpenRouter model, dood!"""
        if name in self.models:
            logger.warning(f"Model {name} already exists in OpenRouter provider, dood!")
            return self.models[name]
        
        if not self._client:
            raise RuntimeError("OpenRouter client not initialized, dood!")
            
        try:
            model = OpenrouterModel(
                provider=self,
                modelId=modelId,
                modelVersion=modelVersion,
                temperature=temperature,
                contextSize=contextSize,
                openAiClient=self._client
            )
            
            self.models[name] = model
            logger.info(f"Added OpenRouter model {name} ({modelId}), dood!")
            return model
            
        except Exception as e:
            logger.error(f"Failed to add OpenRouter model {name}: {e}")
            raise
