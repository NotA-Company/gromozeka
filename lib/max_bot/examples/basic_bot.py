#!/usr/bin/env python3
"""
Basic Echo Bot Example

This example demonstrates the fundamental usage of the Max Bot client library.
It creates a simple echo bot that responds to text messages by echoing them back.

Features demonstrated:
- Basic client initialization
- Update polling
- Message handling
- Sending responses
- Error handling
- Logging configuration

Run this example:
    python basic_bot.py

Requirements:
    - Set MAX_BOT_TOKEN environment variable with your bot access token
"""

import asyncio
import logging
import os
import sys
from typing import cast

# Add the parent directory to the path so we can import lib.max_bot
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from lib.max_bot import (  # noqa: E402
    AuthenticationError,
    MaxBotClient,
    MaxBotError,
    SenderAction,
    UpdateType,
)
from lib.max_bot.models import TextFormat  # noqa: E402


def setup_logging() -> None:
    """Configure logging for the bot."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Set specific logger level for the max_bot library
    logging.getLogger("lib.max_bot").setLevel(logging.DEBUG)


def get_token() -> str:
    """Get the bot token from environment variables."""
    token = os.getenv("MAX_BOT_TOKEN")
    if not token:
        print("❌ Error: MAX_BOT_TOKEN environment variable is not set!")
        print("Please set your bot token:")
        print("export MAX_BOT_TOKEN='your_access_token_here'")
        sys.exit(1)
    return token


async def handle_message(client: MaxBotClient, update) -> None:
    """Handle incoming message updates.

    Args:
        client: The MaxBotClient instance
        update: The update object containing the message
    """
    try:
        message = update.message
        chat_id = message.recipient.chat_id
        user_name = message.sender.first_name or message.sender.user_id

        # Extract message text
        text = message.body.text if message.body.text else ""

        logging.info(f"📨 Received message from {user_name}: {text}")

        # Skip empty messages
        if not text.strip():
            return

        # Show typing action
        await client.sendAction(chat_id, SenderAction.TYPING)

        # Echo the message back
        echo_text = f"You said: {text}"

        # Send the echo response
        result = await client.sendMessage(chatId=chat_id, text=echo_text)

        logging.info(f"✅ Echo sent: {result.message.body.mid}")

    except MaxBotError as e:
        logging.error(f"❌ Error handling message: {e}")
    except Exception as e:
        logging.error(f"❌ Unexpected error handling message: {e}")


async def handle_callback_query(client: MaxBotClient, update) -> None:
    """Handle callback query updates (button clicks).

    Args:
        client: The MaxBotClient instance
        update: The update object containing the callback query
    """
    try:
        callback = update.callbackQuery
        user_name = callback.sender.first_name or callback.sender.user_id

        logging.info(f"🔘 Callback from {user_name}: {callback.payload}")

        # Answer the callback query
        await client.answerCallbackQuery(
            queryId=callback.query_id, text=f"Button clicked: {callback.payload}", showAlert=False
        )

        logging.info(f"✅ Callback answered: {callback.query_id}")

    except MaxBotError as e:
        logging.error(f"❌ Error handling callback: {e}")
    except Exception as e:
        logging.error(f"❌ Unexpected error handling callback: {e}")


async def handle_bot_added(client: MaxBotClient, update) -> None:
    """Handle bot added to chat events.

    Args:
        client: The MaxBotClient instance
        update: The update object containing the bot added event
    """
    try:
        chat_id = update.chat.chat_id
        chat_title = update.chat.title or "Private Chat"

        logging.info(f"🤖 Bot added to chat: {chat_title}")

        # Send welcome message
        welcome_text = (
            "Hello! 👋\n\n"
            "I'm a simple echo bot. Send me any message and I'll echo it back!\n\n"
            "Try typing:\n"
            "• Any text message\n"
            "• /help for this message\n"
            "• /info for bot information"
        )

        await client.sendMessage(chatId=chat_id, text=welcome_text)

        logging.info(f"✅ Welcome message sent to {chat_title}")

    except MaxBotError as e:
        logging.error(f"❌ Error handling bot added: {e}")
    except Exception as e:
        logging.error(f"❌ Unexpected error handling bot added: {e}")


async def handle_commands(client: MaxBotClient, update) -> bool:
    """Handle bot commands.

    Args:
        client: The MaxBotClient instance
        update: The update object containing the message

    Returns:
        True if a command was handled, False otherwise
    """
    try:
        message = update.message
        chat_id = message.recipient.chat_id
        text = message.body.text or ""

        # Check if message is a command
        if not text.startswith("/"):
            return False

        command = text.lower().split()[0]
        user_name = message.sender.first_name or "User"

        logging.info(f"🎯 Command from {user_name}: {command}")

        if command == "/help":
            help_text = (
                "🤖 *Echo Bot Help*\n\n"
                "Available commands:\n"
                "• `/help` - Show this help message\n"
                "• `/info` - Show bot information\n"
                "• `/ping` - Test bot responsiveness\n\n"
                "Just send any text message and I'll echo it back!"
            )

            await client.sendMessage(chatId=chat_id, text=help_text, format=cast(TextFormat, TextFormat.MARKDOWN))

        elif command == "/info":
            bot_info = await client.getMyInfo()
            info_text = (
                f"🤖 *Bot Information*\n\n"
                f"📛 Name: {bot_info.first_name}\n"
                f"🆔 ID: {bot_info.user_id}\n"
                f"📝 Description: {bot_info.description or 'No description'}\n"
                f"🔗 Commands: {len(bot_info.commands) if bot_info.commands else 0}"
            )

            await client.sendMessage(chatId=chat_id, text=info_text, format=cast(TextFormat, TextFormat.MARKDOWN))

        elif command == "/ping":
            await client.sendAction(chat_id, SenderAction.TYPING)
            await asyncio.sleep(0.5)  # Simulate thinking

            await client.sendMessage(chatId=chat_id, text="🏓 Pong! Bot is responsive!")

        else:
            await client.sendMessage(
                chatId=chat_id, text=f"❓ Unknown command: {command}\nType /help for available commands."
            )

        return True

    except MaxBotError as e:
        logging.error(f"❌ Error handling command: {e}")
        return False
    except Exception as e:
        logging.error(f"❌ Unexpected error handling command: {e}")
        return False


async def process_update(client: MaxBotClient, update) -> None:
    """Process a single update from the API.

    Args:
        client: The MaxBotClient instance
        update: The update object to process
    """
    try:
        # Handle different update types
        if update.updateType == UpdateType.MESSAGE_CREATED:
            # First check for commands
            if not await handle_commands(client, update):
                # If not a command, handle as regular message
                await handle_message(client, update)

        elif update.updateType == UpdateType.MESSAGE_CALLBACK:
            await handle_callback_query(client, update)

        elif update.updateType == UpdateType.BOT_ADDED_TO_CHAT:
            await handle_bot_added(client, update)

        elif update.updateType == UpdateType.BOT_STARTED:
            # Similar to bot added, but for private chats
            await handle_bot_added(client, update)

        else:
            logging.debug(f"🔄 Unhandled update type: {update.updateType}")

    except Exception as e:
        logging.error(f"❌ Error processing update: {e}")


async def run_bot() -> None:
    """Main bot function that handles the bot lifecycle."""
    token = get_token()

    logging.info("🚀 Starting Basic Echo Bot...")

    try:
        # Initialize the client
        async with MaxBotClient(token) as client:
            # Get bot information
            bot_info = await client.getMyInfo()
            logging.info(f"✅ Bot started successfully: {bot_info.first_name}")
            logging.info(f"🆔 Bot ID: {bot_info.user_id}")

            # Health check
            if await client.healthCheck():
                logging.info("✅ API health check passed")
            else:
                logging.warning("⚠️ API health check failed")

            # Start polling for updates
            logging.info("🔄 Starting to poll for updates...")
            logging.info("📱 Send a message to your bot to test it!")
            logging.info("⏹️ Press Ctrl+C to stop the bot")

            update_count = 0

            # Create a simple polling loop
            last_event_id = None
            while True:
                updates = await client.getUpdates(lastEventId=last_event_id)
                for update in updates.updates:
                    update_count += 1
                    logging.debug(f"📨 Processing update #{update_count}")

                    # Process the update
                    await process_update(client, update)

                # Update the last event ID for next polling
                if updates.marker:
                    last_event_id = updates.marker

    except AuthenticationError:
        logging.error("❌ Authentication failed! Please check your bot token.")
        sys.exit(1)
    except KeyboardInterrupt:
        logging.info("⏹️ Bot stopped by user")
    except Exception as e:
        logging.error(f"❌ Fatal error: {e}")
        sys.exit(1)


def main() -> None:
    """Entry point for the bot."""
    setup_logging()

    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logging.info("👋 Goodbye!")
    except Exception as e:
        logging.error(f"❌ Fatal error in main: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
