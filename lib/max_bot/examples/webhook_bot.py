#!/usr/bin/env python3
"""
Webhook Bot Example

This example demonstrates webhook-based update handling in Max Bot.
It shows how to set up webhooks, handle incoming updates via HTTP endpoints,
and integrate with web frameworks like FastAPI.

Features demonstrated:
- Webhook setup and management
- HTTP endpoint handling
- Update processing via webhooks
- Webhook security and validation
- Integration with FastAPI
- Error handling for webhook operations

Run this example:
    python webhook_bot.py

Requirements:
    - Set MAX_BOT_TOKEN environment variable with your bot access token
    - Set WEBHOOK_URL environment variable with your webhook URL
    - Install FastAPI: pip install fastapi uvicorn

Example webhook URL format:
    export WEBHOOK_URL="https://your-domain.com/webhook"
    # For local testing with ngrok:
    export WEBHOOK_URL="https://your-ngrok-id.ngrok.io/webhook"
"""

import asyncio
import logging
import os
import sys
from typing import Dict, List, Optional, cast

# Add the parent directory to the path so we can import lib.max_bot
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from lib.max_bot import AuthenticationError, MaxBotClient, MaxBotError, UpdateType  # noqa: E402
from lib.max_bot.models import TextFormat  # noqa: E402

# FastAPI imports (optional - only needed if running webhook server)
try:
    import uvicorn  # type: ignore
    from fastapi import FastAPI, HTTPException  # type: ignore
    from fastapi.responses import JSONResponse  # type: ignore
    from pydantic import BaseModel  # type: ignore

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

    # Create dummy classes to avoid NameError
    class FastAPI:
        def __init__(self, **kwargs):
            pass

    class HTTPException(Exception):
        pass

    class JSONResponse:
        def __init__(self, **kwargs):
            pass

    class BaseModel:
        pass

    # Create dummy uvicorn module
    class uvicorn:
        @staticmethod
        def run(*args, **kwargs):
            pass

    print("⚠️ FastAPI not available. Install with: pip install fastapi uvicorn")


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


def get_webhook_url() -> str:
    """Get the webhook URL from environment variables."""
    webhook_url = os.getenv("WEBHOOK_URL")
    if not webhook_url:
        print("❌ Error: WEBHOOK_URL environment variable is not set!")
        print("Please set your webhook URL:")
        print("export WEBHOOK_URL='https://your-domain.com/webhook'")
        print("For local testing with ngrok:")
        print("export WEBHOOK_URL='https://your-ngrok-id.ngrok.io/webhook'")
        sys.exit(1)
    return webhook_url


