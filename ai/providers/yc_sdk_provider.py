"""
Yandex Cloud SDK provider for LLM models, dood!
"""
import logging
from typing import Dict, List, Any

from ..abstract import AbstractModel, AbstractLLMProvider, ModelMessage, ModelResultStatus, ModelRunResult

logger = logging.getLogger(__name__)


class YcSdkModel(AbstractModel):
    """Yandex Cloud SDK model implementation, dood!"""
    
    def __init__(
        self, 
        provider: "YcSdkProvider",
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        ycSDK: Any,
    ):
        """Initialize YC SDK model, dood!"""
        super().__init__(provider, modelId, modelVersion, temperature, contextSize)
        self._yc_model = None
        self.ycSDK = ycSDK
        self._initModel()
        
    def _initModel(self):
        """Initialize the actual YC SDK model, dood!"""
        try:
            # Create and configure the model
            self._yc_model = self.ycSDK.models.completions(
                self.model_id, 
                model_version=self.model_version
            ).configure(temperature=self.temperature)
            
            logger.info(f"Initialized YC SDK model {self.model_id}, dood!")
            
        except Exception as e:
            logger.error(f"Failed to initialize YC SDK model {self.model_id}: {e}")
            raise
            
    def _statusToModelRunResultStatus(self, status: int) -> ModelResultStatus:
        return ModelResultStatus(status)

    def run(self, messages: List[ModelMessage]) -> ModelRunResult:
        """Run the YC SDK model with given messages, dood!
        
        Args:
            messages: List of message dictionaries with role and content
            
        Returns:
            Model response
        """
        if not self._yc_model:
            raise RuntimeError("Model not initialized, dood!")
            
        try:
            # Convert messages to YC SDK format if needed
            # For now, pass through as-is
            result = self._yc_model.run([message.toDict('text') for message in messages])
            return ModelRunResult(result, self._statusToModelRunResultStatus(result.status), result.alternatives[0].text)
            
        except Exception as e:
            logger.error(f"Error running YC SDK model {self.model_id}: {e}")
            raise

    #def getEstimateTokensCount(self, data: Any) -> int:
    #    if not self._yc_model:
    #        raise RuntimeError("Model not initialized, dood!")
    #    tokens = self._yc_model.tokenize(data)
    #    return len(tokens)


class YcSdkProvider(AbstractLLMProvider):
    """Yandex Cloud SDK provider implementation, dood!"""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize YC SDK provider, dood!"""
        super().__init__(config)
        self._ycMlSDK = None
        self._initSDK()
        
    def _initSDK(self):
        """Initialize Yandex Cloud ML SDK, dood!"""
        try:
            from yandex_cloud_ml_sdk import YCloudML
            from yandex_cloud_ml_sdk.auth import YandexCloudCLIAuth
            
            folder_id = self.config.get("folder_id")
            yc_profile = self.config.get("yc_profile", None)
            
            if not folder_id:
                raise ValueError("folder_id is required for YC SDK provider, dood!")
                
            self._ycMlSDK = YCloudML(
                folder_id=folder_id,
                auth=YandexCloudCLIAuth(),
                yc_profile=yc_profile
            )
            
            logger.info("YC SDK provider initialized, dood!")
            
        except ImportError:
            logger.error("yandex_cloud_ml_sdk not available, dood!")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize YC SDK: {e}")
            raise
            
    def get_yc_ml_sdk(self):
        """Get the YC ML SDK instance, dood!"""
        return self._ycMlSDK
        
    def addModel(
        self,
        name: str,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int
    ) -> AbstractModel:
        """Add a YC SDK model, dood!"""
        if name in self.models:
            logger.warning(f"Model {name} already exists in YC SDK provider, dood!")
            return self.models[name]
            
        try:
            model = YcSdkModel(
                provider=self,
                modelId=modelId,
                modelVersion=modelVersion,
                temperature=temperature,
                contextSize=contextSize,
                ycSDK=self._ycMlSDK
            )
            
            self.models[name] = model
            logger.info(f"Added YC SDK model {name} ({modelId}), dood!")
            return model
            
        except Exception as e:
            logger.error(f"Failed to add YC SDK model {name}: {e}")
            raise