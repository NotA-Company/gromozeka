#!/usr/bin/env python3
"""
Conversation Bot Example

This example demonstrates state management and multi-step conversations in Max Bot.
It shows how to build conversational bots with finite state machines, context management,
and complex interaction flows.

Features demonstrated:
- State management with finite state machines
- Multi-step conversations
- Context data storage
- State transitions
- User session management
- Conversation flow control
- Data persistence across messages

Run this example:
    python conversation_bot.py

Requirements:
    - Set MAX_BOT_TOKEN environment variable with your bot access token
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
from lib.max_bot.state import MemoryStateStorage, State, StateManager, create_fsm  # noqa: E402


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


class ConversationBot:
    """A bot that demonstrates conversational flows with state management."""

    def __init__(self, client: MaxBotClient):
        """Initialize the conversation bot.

        Args:
            client: The MaxBotClient instance
        """
        self.client = client
        self.state_manager = self.setup_state_manager()

    def setup_state_manager(self) -> StateManager:
        """Set up the state manager with states and transitions.

        Returns:
            Configured StateManager instance
        """
        # Create states
        idle_state = State("idle")
        welcome_state = State("welcome")
        registration_name_state = State("registration_name")
        registration_email_state = State("registration_email")
        registration_age_state = State("registration_age")
        survey_topic_state = State("survey_topic")
        survey_rating_state = State("survey_rating")
        survey_feedback_state = State("survey_feedback")
        support_issue_state = State("support_issue")
        support_details_state = State("support_details")

        # Define transitions
        transitions = [
            # Welcome flow
            ("idle", "start", "welcome"),
            ("welcome", "register", "registration_name"),
            ("welcome", "survey", "survey_topic"),
            ("welcome", "support", "support_issue"),
            ("welcome", "back", "idle"),
            # Registration flow
            ("registration_name", "name_provided", "registration_email"),
            ("registration_email", "email_provided", "registration_age"),
            ("registration_age", "age_provided", "idle"),
            ("registration_name", "cancel", "welcome"),
            ("registration_email", "cancel", "welcome"),
            ("registration_age", "cancel", "welcome"),
            # Survey flow
            ("survey_topic", "topic_selected", "survey_rating"),
            ("survey_rating", "rating_provided", "survey_feedback"),
            ("survey_feedback", "feedback_provided", "idle"),
            ("survey_topic", "cancel", "welcome"),
            ("survey_rating", "cancel", "welcome"),
            ("survey_feedback", "cancel", "welcome"),
            # Support flow
            ("support_issue", "issue_selected", "support_details"),
            ("support_details", "details_provided", "idle"),
            ("support_issue", "cancel", "welcome"),
            ("support_details", "cancel", "welcome"),
        ]

        # Create finite state machine
        states = create_fsm(
            [
                idle_state,
                welcome_state,
                registration_name_state,
                registration_email_state,
                registration_age_state,
                survey_topic_state,
                survey_rating_state,
                survey_feedback_state,
                support_issue_state,
                support_details_state,
            ],
            transitions,
        )

        # Create state manager
        state_manager = StateManager(MemoryStateStorage())

        # Register states
        for state in states.values():
            state_manager.add_state(state)

        # Set default state
        state_manager.set_default_state(idle_state)

        return state_manager

    def create_welcome_keyboard(self) -> List[List[Dict]]:
        """Create the welcome keyboard with main options.

        Returns:
            List of keyboard rows with buttons
        """
        return [
            [
                {"type": "callback", "text": "📝 User Registration", "payload": "register"},
                {"type": "callback", "text": "📊 Take Survey", "payload": "survey"},
            ],
            [
                {"type": "callback", "text": "💬 Customer Support", "payload": "support"},
                {"type": "callback", "text": "🔙 Back to Idle", "payload": "back"},
            ],
        ]

    def create_survey_topics_keyboard(self) -> List[List[Dict]]:
        """Create keyboard for survey topic selection.

        Returns:
            List of keyboard rows with buttons
        """
        return [
            [
                {"type": "callback", "text": "🤖 Bot Features", "payload": "topic_bot_features"},
                {"type": "callback", "text": "📱 User Experience", "payload": "topic_ux"},
            ],
            [
                {"type": "callback", "text": "⚡ Performance", "payload": "topic_performance"},
                {"type": "callback", "text": "🛡️ Security", "payload": "topic_security"},
            ],
            [{"type": "callback", "text": "❌ Cancel", "payload": "cancel"}],
        ]

    def create_rating_keyboard(self) -> List[List[Dict]]:
        """Create keyboard for rating selection.

        Returns:
            List of keyboard rows with buttons
        """
        return [
            [
                {"type": "callback", "text": "⭐", "payload": "rating_1"},
                {"type": "callback", "text": "⭐⭐", "payload": "rating_2"},
                {"type": "callback", "text": "⭐⭐⭐", "payload": "rating_3"},
            ],
            [
                {"type": "callback", "text": "⭐⭐⭐⭐", "payload": "rating_4"},
                {"type": "callback", "text": "⭐⭐⭐⭐⭐", "payload": "rating_5"},
            ],
            [{"type": "callback", "text": "❌ Cancel", "payload": "cancel"}],
        ]

    def create_support_issues_keyboard(self) -> List[List[Dict]]:
        """Create keyboard for support issue selection.

        Returns:
            List of keyboard rows with buttons
        """
        return [
            [
                {"type": "callback", "text": "🔐 Login Issues", "payload": "issue_login"},
                {"type": "callback", "text": "💳 Payment Problems", "payload": "issue_payment"},
            ],
            [
                {"type": "callback", "text": "🐛 Bug Report", "payload": "issue_bug"},
                {"type": "callback", "text": "💡 Feature Request", "payload": "issue_feature"},
            ],
            [
                {"type": "callback", "text": "❓ Other", "payload": "issue_other"},
                {"type": "callback", "text": "❌ Cancel", "payload": "cancel"},
            ],
        ]

    async def send_welcome_message(self, chat_id: int, user_id: int, user_name: str) -> None:
        """Send welcome message and create user context.

        Args:
            chat_id: The chat ID to send the message to
            user_id: The user's ID
            user_name: The user's name for personalization
        """
        welcome_text = (
            f"👋 Hello, {user_name}!\n\n"
            "🤖 *Conversation Bot Demo*\n\n"
            "This bot demonstrates stateful conversations with context management.\n\n"
            "Choose an option below to start a conversation flow:\n\n"
            "📝 *User Registration* - Multi-step registration process\n"
            "📊 *Survey* - Interactive survey with ratings\n"
            "💬 *Customer Support* - Issue reporting system\n\n"
            "Each flow maintains state and context across multiple messages!"
        )

        keyboard = self.client.createInlineKeyboard(self.create_welcome_keyboard())

        await self.client.sendMessage(
            chatId=chat_id, text=welcome_text, format=cast(TextFormat, TextFormat.MARKDOWN), inlineKeyboard=keyboard
        )

        # Create user context in welcome state
        await self.state_manager.create_context(
            userId=user_id,
            chatId=chat_id,
            initialState=self.state_manager.get_state("welcome"),
            data={"user_name": user_name, "started_at": asyncio.get_event_loop().time()},
        )

    async def handle_registration_flow(self, user_id: int, chat_id: int, message_text: str) -> None:
        """Handle the user registration flow.

        Args:
            user_id: The user's ID
            chat_id: The chat ID
            message_text: The message text from user
        """
        context = await self.state_manager.get_context(user_id, chat_id)
        if not context:
            return

        current_state = context.currentState.name if context.currentState else "unknown"

        if current_state == "registration_name":
            # Store name and move to email
            await self.state_manager.set_state_data("name", message_text, user_id, chat_id)
            await self.state_manager.transition_state("name_provided", user_id, chat_id)

            await self.client.sendMessage(
                chatId=chat_id, text=f"Nice to meet you, {message_text}! 📝\n\n" "Now, please enter your email address:"
            )

        elif current_state == "registration_email":
            # Validate email and move to age
            if "@" in message_text and "." in message_text:
                await self.state_manager.set_state_data("email", message_text, user_id, chat_id)
                await self.state_manager.transition_state("email_provided", user_id, chat_id)

                await self.client.sendMessage(
                    chatId=chat_id, text="Great! 📧\n\n" "Finally, please enter your age (numbers only):"
                )
            else:
                await self.client.sendMessage(
                    chatId=chat_id, text="❌ Invalid email format. Please enter a valid email address:"
                )

        elif current_state == "registration_age":
            # Validate age and complete registration
            try:
                age = int(message_text)
                if 0 < age < 150:
                    await self.state_manager.set_state_data("age", age, user_id, chat_id)

                    # Get all registration data
                    name = await self.state_manager.get_state_data("name", user_id=user_id, chat_id=chat_id)
                    email = await self.state_manager.get_state_data("email", user_id=user_id, chat_id=chat_id)

                    # Complete registration
                    await self.state_manager.transition_state("age_provided", user_id, chat_id)

                    completion_text = (
                        "🎉 *Registration Complete!*\n\n"
                        f"📝 **Name:** {name}\n"
                        f"📧 **Email:** {email}\n"
                        f"🎂 **Age:** {age}\n\n"
                        "Thank you for registering! Your information has been saved.\n\n"
                        "Type /start to begin a new conversation."
                    )

                    await self.client.sendMessage(
                        chatId=chat_id, text=completion_text, format=cast(TextFormat, TextFormat.MARKDOWN)
                    )
                else:
                    await self.client.sendMessage(chatId=chat_id, text="❌ Please enter a valid age (1-149):")
            except ValueError:
                await self.client.sendMessage(chatId=chat_id, text="❌ Please enter a valid number for your age:")

    async def handle_survey_flow(
        self, user_id: int, chat_id: int, message_text: str, callback_payload: Optional[str] = None
    ) -> None:
        """Handle the survey flow.

        Args:
            user_id: The user's ID
            chat_id: The chat ID
            message_text: The message text from user
            callback_payload: Optional callback payload for button interactions
        """
        context = await self.state_manager.get_context(user_id, chat_id)
        if not context:
            return

        current_state = context.currentState.name if context.currentState else "unknown"

        if current_state == "survey_topic":
            if callback_payload and callback_payload.startswith("topic_"):
                # Store topic and move to rating
                topic = callback_payload.replace("topic_", "").replace("_", " ").title()
                await self.state_manager.set_state_data("topic", topic, user_id, chat_id)
                await self.state_manager.transition_state("topic_selected", user_id, chat_id)

                rating_text = (
                    f"📊 *Survey: {topic}*\n\n"
                    "How would you rate your experience with this aspect?\n\n"
                    "Please select a rating:"
                )

                keyboard = self.client.createInlineKeyboard(self.create_rating_keyboard())

                await self.client.sendMessage(
                    chatId=chat_id,
                    text=rating_text,
                    format=cast(TextFormat, TextFormat.MARKDOWN),
                    inlineKeyboard=keyboard,
                )

        elif current_state == "survey_rating":
            if callback_payload and callback_payload.startswith("rating_"):
                # Store rating and move to feedback
                rating = int(callback_payload.split("_")[1])
                stars = "⭐" * rating
                await self.state_manager.set_state_data("rating", rating, user_id, chat_id)
                await self.state_manager.transition_state("rating_provided", user_id, chat_id)

                await self.client.sendMessage(
                    chatId=chat_id,
                    text=f"Thank you for rating: {stars}\n\n" f"Please provide any additional feedback or comments:",
                )

        elif current_state == "survey_feedback":
            # Store feedback and complete survey
            await self.state_manager.set_state_data("feedback", message_text, user_id, chat_id)
            await self.state_manager.transition_state("feedback_provided", user_id, chat_id)

            # Get all survey data
            topic = await self.state_manager.get_state_data("topic", user_id=user_id, chat_id=chat_id)
            rating = await self.state_manager.get_state_data("rating", user_id=user_id, chat_id=chat_id)
            stars = "⭐" * rating

            completion_text = (
                "📊 *Survey Complete!*\n\n"
                f"📋 **Topic:** {topic}\n"
                f"⭐ **Rating:** {stars} ({rating}/5)\n"
                f"💬 **Feedback:** {message_text}\n\n"
                "Thank you for your feedback! It helps us improve our service.\n\n"
                "Type /start to begin a new conversation."
            )

            await self.client.sendMessage(
                chatId=chat_id, text=completion_text, format=cast(TextFormat, TextFormat.MARKDOWN)
            )

    async def handle_support_flow(
        self, user_id: int, chat_id: int, message_text: str, callback_payload: Optional[str] = None
    ) -> None:
        """Handle the customer support flow.

        Args:
            user_id: The user's ID
            chat_id: The chat ID
            message_text: The message text from user
            callback_payload: Optional callback payload for button interactions
        """
        context = await self.state_manager.get_context(user_id, chat_id)
        if not context:
            return

        current_state = context.currentState.name if context.currentState else "unknown"

        if current_state == "support_issue":
            if callback_payload and callback_payload.startswith("issue_"):
                # Store issue and move to details
                issue = callback_payload.replace("issue_", "").replace("_", " ").title()
                await self.state_manager.set_state_data("issue_type", issue, user_id, chat_id)
                await self.state_manager.transition_state("issue_selected", user_id, chat_id)

                await self.client.sendMessage(
                    chatId=chat_id,
                    text=f"📝 *Support: {issue}*\n\n"
                    "Please describe your issue in detail:\n"
                    "• What happened?\n"
                    "• When did it occur?\n"
                    "• What steps have you tried?\n\n"
                    "The more details you provide, the better we can help you!",
                )

        elif current_state == "support_details":
            # Store details and complete support request
            await self.state_manager.set_state_data("issue_details", message_text, user_id, chat_id)
            await self.state_manager.transition_state("details_provided", user_id, chat_id)

            # Get all support data
            issue_type = await self.state_manager.get_state_data("issue_type", user_id=user_id, chat_id=chat_id)
            user_name = await self.state_manager.get_state_data("user_name", user_id=user_id, chat_id=chat_id)

            # Generate ticket number
            import random

            ticket_number = f"TKT-{random.randint(10000, 99999)}"

            completion_text = (
                "🎫 *Support Request Created!*\n\n"
                f"🎫 **Ticket Number:** {ticket_number}\n"
                f"👤 **Name:** {user_name}\n"
                f"📋 **Issue Type:** {issue_type}\n"
                f"📝 **Description:** {message_text}\n\n"
                "Our support team will review your request and respond within 24 hours.\n"
                "You'll receive updates via this chat.\n\n"
                "Type /start to begin a new conversation."
            )

            await self.client.sendMessage(
                chatId=chat_id, text=completion_text, format=cast(TextFormat, TextFormat.MARKDOWN)
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
            # Get user context
            context = await self.state_manager.get_context(user_id, chat_id)
            if not context:
                await self.client.answerCallbackQuery(
                    queryId=callback.query_id, text="❌ No active conversation. Type /start to begin.", showAlert=True
                )
                return

            current_state = context.currentState.name if context.currentState else "unknown"

            # Handle welcome state callbacks
            if current_state == "welcome":
                if payload == "register":
                    await self.client.answerCallbackQuery(queryId=callback.query_id, text="📝 Starting registration...")
                    await self.state_manager.transition_state("register", user_id, chat_id)
                    await self.client.sendMessage(
                        chatId=chat_id,
                        text="📝 *User Registration*\n\n" "Let's get you registered! Please enter your full name:",
                    )

                elif payload == "survey":
                    await self.client.answerCallbackQuery(queryId=callback.query_id, text="📊 Starting survey...")
                    await self.state_manager.transition_state("survey", user_id, chat_id)

                    keyboard = self.client.createInlineKeyboard(self.create_survey_topics_keyboard())
                    await self.client.sendMessage(
                        chatId=chat_id,
                        text="📊 *Survey*\n\n" "Please select a topic you'd like to provide feedback on:",
                        format=cast(TextFormat, TextFormat.MARKDOWN),
                        inlineKeyboard=keyboard,
                    )

                elif payload == "support":
                    await self.client.answerCallbackQuery(queryId=callback.query_id, text="💬 Opening support...")
                    await self.state_manager.transition_state("support", user_id, chat_id)

                    keyboard = self.client.createInlineKeyboard(self.create_support_issues_keyboard())
                    await self.client.sendMessage(
                        chatId=chat_id,
                        text="💬 *Customer Support*\n\n" "Please select the type of issue you're experiencing:",
                        format=cast(TextFormat, TextFormat.MARKDOWN),
                        inlineKeyboard=keyboard,
                    )

                elif payload == "back":
                    await self.client.answerCallbackQuery(
                        queryId=callback.query_id, text="🔙 Returning to idle state..."
                    )
                    await self.state_manager.transition_state("back", user_id, chat_id)
                    await self.client.sendMessage(
                        chatId=chat_id, text="🔙 Conversation ended. Type /start to begin a new conversation."
                    )

            # Handle survey topic selection
            elif current_state == "survey_topic":
                await self.handle_survey_flow(user_id, chat_id, "", payload)
                await self.client.answerCallbackQuery(queryId=callback.query_id, text="📊 Topic selected...")

            # Handle survey rating
            elif current_state == "survey_rating":
                await self.handle_survey_flow(user_id, chat_id, "", payload)
                await self.client.answerCallbackQuery(queryId=callback.query_id, text="⭐ Rating recorded...")

            # Handle support issue selection
            elif current_state == "support_issue":
                await self.handle_support_flow(user_id, chat_id, "", payload)
                await self.client.answerCallbackQuery(queryId=callback.query_id, text="📝 Issue type selected...")

            # Handle cancel in any state
            elif payload == "cancel":
                await self.client.answerCallbackQuery(queryId=callback.query_id, text="❌ Operation cancelled")
                await self.state_manager.transition_state("cancel", user_id, chat_id)

                keyboard = self.client.createInlineKeyboard(self.create_welcome_keyboard())
                await self.client.sendMessage(
                    chatId=chat_id, text="❌ Operation cancelled.\n\n" "Choose another option:", inlineKeyboard=keyboard
                )

            else:
                await self.client.answerCallbackQuery(
                    queryId=callback.query_id, text=f"❓ Unknown action: {payload}", showAlert=True
                )

        except MaxBotError as e:
            logging.error(f"❌ Error handling callback: {e}")
            await self.client.answerCallbackQuery(
                queryId=callback.query_id, text="❌ Error occurred while processing your request", showAlert=True
            )

    async def handle_text_message(self, update) -> None:
        """Handle text messages based on current state.

        Args:
            update: The update object containing the message
        """
        message = update.message
        user_id = message.sender.user_id
        chat_id = message.recipient.chat_id
        text = message.body.text or ""

        # Get user context
        context = await self.state_manager.get_context(user_id, chat_id)
        if not context:
            await self.client.sendMessage(
                chatId=chat_id, text="👋 Welcome! Please type /start to begin a conversation."
            )
            return

        current_state = context.currentState.name if context.currentState else "unknown"

        # Route message based on current state
        if current_state == "idle":
            await self.client.sendMessage(
                chatId=chat_id, text="🔙 You're in idle state. Type /start to begin a new conversation."
            )

        elif current_state in ["registration_name", "registration_email", "registration_age"]:
            await self.handle_registration_flow(user_id, chat_id, text)

        elif current_state == "survey_feedback":
            await self.handle_survey_flow(user_id, chat_id, text)

        elif current_state == "support_details":
            await self.handle_support_flow(user_id, chat_id, text)

        elif current_state == "welcome":
            await self.client.sendMessage(chatId=chat_id, text="👋 Please use the buttons below to select an option:")

        else:
            await self.client.sendMessage(
                chatId=chat_id, text=f"🔄 I'm in the '{current_state}' state. Please use the provided options."
            )

    async def handle_commands(self, update) -> bool:
        """Handle bot commands.

        Args:
            update: The update object containing the message

        Returns:
            True if a command was handled, False otherwise
        """
        message = update.message
        chat_id = message.recipient.chat_id
        user_id = message.sender.user_id
        text = message.body.text or ""

        if not text.startswith("/"):
            return False

        command = text.lower().split()[0]
        user_name = message.sender.first_name or "User"

        logging.info(f"🎯 Command from {user_name}: {command}")

        try:
            if command == "/start":
                # Clear any existing context and start fresh
                await self.state_manager.delete_context(user_id, chat_id)
                await self.send_welcome_message(chat_id, user_id, user_name)

            elif command == "/help":
                help_text = (
                    "🤖 *Conversation Bot Help*\n\n"
                    "Available commands:\n"
                    "• `/start` - Start a new conversation\n"
                    "• `/help` - Show this help message\n"
                    "• `/status` - Show current conversation state\n"
                    "• `/reset` - Reset conversation state\n\n"
                    "Conversation flows:\n"
                    "• 📝 **User Registration** - Multi-step registration process\n"
                    "• 📊 **Survey** - Interactive survey with ratings and feedback\n"
                    "• 💬 **Customer Support** - Issue reporting with ticket generation\n\n"
                    "Each flow maintains state and context across multiple messages!"
                )

                await self.client.sendMessage(
                    chatId=chat_id, text=help_text, format=cast(TextFormat, TextFormat.MARKDOWN)
                )

            elif command == "/status":
                context = await self.state_manager.get_context(user_id, chat_id)
                if context:
                    state_name = context.currentState.name if context.currentState else "unknown"
                    user_name = await self.state_manager.get_state_data("user_name", user_id=user_id, chat_id=chat_id)

                    status_text = (
                        f"📊 *Conversation Status*\n\n"
                        f"👤 **User:** {user_name or 'Unknown'}\n"
                        f"🔄 **Current State:** {state_name}\n"
                        f"📝 **Data Keys:** {list(context.stateData.keys())}\n"
                        f"🕒 **Started:** {context.createdAt:.0f}\n"
                        f"🕒 **Updated:** {context.updatedAt:.0f}"
                    )
                else:
                    status_text = "📊 *Conversation Status*\n\nNo active conversation. Type /start to begin."

                await self.client.sendMessage(
                    chatId=chat_id, text=status_text, format=cast(TextFormat, TextFormat.MARKDOWN)
                )

            elif command == "/reset":
                await self.state_manager.delete_context(user_id, chat_id)
                await self.client.sendMessage(
                    chatId=chat_id, text="🔄 Conversation state reset. Type /start to begin a new conversation."
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
                    # Handle text messages based on state
                    await self.handle_text_message(update)

            elif update.updateType == UpdateType.MESSAGE_CALLBACK:
                await self.handle_callback_query(update)

            elif update.updateType == UpdateType.BOT_ADDED_TO_CHAT:
                chat_id = update.chat.chat_id
                user_name = "Chat Members"
                await self.send_welcome_message(chat_id, 0, user_name)  # Use 0 as placeholder for user_id

            elif update.updateType == UpdateType.BOT_STARTED:
                chat_id = update.user.user_id
                user_id = update.user.user_id
                user_name = update.user.first_name or "User"
                await self.send_welcome_message(chat_id, user_id, user_name)

            else:
                logging.debug(f"🔄 Unhandled update type: {update.updateType}")

        except Exception as e:
            logging.error(f"❌ Error processing update: {e}")


async def run_bot() -> None:
    """Main bot function that handles the bot lifecycle."""
    token = get_token()

    logging.info("🚀 Starting Conversation Bot...")

    try:
        # Initialize the client
        async with MaxBotClient(token) as client:
            # Create bot instance
            bot = ConversationBot(client)

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
            logging.info("📱 Send /start to your bot to try the conversation flows!")
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