class WebhookBot:
    """A bot that demonstrates webhook-based update handling."""

    def __init__(self, client: MaxBotClient):
        """Initialize the webhook bot.

        Args:
            client: The MaxBotClient instance
        """
        self.client = client
        self.webhook_url = get_webhook_url()
        self.update_count = 0
        self.processed_updates: Dict[str, Dict] = {}

    def create_main_keyboard(self) -> List[List[Dict]]:
        """Create the main inline keyboard.

        Returns:
            List of keyboard rows with buttons
        """
        return [
            [
                {"type": "callback", "text": "📊 Webhook Info", "payload": "webhook_info"},
                {"type": "callback", "text": "📈 Statistics", "payload": "stats"},
            ],
            [
                {"type": "callback", "text": "🔄 Test Webhook", "payload": "test_webhook"},
                {"type": "callback", "text": "❌ Close", "payload": "close"},
            ],
        ]

    async def send_welcome_message(self, chat_id: int, user_name: str) -> None:
        """Send a welcome message explaining webhook functionality.

        Args:
            chat_id: The chat ID to send the message to
            user_name: The user's name for personalization
        """
        welcome_text = (
            f"👋 Hello, {user_name}!\n\n"
            "🌐 *Webhook Bot Demo*\n\n"
            "This bot demonstrates webhook-based update handling:\n\n"
            "🔗 **Webhook Features:**\n"
            "• Real-time update delivery\n"
            "• HTTP endpoint integration\n"
            "• Webhook management\n"
            "• Update tracking\n"
            "• Error handling\n\n"
            "📊 **Current Webhook:**\n"
            f"URL: `{self.webhook_url}`\n\n"
            "Choose an option below to learn more! 👇"
        )

        keyboard = self.client.createInlineKeyboard(self.create_main_keyboard())

        await self.client.sendMessage(
            chatId=chat_id, text=welcome_text, format=cast(TextFormat, TextFormat.MARKDOWN), inlineKeyboard=keyboard
        )

    async def setup_webhook(self) -> bool:
        """Set up the webhook for the bot.

        Returns:
            True if webhook was set up successfully
        """
        try:
            logging.info(f"🔗 Setting up webhook: {self.webhook_url}")

            # Set webhook with all update types
            await self.client.setWebhook(
                url=self.webhook_url,
                types=[
                    UpdateType.MESSAGE_CREATED,
                    UpdateType.MESSAGE_CALLBACK,
                    UpdateType.BOT_ADDED_TO_CHAT,
                    UpdateType.BOT_STARTED,
                ],
            )

            # Verify webhook setup
            webhook_info = await self.client.getWebhookInfo()

            logging.info("✅ Webhook set up successfully!")
            logging.info(f"📡 Webhook URL: {webhook_info.get('url', '')}")
            logging.info(f"📊 Events: {webhook_info.get('events', [])}")

            return True

        except MaxBotError as e:
            logging.error(f"❌ Error setting up webhook: {e}")
            return False
        except Exception as e:
            logging.error(f"❌ Unexpected error setting up webhook: {e}")
            return False

    async def remove_webhook(self) -> bool:
        """Remove the webhook for the bot.

        Returns:
            True if webhook was removed successfully
        """
        try:
            logging.info("🗑️ Removing webhook...")

            await self.client.deleteWebhook(self.webhook_url)

            logging.info("✅ Webhook removed successfully!")
            return True

        except MaxBotError as e:
            logging.error(f"❌ Error removing webhook: {e}")
            return False
        except Exception as e:
            logging.error(f"❌ Unexpected error removing webhook: {e}")
            return False

    async def process_webhook_update(self, update_data: Dict) -> Dict:
        """Process an update received via webhook.

        Args:
            update_data: The update data from webhook

        Returns:
            Response data for the webhook
        """
        try:
            self.update_count += 1

            # Convert dict to Update object (simplified for demo)
            # In a real implementation, you would use Update.from_dict()
            update_type = update_data.get("updateType", "unknown")

            logging.info(f"📨 Webhook update #{self.update_count}: {update_type}")

            # Store update for tracking
            update_id = str(self.update_count)
            self.processed_updates[update_id] = {
                "update_type": update_type,
                "timestamp": asyncio.get_event_loop().time(),
                "processed": True,
            }

            # Process different update types
            if update_type == UpdateType.MESSAGE_CREATED:
                await self.handle_message_update(update_data)
            elif update_type == UpdateType.MESSAGE_CALLBACK:
                await self.handle_callback_update(update_data)
            elif update_type == UpdateType.BOT_ADDED_TO_CHAT:
                await self.handle_bot_added_update(update_data)
            elif update_type == UpdateType.BOT_STARTED:
                await self.handle_bot_started_update(update_data)
            else:
                logging.debug(f"🔄 Unhandled update type: {update_type}")

            return {"status": "ok", "update_id": update_id}

        except Exception as e:
            logging.error(f"❌ Error processing webhook update: {e}")
            return {"status": "error", "message": str(e)}

    async def handle_message_update(self, update_data: Dict) -> None:
        """Handle message updates from webhook.

        Args:
            update_data: The message update data
        """
        try:
            # Extract message data (simplified)
            message_data = update_data.get("message", {})
            recipient_data = message_data.get("recipient", {})
            sender_data = message_data.get("sender", {})
            body_data = message_data.get("body", {})

            chat_id = recipient_data.get("chat_id")
            user_name = sender_data.get("first_name", "User")
            text = body_data.get("text", "")

            if not chat_id:
                logging.warning("⚠️ No chat_id in message update")
                return

            logging.info(f"💬 Message from {user_name} in chat {chat_id}: {text}")

            # Handle commands
            if text and text.startswith("/"):
                await self.handle_command(chat_id, user_name, text)
            elif text:
                await self.handle_text_message(chat_id, user_name, text)
            else:
                await self.client.sendMessage(
                    chatId=chat_id, text="📨 Message received! Use /help for available commands."
                )

        except Exception as e:
            logging.error(f"❌ Error handling message update: {e}")

    async def handle_callback_update(self, update_data: Dict) -> None:
        """Handle callback updates from webhook.

        Args:
            update_data: The callback update data
        """
        try:
            # Extract callback data (simplified)
            callback_data = update_data.get("callbackQuery", {})
            message_data = callback_data.get("message", {})
            recipient_data = message_data.get("recipient", {})
            sender_data = callback_data.get("sender", {})

            chat_id = recipient_data.get("chat_id")
            user_name = sender_data.get("first_name", "User")
            payload = callback_data.get("payload", "")
            query_id = callback_data.get("queryId", "")

            if not chat_id or not query_id:
                logging.warning("⚠️ Missing chat_id or query_id in callback update")
                return

            logging.info(f"🔘 Callback from {user_name}: {payload}")

            # Handle different callback actions
            if payload == "webhook_info":
                await self.client.answerCallbackQuery(queryId=query_id, text="🔗 Webhook info loading...")

                info_text = (
                    f"🌐 *Webhook Information*\n\n"
                    f"📡 **URL:** `{self.webhook_url}`\n"
                    f"📊 **Updates Processed:** {self.update_count}\n"
                    f"⏰ **Status:** Active\n\n"
                    f"✅ Webhook is working perfectly!"
                )

                await self.client.sendMessage(
                    chatId=chat_id, text=info_text, format=cast(TextFormat, TextFormat.MARKDOWN)
                )

            elif payload == "stats":
                await self.client.answerCallbackQuery(queryId=query_id, text="📈 Loading statistics...")

                stats_text = (
                    f"📊 *Webhook Statistics*\n\n"
                    f"📈 **Total Updates:** {self.update_count}\n"
                    f"📝 **Processed Updates:** {len(self.processed_updates)}\n"
                    f"🕒 **Uptime:** {asyncio.get_event_loop().time():.0f}s\n\n"
                    f"🔗 **Webhook URL:** `{self.webhook_url}`\n\n"
                    f"📊 Performance: Excellent!"
                )

                await self.client.sendMessage(
                    chatId=chat_id, text=stats_text, format=cast(TextFormat, TextFormat.MARKDOWN)
                )

            elif payload == "test_webhook":
                await self.client.answerCallbackQuery(queryId=query_id, text="🔄 Testing webhook...", showAlert=True)

                await self.client.sendMessage(
                    chatId=chat_id,
                    text="🔄 *Webhook Test*\n\n"
                    "✅ Webhook is working!\n"
                    f"📡 Updates are being received at: `{self.webhook_url}`\n\n"
                    "This message was delivered via webhook processing!",
                    format=cast(TextFormat, TextFormat.MARKDOWN),
                )

            elif payload == "close":
                await self.client.editMessage(
                    messageId=message_data.get("body", {}).get("mid", ""),
                    text="👋 Webhook demo closed!\n\nType /start to show it again.",
                )
                await self.client.answerCallbackQuery(queryId=query_id, text="❌ Demo closed")

            else:
                await self.client.answerCallbackQuery(
                    queryId=query_id, text=f"❓ Unknown action: {payload}", showAlert=True
                )

        except Exception as e:
            logging.error(f"❌ Error handling callback update: {e}")

    async def handle_bot_added_update(self, update_data: Dict) -> None:
        """Handle bot added to chat updates from webhook.

        Args:
            update_data: The bot added update data
        """
        try:
            chat_data = update_data.get("chat", {})
            chat_id = chat_data.get("chat_id")
            chat_title = chat_data.get("title", "Chat")

            if not chat_id:
                logging.warning("⚠️ No chat_id in bot added update")
                return

            logging.info(f"🤖 Bot added to chat: {chat_title}")

            await self.client.sendMessage(
                chatId=chat_id,
                text="🤖 *Webhook Bot Added!*\n\n"
                "Hello everyone! 👋\n\n"
                "I'm a webhook-powered bot demonstrating real-time update processing.\n\n"
                "Type /start to see what I can do!",
                format=cast(TextFormat, TextFormat.MARKDOWN),
            )

        except Exception as e:
            logging.error(f"❌ Error handling bot added update: {e}")

    async def handle_bot_started_update(self, update_data: Dict) -> None:
        """Handle bot started updates from webhook.

        Args:
            update_data: The bot started update data
        """
        try:
            user_data = update_data.get("user", {})
            chat_id = user_data.get("user_id")
            user_name = user_data.get("first_name", "User")

            if not chat_id:
                logging.warning("⚠️ No chat_id in bot started update")
                return

            logging.info(f"🤖 Bot started by: {user_name}")

            await self.send_welcome_message(chat_id, user_name)

        except Exception as e:
            logging.error(f"❌ Error handling bot started update: {e}")

    async def handle_command(self, chat_id: int, user_name: str, command: str) -> None:
        """Handle bot commands.

        Args:
            chat_id: The chat ID to send messages to
            user_name: The user's name
            command: The command text
        """
        try:
            if command.lower() == "/start":
                await self.send_welcome_message(chat_id, user_name)

            elif command.lower() == "/help":
                help_text = (
                    "🤖 *Webhook Bot Help*\n\n"
                    "Available commands:\n"
                    "• `/start` - Show webhook demo\n"
                    "• `/help` - Show this help message\n"
                    "• `/webhook` - Show webhook info\n"
                    "• `/stats` - Show statistics\n\n"
                    "Webhook Features:\n"
                    "• 🌐 Real-time update delivery\n"
                    "• 📡 HTTP endpoint integration\n"
                    "• 📊 Update tracking\n"
                    "• ⚡ Fast processing"
                )

                await self.client.sendMessage(
                    chatId=chat_id, text=help_text, format=cast(TextFormat, TextFormat.MARKDOWN)
                )

            elif command.lower() == "/webhook":
                webhook_info = await self.client.getWebhookInfo()

                info_text = (
                    f"🌐 *Webhook Information*\n\n"
                    f"📡 **URL:** `{webhook_info.get('url', '')}`\n"
                    f"📊 **Events:** {', '.join(webhook_info.get('events', []))}\n"
                    f"📈 **Updates Processed:** {self.update_count}\n\n"
                    f"✅ Webhook is active and working!"
                )

                await self.client.sendMessage(
                    chatId=chat_id, text=info_text, format=cast(TextFormat, TextFormat.MARKDOWN)
                )

            elif command.lower() == "/stats":
                stats_text = (
                    f"📊 *Webhook Statistics*\n\n"
                    f"📈 **Total Updates:** {self.update_count}\n"
                    f"📝 **Processed:** {len(self.processed_updates)}\n"
                    f"🕒 **Uptime:** {asyncio.get_event_loop().time():.0f}s\n\n"
                    f"🔗 **Webhook URL:** `{self.webhook_url}`"
                )

                await self.client.sendMessage(
                    chatId=chat_id, text=stats_text, format=cast(TextFormat, TextFormat.MARKDOWN)
                )

            else:
                await self.client.sendMessage(
                    chatId=chat_id, text=f"❓ Unknown command: {command}\nType /help for available commands."
                )

        except Exception as e:
            logging.error(f"❌ Error handling command: {e}")

    async def handle_text_message(self, chat_id: int, user_name: str, text: str) -> None:
        """Handle regular text messages.

        Args:
            chat_id: The chat ID to send messages to
            user_name: The user's name
            text: The message text
        """
        try:
            await self.client.sendMessage(
                chatId=chat_id,
                text=f"📨 Message received via webhook: {text}\n\n" f"Type /help for available commands.",
            )

        except Exception as e:
            logging.error(f"❌ Error handling text message: {e}")


