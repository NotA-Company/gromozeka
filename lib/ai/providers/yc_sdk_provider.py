"""
Yandex Cloud SDK provider for LLM models, dood!
"""
import logging
from typing import Dict, List, Any

from yandex_cloud_ml_sdk import YCloudML
from yandex_cloud_ml_sdk.auth import YandexCloudCLIAuth
from yandex_cloud_ml_sdk._exceptions import AioRpcError

from ..abstract import AbstractModel, AbstractLLMProvider
from ..models import LLMAbstractTool, ModelMessage, ModelResultStatus, ModelRunResult

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
        extraConfig: Dict[str, Any] = {}
    ):
        """Initialize YC SDK model, dood!"""
        super().__init__(provider, modelId, modelVersion, temperature, contextSize)
        self._ycModel = None
        self.ycSDK = ycSDK
        self._config = extraConfig
        self.supportText = self._config.get("support_text", True)
        self.supportImages = self._config.get("support_images", False)
        self._initModel()

    def _initModel(self):
        """Initialize the actual YC SDK model, dood!"""
        try:
            kwargs: Dict[str, Any] = {}

            if self.supportText and self.supportImages:
                raise ValueError(
                    "Only one of support_text and support_images can be True for YC SDK model, dood"
                )

            if not self.supportText and not self.supportImages:
                raise ValueError(
                    "Either support_text or support_images must be True for YC SDK model, dood"
                )

            # Text generation Models
            if self.supportText:
                kwargs.update(
                    {
                        "temperature": self.temperature,
                    }
                )

                self._ycModel = self.ycSDK.models.completions(
                    self.modelId, model_version=self.modelVersion
                ).configure(**kwargs)

            # Image generation Models
            if self.supportImages:
                for key in ["width_ratio", "height_ratio", "seed"]:
                    if key in self._config:
                        kwargs[key] = self._config[key]

                self._ycModel = self.ycSDK.models.image_generation(
                    self.modelId, model_version=self.modelVersion
                ).configure(**kwargs)

            logger.info(f"Initialized YC SDK model {self.modelId}, dood!")

        except Exception as e:
            logger.error(f"Failed to initialize YC SDK model {self.modelId}: {e}")
            raise

    def _statusToModelRunResultStatus(self, status: int) -> ModelResultStatus:
        return ModelResultStatus(status)

    def generateText(self, messages: List[ModelMessage], tools: List[LLMAbstractTool] = []) -> ModelRunResult:
        """Run the YC SDK model with given messages, dood!
        
        Args:
            messages: List of message dictionaries with role and content
            
        Returns:
            Model response
        """
        if not self._ycModel:
            raise RuntimeError("Model not initialized, dood!")

        if tools:
            raise NotImplementedError("Tools not supported by YC SDK models for now, dood!")

        if not self.supportText:
            raise NotImplementedError(f"Text generation isn't supported by {self.modelId}, dood!")

        try:
            # Convert messages to YC SDK format if needed
            # For now, pass through as-is
            result = self._ycModel.run([message.toDict('text') for message in messages])
            return ModelRunResult(result, self._statusToModelRunResultStatus(result.status), result.alternatives[0].text)

        except Exception as e:
            logger.error(f"Error running YC SDK model {self.modelId}: {e}")
            raise

    def generateImage(self, messages: List[ModelMessage]) -> ModelRunResult:
        """Generate an image via the YC SDK model, dood"""

        if not self._ycModel:
            raise RuntimeError("Model not initialized, dood!")

        if not self.supportImages:
            raise NotImplementedError(f"Image generation isn't supported by {self.modelId}, dood")
        
        # From docs:
        # # Sample 3: run with several messages specifying weight
        # operation = model.run_deferred([{"text": message1, "weight": 5}, message2])
        # TODO: Think about support of message weights
        
        result: Any = None
        resultStatus: ModelResultStatus = ModelResultStatus.UNKNOWN

        try:
            operation = self._ycModel.run_deferred([message.toDict('text', skipRole=True) for message in messages])
            result = operation.wait()
            resultStatus = ModelResultStatus.FINAL
        except Exception as e:
            resultStatus = ModelResultStatus.ERROR
            errorMsg = str(e)
            logger.error(f"Error generating image with YC SDK model {self.modelId}: {type(e).__name__}#{e}")
            #logger.info(e.__dict__)
            ethicDetails = [
              "it is not possible to generate an image from this request because it may violate the terms of use",
            ]
            
            if isinstance(e, AioRpcError) and hasattr(e, "details"):
                errorMsg = str(e.details())
                if errorMsg in ethicDetails:
                    resultStatus = ModelResultStatus.CONTENT_FILTER
                    logger.warning(f"Content filter error: '{errorMsg}'")
            
            if resultStatus != ModelResultStatus.CONTENT_FILTER:
                # Do not log content filter errors
                logger.exception(e)

            return ModelRunResult(result, resultStatus, resultText=errorMsg, error=e)
        logger.debug(f"Image generation Result: {result}")
        return ModelRunResult(
            result,
            ModelResultStatus.FINAL if result.image_bytes else ModelResultStatus.UNKNOWN,
            mediaMimeType="image/jpeg",
            mediaData=result.image_bytes,
        )

    # def getEstimateTokensCount(self, data: Any) -> int:
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
            folder_id = self.config.get("folder_id")
            yc_profile = self.config.get("yc_profile", None)
            
            if not folder_id:
                raise ValueError("folder_id is required for YC SDK provider, dood!")
            
            logger.debug(f"Initializing YC SDK provider with folder_id: {folder_id} and yc_profile: {yc_profile}, dood")
            #TODO: Add ability to configure somehow else
            self._ycMlSDK = YCloudML(
                folder_id=folder_id,
                auth=YandexCloudCLIAuth(),
                yc_profile=yc_profile
            )
            
            logger.info("YC SDK provider initialized, dood!")

        except Exception as e:
            logger.error(f"Failed to initialize YC SDK: {e}")
            raise
        
    def addModel(
        self,
        name: str,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        extraConfig: Dict[str, Any] = {},
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
                ycSDK=self._ycMlSDK,
                extraConfig=extraConfig,
            )
            
            self.models[name] = model
            logger.info(f"Added YC SDK model {name} ({modelId}), dood!")
            return model
            
        except Exception as e:
            logger.error(f"Failed to add YC SDK model {name}: {e}")
            raise
