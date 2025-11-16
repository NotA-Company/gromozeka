#!/usr/bin/env python3
"""
Keyboard Bot Example

This example demonstrates the usage of inline and reply keyboards in Max Bot.
It shows how to create interactive bots with buttons, handle callbacks, and manage
different types of keyboards.

Features demonstrated:
- Inline keyboards with callback buttons
- Reply keyboards with user interaction
- Button types (callback, link, request contact, etc.)
- Callback query handling
- Keyboard management (show/hide/remove)
- Dynamic keyboard creation

Run this example:
    python keyboard_bot.py

Requirements:
    - Set MAX_BOT_TOKEN environment variable with your bot access token
"""

import asyncio
import logging
import os
import sys
from typing import Any, Dict, List, cast

# Add the parent directory to the path so we can import lib.max_bot
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from lib.max_bot import AuthenticationError, ButtonType, MaxBotClient, MaxBotError, UpdateType  # noqa: E402
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


class KeyboardBot:
    """A bot that demonstrates various keyboard features."""

    def __init__(self, client: MaxBotClient):
        """Initialize the keyboard bot.

        Args:
            client: The MaxBotClient instance
        """
        self.client = client
        self.user_states: Dict[int, str] = {}  # Track user interaction states

    def create_main_inline_keyboard(self) -> List[List[Dict]]:
        """Create the main inline keyboard with various options.

        Returns:
            List of keyboard rows with buttons
        """
        return [
            [
                {"type": ButtonType.CALLBACK, "text": "🔘 Callback Button", "payload": "callback_demo"},
                {"type": ButtonType.LINK, "text": "🌐 Visit Website", "url": "https://max.ru"},
            ],
            [
                {"type": ButtonType.CALLBACK, "text": "📊 Show Statistics", "payload": "show_stats"},
                {"type": ButtonType.CALLBACK, "text": "🎮 Play Game", "payload": "play_game"},
            ],
            [
                {"type": ButtonType.CALLBACK, "text": "⚙️ Settings", "payload": "show_settings"},
                {"type": ButtonType.CALLBACK, "text": "❌ Close", "payload": "close_keyboard"},
            ],
        ]

    def create_game_keyboard(self) -> List[List[Dict]]:
        """Create a game keyboard for the number guessing game.

        Returns:
            List of keyboard rows with game buttons
        """
        return [
            [
                {"type": ButtonType.CALLBACK, "text": "1️⃣", "payload": "guess_1"},
                {"type": ButtonType.CALLBACK, "text": "2️⃣", "payload": "guess_2"},
                {"type": ButtonType.CALLBACK, "text": "3️⃣", "payload": "guess_3"},
            ],
            [
                {"type": ButtonType.CALLBACK, "text": "4️⃣", "payload": "guess_4"},
                {"type": ButtonType.CALLBACK, "text": "5️⃣", "payload": "guess_5"},
                {"type": ButtonType.CALLBACK, "text": "🎲 Random", "payload": "guess_random"},
            ],
            [{"type": ButtonType.CALLBACK, "text": "🔙 Back to Menu", "payload": "back_to_menu"}],
        ]

    def create_settings_keyboard(self) -> List[List[Dict]]:
        """Create a settings keyboard.

        Returns:
            List of keyboard rows with settings buttons
        """
        return [
            [
                {"type": ButtonType.CALLBACK, "text": "🔔 Notifications: ON", "payload": "toggle_notifications"},
                {"type": ButtonType.CALLBACK, "text": "🌙 Dark Mode: OFF", "payload": "toggle_dark_mode"},
            ],
            [
                {"type": ButtonType.CALLBACK, "text": "🌐 Language: English", "payload": "change_language"},
                {"type": ButtonType.CALLBACK, "text": "📊 Show Stats", "payload": "show_user_stats"},
            ],
            [{"type": ButtonType.CALLBACK, "text": "🔙 Back to Menu", "payload": "back_to_menu"}],
        ]

    def create_reply_keyboard(self) -> List[List[Dict[str, Any]]]:
        """Create a reply keyboard for user interaction.

        Returns:
            List of keyboard rows with button dictionaries
        """
        return [
            [{"type": "reply", "text": "📍 Share Location"}, {"type": "reply", "text": "📞 Share Contact"}],
            [{"type": "reply", "text": "📸 Send Photo"}, {"type": "reply", "text": "📄 Send Document"}],
            [{"type": "reply", "text": "❌ Remove Keyboard"}],
        ]

    async def send_welcome_message(self, chat_id: int, user_name: str) -> None:
        """Send a welcome message with the main inline keyboard.

        Args:
            chat_id: The chat ID to send the message to
            user_name: The user's name for personalization
        """
        welcome_text = (
            f"👋 Hello, {user_name}!\n\n"
            "🎮 *Keyboard Bot Demo*\n\n"
            "This bot demonstrates various keyboard features:\n"
            "• 🔘 Inline keyboards with callbacks\n"
            "• 🌐 Link buttons\n"
            "• 📊 Interactive menus\n"
            "• 🎮 Mini-games\n"
            "• ⚙️ Settings management\n\n"
            "Try the buttons below! 👇"
        )

        keyboard = self.client.createInlineKeyboard(self.create_main_inline_keyboard())

        await self.client.sendMessage(
            chatId=chat_id, text=welcome_text, format=cast(TextFormat, TextFormat.MARKDOWN), inlineKeyboard=keyboard
        )

    async def handle_callback_query(self, update) -> None:
        """Handle callback queries from inline keyboard buttons.

        Args:
            update: The update object containing the callback query
        """
        callback = update.callbackQuery
        user_id = callback.sender.user_id
        chat_id = callback.message.recipient.chat_id
        payload = callback.payload

        logging.info(f"🔘 Callback from user {user_id}: {payload}")

        try:
            # Handle different callback actions
            if payload == "callback_demo":
                await self.client.answerCallbackQuery(
                    queryId=callback.query_id, text="🔘 Callback button clicked!", showAlert=True
                )

            elif payload == "show_stats":
                stats_text = (
                    "📊 *Bot Statistics*\n\n"
                    "👥 Active users: 1 (you!)\n"
                    "💬 Messages sent: 42\n"
                    "🔘 Buttons clicked: 13\n"
                    "🎮 Games played: 7\n"
                    "⏰ Uptime: 2 hours"
                )

                keyboard = self.client.createInlineKeyboard(
                    [
                        [{"type": ButtonType.CALLBACK, "text": "🔄 Refresh", "payload": "show_stats"}],
                        [{"type": ButtonType.CALLBACK, "text": "🔙 Back", "payload": "back_to_menu"}],
                    ]
                )

                await self.client.editMessage(
                    messageId=callback.message.body.mid,
                    text=stats_text,
                    format=cast(TextFormat, TextFormat.MARKDOWN),
                    inlineKeyboard=keyboard,
                )

                await self.client.answerCallbackQuery(queryId=callback.query_id, text="📊 Statistics updated!")

            elif payload == "play_game":
                # Initialize game state
                self.user_states[user_id] = "playing_game"

                game_text = (
                    "🎮 *Number Guessing Game*\n\n"
                    "I'm thinking of a number between 1 and 5!\n"
                    "Can you guess it? 🤔\n\n"
                    "Choose a number below:"
                )

                keyboard = self.client.createInlineKeyboard(self.create_game_keyboard())

                await self.client.editMessage(
                    messageId=callback.message.body.mid,
                    text=game_text,
                    format=cast(TextFormat, TextFormat.MARKDOWN),
                    inlineKeyboard=keyboard,
                )

                await self.client.answerCallbackQuery(queryId=callback.query_id, text="🎮 Game started! Good luck!")

            elif payload.startswith("guess_"):
                await self.handle_game_guess(user_id, callback, payload)

            elif payload == "show_settings":
                settings_text = "⚙️ *Bot Settings*\n\n" "Customize your bot experience:\n\n" "Toggle options below:"

                keyboard = self.client.createInlineKeyboard(self.create_settings_keyboard())

                await self.client.editMessage(
                    messageId=callback.message.body.mid,
                    text=settings_text,
                    format=cast(TextFormat, TextFormat.MARKDOWN),
                    inlineKeyboard=keyboard,
                )

                await self.client.answerCallbackQuery(queryId=callback.query_id, text="⚙️ Settings opened")

            elif payload == "toggle_notifications":
                await self.client.answerCallbackQuery(
                    queryId=callback.query_id, text="🔔 Notifications toggled!", showAlert=True
                )

            elif payload == "toggle_dark_mode":
                await self.client.answerCallbackQuery(
                    queryId=callback.query_id, text="🌙 Dark mode toggled!", showAlert=True
                )

            elif payload == "change_language":
                await self.client.answerCallbackQuery(
                    queryId=callback.query_id, text="🌐 Language selection coming soon!", showAlert=True
                )

            elif payload == "show_user_stats":
                stats_text = (
                    f"👤 *Your Statistics*\n\n"
                    f"🆔 User ID: {user_id}\n"
                    f"🔘 Buttons clicked: {len([k for k in self.user_states.keys()])}\n"
                    f"🎮 Games played: 1\n"
                    f"⏰ First interaction: Just now!"
                )

                keyboard = self.client.createInlineKeyboard(
                    [[{"type": ButtonType.CALLBACK, "text": "🔙 Back", "payload": "show_settings"}]]
                )

                await self.client.editMessage(
                    messageId=callback.message.body.mid,
                    text=stats_text,
                    format=cast(TextFormat, TextFormat.MARKDOWN),
                    inlineKeyboard=keyboard,
                )

                await self.client.answerCallbackQuery(queryId=callback.query_id, text="📊 Your stats loaded!")

            elif payload == "back_to_menu":
                await self.send_welcome_message(chat_id, callback.sender.first_name or "User")
                await self.client.answerCallbackQuery(queryId=callback.query_id, text="🔙 Back to main menu")

            elif payload == "close_keyboard":
                await self.client.editMessage(
                    messageId=callback.message.body.mid, text="👋 Keyboard closed! Type /start to show it again."
                )

                await self.client.answerCallbackQuery(queryId=callback.query_id, text="❌ Keyboard closed")

            else:
                await self.client.answerCallbackQuery(
                    queryId=callback.query_id, text=f"❓ Unknown action: {payload}", showAlert=True
                )

        except MaxBotError as e:
            logging.error(f"❌ Error handling callback: {e}")
            await self.client.answerCallbackQuery(
                queryId=callback.query_id, text="❌ Error occurred while processing your request", showAlert=True
            )

    async def handle_game_guess(self, user_id: int, callback, payload: str) -> None:
        """Handle game number guesses.

        Args:
            user_id: The user's ID
            callback: The callback query object
            payload: The callback payload containing the guess
        """
        import random

        # Generate random number (in a real bot, this would be stored per user)
        secret_number = random.randint(1, 5)

        # Extract guess from payload
        if payload == "guess_random":
            guess = random.randint(1, 5)
            guess_text = f"🎲 Random choice: {guess}"
        else:
            guess = int(payload.split("_")[1])
            guess_text = f"🔢 Your choice: {guess}"

        # Check if guess is correct
        if guess == secret_number:
            result_text = f"🎉 *Correct!*\n\n{guess_text}\n🎯 Secret number: {secret_number}\n\n🏆 You won!"
            alert_text = "🎉 Congratulations! You guessed correctly!"
        else:
            result_text = f"❌ *Wrong!*\n\n{guess_text}\n🎯 Secret number: {secret_number}\n\n💡 Try again!"
            alert_text = f"❌ Wrong! The number was {secret_number}"

        # Update message with result
        keyboard = self.client.createInlineKeyboard(
            [
                [{"type": ButtonType.CALLBACK, "text": "🎮 Play Again", "payload": "play_game"}],
                [{"type": ButtonType.CALLBACK, "text": "🔙 Back to Menu", "payload": "back_to_menu"}],
            ]
        )

        await self.client.editMessage(
            messageId=callback.message.body.mid,
            text=result_text,
            format=cast(TextFormat, TextFormat.MARKDOWN),
            inlineKeyboard=keyboard,
        )

        # Clear game state
        if user_id in self.user_states:
            del self.user_states[user_id]

        # Answer callback
        await self.client.answerCallbackQuery(queryId=callback.query_id, text=alert_text, showAlert=True)

    async def handle_reply_keyboard(self, update) -> None:
        """Handle messages from reply keyboard.

        Args:
            update: The update object containing the message
        """
        message = update.message
        chat_id = message.recipient.chat_id
        user_id = message.sender.user_id
        text = message.body.text or ""

        logging.info(f"⌨️ Reply keyboard input from user {user_id}: {text}")

        try:
            if text == "📍 Share Location":
                await self.client.sendLocation(
                    location={"latitude": 55.7558, "longitude": 37.6173, "title": "Moscow, Russia"}, chatId=chat_id
                )

                await self.client.sendMessage(chatId=chat_id, text="📍 Here's Moscow! Beautiful city! 🏛️")

            elif text == "📞 Share Contact":
                contact_text = (
                    "📞 *Contact Information*\n\n"
                    "🤖 Bot: Keyboard Bot Demo\n"
                    "📧 Email: bot@example.com\n"
                    "🌐 Website: https://max.ru\n"
                    "📱 Phone: +7 (999) 123-45-67"
                )

                await self.client.sendMessage(
                    chatId=chat_id, text=contact_text, format=cast(TextFormat, TextFormat.MARKDOWN)
                )

            elif text == "📸 Send Photo":
                # In a real bot, you would upload an actual photo
                await self.client.sendMessage(
                    chatId=chat_id,
                    text="📸 Photo feature coming soon!\n\n"
                    "This would typically upload and send a photo from your device or server.",
                )

            elif text == "📄 Send Document":
                # In a real bot, you would upload an actual document
                await self.client.sendMessage(
                    chatId=chat_id,
                    text="📄 Document feature coming soon!\n\n" "This would typically upload and send a document file.",
                )

            elif text == "❌ Remove Keyboard":
                await self.client.sendMessage(
                    chatId=chat_id,
                    text="⌨️ Keyboard removed!\n\n" "Type /keyboard to show it again.",
                    keyboard=self.client.removeKeyboard(),
                )

            else:
                await self.client.sendMessage(chatId=chat_id, text=f"⌨️ You pressed: {text}")

        except MaxBotError as e:
            logging.error(f"❌ Error handling reply keyboard: {e}")

    async def handle_commands(self, update) -> bool:
        """Handle bot commands.

        Args:
            update: The update object containing the message

        Returns:
            True if a command was handled, False otherwise
        """
        message = update.message
        chat_id = message.recipient.chat_id
        text = message.body.text or ""

        if not text.startswith("/"):
            return False

        command = text.lower().split()[0]
        user_name = message.sender.first_name or "User"

        logging.info(f"🎯 Command from {user_name}: {command}")

        try:
            if command == "/start":
                await self.send_welcome_message(chat_id, user_name)

            elif command == "/help":
                help_text = (
                    "🤖 *Keyboard Bot Help*\n\n"
                    "Available commands:\n"
                    "• `/start` - Show main menu with inline keyboard\n"
                    "• `/keyboard` - Show reply keyboard\n"
                    "• `/remove` - Remove reply keyboard\n"
                    "• `/help` - Show this help message\n\n"
                    "Features:\n"
                    "• 🔘 Inline keyboards with callbacks\n"
                    "• ⌨️ Reply keyboards for user interaction\n"
                    "• 🎮 Interactive mini-games\n"
                    "• ⚙️ Settings management\n"
                    "• 📊 Statistics display"
                )

                await self.client.sendMessage(
                    chatId=chat_id, text=help_text, format=cast(TextFormat, TextFormat.MARKDOWN)
                )

            elif command == "/keyboard":
                keyboard = self.client.createReplyKeyboard(self.create_reply_keyboard())

                await self.client.sendMessage(
                    chatId=chat_id, text="⌨️ Reply keyboard activated!\n\n" "Try the buttons below:", keyboard=keyboard
                )

            elif command == "/remove":
                await self.client.sendMessage(
                    chatId=chat_id, text="⌨️ Reply keyboard removed!", keyboard=self.client.removeKeyboard()
                )

            else:
                await self.client.sendMessage(
                    chatId=chat_id, text=f"❓ Unknown command: {command}\nType /help for available commands."
                )

            return True

        except MaxBotError as e:
            logging.error(f"❌ Error handling command: {e}")
            return False

    async def process_update(self, update) -> None:
        """Process a single update from the API.

        Args:
            update: The update object to process
        """
        try:
            if update.updateType == UpdateType.MESSAGE_CREATED:
                # First check for commands
                if not await self.handle_commands(update):
                    # Check if it's a reply keyboard interaction
                    message = update.message
                    if message.body.text:
                        await self.handle_reply_keyboard(update)
                    else:
                        # Handle other message types
                        chat_id = message.recipient.chat_id
                        await self.client.sendMessage(
                            chatId=chat_id, text="📨 Message received! Use /start to see the keyboard demo."
                        )

            elif update.updateType == UpdateType.MESSAGE_CALLBACK:
                await self.handle_callback_query(update)

            elif update.updateType == UpdateType.BOT_ADDED_TO_CHAT:
                chat_id = update.chat.chat_id
                user_name = "Chat Members"
                await self.send_welcome_message(chat_id, user_name)

            elif update.updateType == UpdateType.BOT_STARTED:
                chat_id = update.user.user_id
                user_name = update.user.first_name or "User"
                await self.send_welcome_message(chat_id, user_name)

            else:
                logging.debug(f"🔄 Unhandled update type: {update.updateType}")

        except Exception as e:
            logging.error(f"❌ Error processing update: {e}")


async def run_bot() -> None:
    """Main bot function that handles the bot lifecycle."""
    token = get_token()

    logging.info("🚀 Starting Keyboard Bot...")

    try:
        # Initialize the client
        async with MaxBotClient(token) as client:
            # Create bot instance
            bot = KeyboardBot(client)

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
            logging.info("📱 Send /start to your bot to see the keyboard demo!")
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
                    await bot.process_update(update)

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