# FastAPI application (only if FastAPI is available)
if FASTAPI_AVAILABLE:
    app = FastAPI(title="Max Bot Webhook Server")
    bot_instance: Optional[WebhookBot] = None

    class WebhookUpdate(BaseModel):
        """Pydantic model for webhook updates."""

        updateType: str
        message: Optional[Dict] = None
        callbackQuery: Optional[Dict] = None
        chat: Optional[Dict] = None
        user: Optional[Dict] = None

    @app.on_event("startup")  # type: ignore[attr-defined]
    async def startup_event():
        """Initialize the bot on application startup."""
        global bot_instance

        token = get_token()
        client = MaxBotClient(token)
        bot_instance = WebhookBot(client)

        # Set up webhook
        if await bot_instance.setup_webhook():
            logging.info("✅ Webhook bot started successfully!")
        else:
            logging.error("❌ Failed to set up webhook!")

    @app.on_event("shutdown")  # type: ignore[attr-defined]
    async def shutdown_event():
        """Clean up on application shutdown."""

        if bot_instance:
            await bot_instance.remove_webhook()
            await bot_instance.client.aclose()
            logging.info("👋 Webhook bot shut down gracefully!")

    @app.post("/webhook")  # type: ignore[attr-defined]
    async def webhook_endpoint(update: WebhookUpdate):
        """Handle incoming webhook updates."""

        if not bot_instance:
            raise HTTPException(status_code=500, detail="Bot not initialized")  # type: ignore[arg-type]

        try:
            # Process the update
            result = await bot_instance.process_webhook_update(update.__dict__)

            if result.get("status") == "ok":
                return JSONResponse(content=result)
            else:
                raise HTTPException(status_code=400, detail=result)  # type: ignore[arg-type]

        except Exception as e:
            logging.error(f"❌ Error in webhook endpoint: {e}")
            raise HTTPException(status_code=500, detail=str(e))  # type: ignore[arg-type]

    @app.get("/health")  # type: ignore[attr-defined]
    async def health_check():
        """Health check endpoint."""

        if bot_instance:
            return {
                "status": "healthy",
                "webhook_url": bot_instance.webhook_url,
                "updates_processed": bot_instance.update_count,
            }
        else:
            return {"status": "unhealthy", "message": "Bot not initialized"}

    @app.get("/")  # type: ignore[attr-defined]
    async def root():
        """Root endpoint with information."""
        return {
            "message": "Max Bot Webhook Server",
            "webhook_endpoint": "/webhook",
            "health_endpoint": "/health",
            "docs": "/docs",
        }


