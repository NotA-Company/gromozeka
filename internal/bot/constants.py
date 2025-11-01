"""
Constants for Telegram bot handlers.
"""

import telegram.constants

# Emoji constants
DUNNO_EMOJI = "🤷‍♂️"
ROBOT_EMOJI = "🤖"
CHAT_ICON = "👥"
PRIVATE_ICON = "👤"

# Telegram limits
# TELEGRAM_MAX_MESSAGE_LENGTH = 4096
TELEGRAM_MAX_MESSAGE_LENGTH = telegram.constants.MessageLimit.MAX_TEXT_LENGTH

# Processing settings
PROCESSING_TIMEOUT = 30 * 60  # 30 minutes
RANDOM_ANSWER_CONTEXT_LENGTH = 50
SUMMARIZATION_MAX_BATCH_LENGTH = 256

# Weather conversion
HPA_TO_MMHG = 0.75006157584567  # hPA to mmHg coefficient

# Geocoder settings
GEOCODER_LOCATION_LANGS = ["en", "ru"]
