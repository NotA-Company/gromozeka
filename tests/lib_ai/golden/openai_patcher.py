#!/usr/bin/env python3
"""
Patches for OpenAI library to enable golden data recording and replaying.

This module provides patcher classes that modify the OpenAI library's HTTP client
to use custom transports for recording HTTP traffic during golden data collection
and replaying it during testing. This allows for deterministic testing of AI models
without making actual API calls.
"""

import logging
from typing import Optional

import openai._base_client

from lib.aurumentation.recorder import GoldenDataRecorder
from lib.aurumentation.replayer import GoldenDataReplayer

logger = logging.getLogger(__name__)


class OpenAIReplayerPatcher:
    """Initialize the patcher with no original class reference."""

    def __init__(self):
        """Patcher for OpenAI library that enables replaying recorded HTTP traffic.
    
        This class patches the OpenAI library's AsyncHttpxClientWrapper to use a
        ReplayTransport instead of making actual HTTP requests. This allows tests
        to replay previously recorded golden data scenarios without making real
        API calls to OpenAI-compatible services.
        """
        self.originalClass: Optional[type] = None

    def patch(self, replayer: GoldenDataReplayer) -> None:
        """Patch openai._base_client.AsyncHttpxClientWrapper to use ReplayTransport."""
        try:

            self.originalClass = openai._base_client.AsyncHttpxClientWrapper

            class PatchedAsyncHttpxClientWrapper(openai._base_client.AsyncHttpxClientWrapper):
                def __init__(self, *args, **kwargs):
                    # Force our replay transport to be used
                    kwargs["transport"] = replayer.transport
                    super().__init__(*args, **kwargs)

            openai._base_client.AsyncHttpxClientWrapper = PatchedAsyncHttpxClientWrapper
        except ImportError:
            # OpenAI library not available, nothing to patch
            pass

    def unpatch(self, replayer: GoldenDataReplayer) -> None:
        """Restore the original openai._base_client.AsyncHttpxClientWrapper."""
        if self.originalClass:
            try:
                import openai._base_client

                openai._base_client.AsyncHttpxClientWrapper = self.originalClass
                self.originalClass = None
            except ImportError:
                # OpenAI library not available, nothing to unpatch
                pass


class OpenAIRecorderPatcher:
    def __init__(self):
        self.originalOpenAIClientClass: Optional[type] = None
        self.openaiClientClass: Optional[type] = None

    async def patchOpenAI(self, recorder: GoldenDataRecorder) -> None:
        # Also patch OpenAI's AsyncHttpxClientWrapper if it exists
        try:

            class PatchedOpenAIClient(openai._base_client.AsyncHttpxClientWrapper):
                def __init__(self, *args, **kwargs):
                    logger.info("Patching openai.AsyncHttpxClientWrapper...")
                    # Force our transport to be used
                    kwargs["transport"] = recorder.transport
                    super().__init__(*args, **kwargs)

            self.originalOpenAIClientClass = openai._base_client.AsyncHttpxClientWrapper
            self.openaiClientClass = PatchedOpenAIClient
            # Patch the class in the openai module
            openai._base_client.AsyncHttpxClientWrapper = PatchedOpenAIClient
            logger.info("HttpxRecorder: Patched openai.AsyncHttpxClientWrapper")
        except Exception as e:
            logger.error("HttpxRecorder: OpenAI patch failed, skipping OpenAI client patching")
            logger.exception(e)
            if self.originalOpenAIClientClass is not None:
                openai._base_client.AsyncHttpxClientWrapper = self.originalOpenAIClientClass
            self.originalOpenAIClientClass = None
            self.openaiClientClass = None

    async def unpatchOpenAI(self, recorder: GoldenDataRecorder) -> None:
        if self.openaiClientClass is not None:
            openai._base_client.AsyncHttpxClientWrapper = self.originalOpenAIClientClass
            self.originalOpenAIClientClass = None
            self.openaiClientClass = None
            logger.info("HttpxRecorder: Unpatched openai.AsyncHttpxClientWrapper")