async def run_webhook_demo() -> None:
    """Run the webhook demo without FastAPI server."""
    token = get_token()

    logging.info("🚀 Starting Webhook Bot Demo...")

    try:
        # Initialize the client
        async with MaxBotClient(token) as client:
            # Create bot instance
            bot = WebhookBot(client)

            # Get bot information
            bot_info = await client.getMyInfo()
            logging.info(f"✅ Bot started successfully: {bot_info.first_name}")
            logging.info(f"🆔 Bot ID: {bot_info.user_id}")

            # Set up webhook
            if await bot.setup_webhook():
                logging.info("✅ Webhook is set up and ready!")
                logging.info(f"📡 Webhook URL: {bot.webhook_url}")
                logging.info("🌐 Make sure your webhook endpoint is accessible!")
                logging.info("⏹️ Press Ctrl+C to stop and remove webhook")

                # Keep the bot running
                try:
                    while True:
                        await asyncio.sleep(10)
                        # Periodically check webhook status
                        webhook_info = await client.getWebhookInfo()
                        logging.debug(f"📊 Webhook status: {webhook_info.get('url', '')}")

                except KeyboardInterrupt:
                    logging.info("⏹️ Stopping webhook bot...")
                    await bot.remove_webhook()
                    logging.info("✅ Webhook removed successfully!")
            else:
                logging.error("❌ Failed to set up webhook!")

    except AuthenticationError:
        logging.error("❌ Authentication failed! Please check your bot token.")
        sys.exit(1)
    except Exception as e:
        logging.error(f"❌ Fatal error: {e}")
        sys.exit(1)


def run_webhook_server() -> None:
    """Run the FastAPI webhook server."""
    if not FASTAPI_AVAILABLE:
        print("❌ FastAPI is not available. Install with: pip install fastapi uvicorn")
        sys.exit(1)

    print("🌐 Starting FastAPI webhook server...")
    print("📡 Webhook endpoint: /webhook")
    print("🏥 Health endpoint: /health")
    print("📚 API docs: /docs")
    print("⏹️ Press Ctrl+C to stop the server")

    # Run the server
    uvicorn.run(app, host="0.0.0.0", port=8000)


def main() -> None:
    """Entry point for the webhook bot."""
    setup_logging()

    # Check if we should run the server or just demo
    if len(sys.argv) > 1 and sys.argv[1] == "server":
        run_webhook_server()
    else:
        try:
            asyncio.run(run_webhook_demo())
        except KeyboardInterrupt:
            logging.info("👋 Goodbye!")
        except Exception as e:
            logging.error(f"❌ Fatal error in main: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
