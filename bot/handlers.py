"""
Telegram bot command handlers for Gromozeka.
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes

from database.wrapper import DatabaseWrapper

logger = logging.getLogger(__name__)


class BotHandlers:
    """Contains all bot command and message handlers."""
    
    def __init__(self, database: DatabaseWrapper, llm_model):
        """Initialize handlers with database and LLM model."""
        self.db = database
        self.llm_model = llm_model
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /start command."""
        user = update.effective_user
        if not user or not update.message:
            logging.error("User or message undefined")
            return

        # Save user to database
        self.db.save_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )

        welcome_message = (
            f"Hello {user.first_name}! 👋\n\n"
            "I'm Gromozeka, your friendly Telegram bot, dood!\n\n"
            "Available commands:\n"
            "/start - Show this welcome message\n"
            "/help - Get help information\n"
            "/stats - Show your statistics\n"
            "/echo <message> - Echo your message back\n\n"
            "Just send me any message and I'll respond, dood!"
        )

        await update.message.reply_text(welcome_message)
        logger.info(f"User {user.id} ({user.username}) started the bot")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /help command."""
        if not update.message:
            logging.error("Message undefined")
            return
            
        help_text = (
            "🤖 *Gromozeka Bot Help*\n\n"
            "*Commands:*\n"
            "/start - Welcome message and bot introduction\n"
            "/help - Show this help message\n"
            "/stats - Display your usage statistics\n"
            "/echo <message> - Echo your message back\n\n"
            "*Features:*\n"
            "• Message logging and statistics\n"
            "• User data persistence\n"
            "• Simple conversation handling\n\n"
            "Just send me any text message and I'll respond, dood!"
        )

        await update.message.reply_text(help_text, parse_mode='Markdown')

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /stats command."""
        user = update.effective_user
        if not user or not update.message:
            logging.error("User or message undefined")
            return

        # Get user data from database
        user_data = self.db.get_user(user.id)
        messages = self.db.get_user_messages(user.id, limit=100)

        if user_data:
            stats_text = (
                f"📊 *Your Statistics*\n\n"
                f"👤 *User:* {user_data['first_name']}\n"
                f"🆔 *ID:* {user_data['user_id']}\n"
                f"📅 *Joined:* {user_data['created_at'][:10]}\n"
                f"💬 *Messages sent:* {len(messages)}\n"
            )
        else:
            stats_text = "No statistics available. Send me a message first!"

        await update.message.reply_text(stats_text, parse_mode='Markdown')

    async def echo_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /echo command."""
        if not update.message:
            logging.error("Message undefined")
            return
            
        if context.args:
            echo_text = " ".join(context.args)
            await update.message.reply_text(f"🔄 Echo: {echo_text}")
        else:
            await update.message.reply_text("Please provide a message to echo!\nUsage: /echo <your message>")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle regular text messages."""
        user = update.effective_user
        if not user or not update.message:
            logging.error("User or message undefined")
            return
            
        message_text = update.message.text
        if not message_text:
            logging.error("Message text undefined")
            return

        # Save user and message to database
        self.db.save_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )
        messages = self.db.get_user_messages(user.id, limit=10)
        req_messages = [
            {
                "role": "system",
                "text": "Ты - Prinny - вайбовый, но умный пингвин из Disgaea. При ответе ты можешь использовать Markdown форматирование",
            },
        ]

        for message in reversed(messages):
            req_messages.append({
                "role": "user",
                "text": message["message_text"],
            })
            if message["reply_text"]:
                req_messages.append({
                    "role": "assistant",
                    "text": message["reply_text"],
                })
        req_messages.append({
            "role": "user",
            "text": message_text,
        })
        
        logging.info(f"LLM Request messages: {req_messages}")
        ml_ret = self.llm_model.run(req_messages)
        logging.info(f"LLM Response: {ml_ret}")
        reply = ml_ret.alternatives[0].text
        self.db.save_message(user.id, message_text, reply_text=reply)

        try:
            await update.message.reply_markdown(reply, reply_to_message_id=update.message.message_id)
            logger.info(f"Replied to message from {user.id}: {message_text[:50]}...")
        except Exception as e:
            logger.error(f"Error while replying to message: {type(e).__name__}#{e}")
            # Probably error in markdown formatting, fallback to raw text
            await update.message.reply_text(reply, reply_to_message_id=update.message.message_id)
        logger.info(f"Handled message from {user.id}: {message_text[:50]}...")

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors."""
        logger.error(f"Exception while handling an update: {context.error}")