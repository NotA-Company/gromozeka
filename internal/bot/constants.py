"""
Constants for Telegram bot handlers.
"""

# Emoji constants
DUNNO_EMOJI = "🤷‍♂️"
CHAT_ICON = "👥"
PRIVATE_ICON = "👤"

# Telegram limits
TELEGRAM_MAX_MESSAGE_LENGTH = 4096

# Queue settings
MAX_QUEUE_LENGTH = 32
MAX_QUEUE_AGE = 30 * 60  # 30 minutes

# Processing settings
PROCESSING_TIMEOUT = 30 * 60  # 30 minutes
PRIVATE_CHAT_CONTEXT_LENGTH = 50
SUMMARIZATION_MAX_BATCH_LENGTH = 256

# Weather conversion
HPA_TO_MMHG = 0.75006157584567  # hPA to mmHg coefficient

# Geocoder settings
GEOCODER_LOCATION_LANGS = ["en", "ru"]
