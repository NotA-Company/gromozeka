"""
Yandex Cloud ML integration for Gromozeka bot.
"""
import logging
import sys
from typing import Dict, Any

from yandex_cloud_ml_sdk import YCloudML
from yandex_cloud_ml_sdk.auth import YandexCloudCLIAuth

logger = logging.getLogger(__name__)


class YandexMLManager:
    """Manages Yandex Cloud ML SDK initialization and model configuration."""

    def __init__(self, config: Dict[str, Any]):
        """Initialize YandexMLManager with ML configuration."""
        self.config = config
        self.yc_ml = self._init_yc_ml_sdk()
        self.yc_model = self._init_yc_model()

    def _init_yc_ml_sdk(self):
        """Initialize Yandex Cloud ML SDK."""
        folder_id = self.config.get("folder_id")

        try:
            yc_ml = YCloudML(
                folder_id=folder_id,
                auth=YandexCloudCLIAuth(),
                yc_profile=self.config.get("yc_profile", None),
            )
            logger.info("Yandex Cloud ML SDK initialized")
            return yc_ml
        except Exception as e:
            logger.error(f"Failed to initialize Yandex Cloud ML SDK: {e}")
            sys.exit(1)

    def _init_yc_model(self):
        """Initialize Yandex Cloud ML model."""
        model_id = self.config.get("model_id", "yandexgpt-5-lite")
        model_version = self.config.get("model_version", "latest")

        try:
            yc_model = self.yc_ml.models.completions(model_id, model_version=model_version).configure(
                temperature=self.config.get("temperature", 0.5)
            )
            logger.info(f"Yandex Cloud ML model initialized: {model_id}")
            return yc_model
        except Exception as e:
            logger.error(f"Failed to initialize Yandex Cloud ML model: {e}")
            sys.exit(1)

    def get_model(self):
        """Get the configured Yandex Cloud ML model."""
        return self.yc_model

    def get_sdk(self):
        """Get the Yandex Cloud ML SDK instance."""
        return self.yc_ml