#!/usr/bin/env python3
"""
File Bot Example

This example demonstrates file operations in Max Bot, including uploading and downloading
various types of files (photos, videos, audio, documents), streaming large files, and
managing file attachments.

Features demonstrated:
- File upload (photo, video, audio, document)
- File download (to disk and as bytes)
- File streaming for large files
- File URL generation
- Attachment handling
- Progress tracking
- Error handling for file operations

Run this example:
    python file_bot.py

Requirements:
    - Set MAX_BOT_TOKEN environment variable with your bot access token
    - Create a 'downloads' directory for downloaded files
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import cast

# Add the parent directory to the path so we can import lib.max_bot
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from lib.max_bot import (  # noqa: E402
    AttachmentType,
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


def ensure_downloads_directory() -> Path:
    """Ensure the downloads directory exists.

    Returns:
        Path to the downloads directory
    """
    downloads_dir = Path("downloads")
    downloads_dir.mkdir(exist_ok=True)
    return downloads_dir


class FileBot:
    """A bot that demonstrates file operations."""

    def __init__(self, client: MaxBotClient):
        """Initialize the file bot.

        Args:
            client: The MaxBotClient instance
        """
        self.client = client
        self.downloads_dir = ensure_downloads_directory()

    def create_main_keyboard(self) -> list:
        """Create the main inline keyboard for file operations.

        Returns:
            List of keyboard rows with buttons
        """
        return [
            [
                {"type": "callback", "text": "📸 Upload Photo", "payload": "upload_photo"},
                {"type": "callback", "text": "🎥 Upload Video", "payload": "upload_video"},
            ],
            [
                {"type": "callback", "text": "🎵 Upload Audio", "payload": "upload_audio"},
                {"type": "callback", "text": "📄 Upload Document", "payload": "upload_document"},
            ],
            [
                {"type": "callback", "text": "📥 Download Demo", "payload": "download_demo"},
                {"type": "callback", "text": "📊 File Info", "payload": "file_info"},
            ],
            [
                {"type": "callback", "text": "🧹 Clean Downloads", "payload": "clean_downloads"},
                {"type": "callback", "text": "❌ Close", "payload": "close_menu"},
            ],
        ]

    async def send_welcome_message(self, chat_id: int, user_name: str) -> None:
        """Send a welcome message with the main keyboard.

        Args:
            chat_id: The chat ID to send the message to
            user_name: The user's name for personalization
        """
        welcome_text = (
            f"👋 Hello, {user_name}!\n\n"
            "📁 *File Bot Demo*\n\n"
            "This bot demonstrates file operations:\n"
            "• 📸 Photo upload and download\n"
            "• 🎥 Video file handling\n"
            "• 🎵 Audio file management\n"
            "• 📄 Document operations\n"
            "• 📥 File streaming\n"
            "• 📊 File information\n\n"
            "Choose an operation below! 👇"
        )

        keyboard = self.client.createInlineKeyboard(self.create_main_keyboard())

        await self.client.sendMessage(
            chatId=chat_id, text=welcome_text, format=cast(TextFormat, TextFormat.MARKDOWN), inlineKeyboard=keyboard
        )

    async def create_sample_file(self, file_type: str) -> str:
        """Create a sample file for demonstration purposes.

        Args:
            file_type: Type of file to create (photo, video, audio, document)

        Returns:
            Path to the created file
        """
        timestamp = int(asyncio.get_event_loop().time())

        if file_type == "photo":
            # Create a simple text file as a "photo" placeholder
            file_path = self.downloads_dir / f"sample_photo_{timestamp}.txt"
            with open(file_path, "w") as f:
                f.write("This is a sample photo file placeholder.\n")
                f.write(f"Created at: {timestamp}\n")
                f.write("In a real implementation, this would be an actual image file.\n")

        elif file_type == "video":
            file_path = self.downloads_dir / f"sample_video_{timestamp}.txt"
            with open(file_path, "w") as f:
                f.write("This is a sample video file placeholder.\n")
                f.write(f"Created at: {timestamp}\n")
                f.write("In a real implementation, this would be an actual video file.\n")

        elif file_type == "audio":
            file_path = self.downloads_dir / f"sample_audio_{timestamp}.txt"
            with open(file_path, "w") as f:
                f.write("This is a sample audio file placeholder.\n")
                f.write(f"Created at: {timestamp}\n")
                f.write("In a real implementation, this would be an actual audio file.\n")

        elif file_type == "document":
            file_path = self.downloads_dir / f"sample_document_{timestamp}.txt"
            with open(file_path, "w") as f:
                f.write("Sample Document\n")
                f.write("=" * 20 + "\n\n")
                f.write("This is a sample document created for demonstration purposes.\n")
                f.write(f"Created at: {timestamp}\n")
                f.write("\nFeatures demonstrated:\n")
                f.write("- File upload\n")
                f.write("- File download\n")
                f.write("- File streaming\n")
                f.write("- File management\n")

        return str(file_path)

    async def upload_file_demo(self, chat_id: int, file_type: str) -> None:
        """Demonstrate file upload functionality.

        Args:
            chat_id: The chat ID to send messages to
            file_type: Type of file to upload
        """
        try:
            # Show typing action
            await self.client.sendAction(chat_id, SenderAction.UPLOAD_FILE)

            # Create a sample file
            file_path = await self.create_sample_file(file_type)

            # Upload the file
            if file_type == "photo":
                result = await self.client.uploadPhoto(file_path)
                attachment_type = "📸 Photo"
            elif file_type == "video":
                result = await self.client.uploadVideo(file_path)
                attachment_type = "🎥 Video"
            elif file_type == "audio":
                result = await self.client.uploadAudio(file_path)
                attachment_type = "🎵 Audio"
            elif file_type == "document":
                result = await self.client.uploadDocument(file_path)
                attachment_type = "📄 Document"
            else:
                raise ValueError(f"Unknown file type: {file_type}")

            # Send the uploaded file
            attachment = getattr(result, "attachment", None) if result else None
            attachments = [attachment] if attachment else []
            await self.client.sendMessage(
                chatId=chat_id,
                text=f"{attachment_type} uploaded successfully! 📤",
                attachments=attachments,
            )

            # Clean up the sample file
            os.remove(file_path)

            logging.info(f"✅ {file_type} uploaded successfully")

        except MaxBotError as e:
            logging.error(f"❌ Error uploading {file_type}: {e}")
            await self.client.sendMessage(chatId=chat_id, text=f"❌ Error uploading {file_type}: {str(e)}")
        except Exception as e:
            logging.error(f"❌ Unexpected error uploading {file_type}: {e}")
            await self.client.sendMessage(chatId=chat_id, text=f"❌ Unexpected error uploading {file_type}")

    async def download_file_demo(self, chat_id: int) -> None:
        """Demonstrate file download functionality.

        Args:
            chat_id: The chat ID to send messages to
        """
        try:
            # Show typing action
            await self.client.sendAction(chat_id, SenderAction.UPLOAD_FILE)

            # First upload a file to have something to download
            sample_file = await self.create_sample_file("document")
            upload_result = await self.client.uploadDocument(sample_file)

            # Get file ID from the upload result
            attachment = getattr(upload_result, "attachment", None)
            if attachment and hasattr(attachment, "payload"):
                file_id = attachment.payload.get("file_id")
            else:
                file_id = None
            if not file_id:
                raise ValueError("No file ID in upload result")

            # Get file URL
            file_url = await self.client.getFileUrl(file_id)

            # Download file to disk
            download_path = self.downloads_dir / f"downloaded_{file_id}.txt"
            await self.client.downloadFile(file_id, str(download_path))

            # Send confirmation with file info
            file_size = download_path.stat().st_size

            info_text = (
                f"📥 *File Download Demo*\n\n"
                f"📄 File ID: `{file_id}`\n"
                f"🌐 File URL: {file_url}\n"
                f"💾 Downloaded to: `{download_path.name}`\n"
                f"📊 File size: {file_size} bytes\n\n"
                f"✅ Download completed successfully!"
            )

            await self.client.sendMessage(chatId=chat_id, text=info_text, format=cast(TextFormat, TextFormat.MARKDOWN))

            # Clean up
            os.remove(sample_file)

            logging.info(f"✅ File downloaded successfully: {download_path}")

        except MaxBotError as e:
            logging.error(f"❌ Error downloading file: {e}")
            await self.client.sendMessage(chatId=chat_id, text=f"❌ Error downloading file: {str(e)}")
        except Exception as e:
            logging.error(f"❌ Unexpected error downloading file: {e}")
            await self.client.sendMessage(chatId=chat_id, text="❌ Unexpected error downloading file")

    async def stream_file_demo(self, chat_id: int) -> None:
        """Demonstrate file streaming functionality.

        Args:
            chat_id: The chat ID to send messages to
        """
        try:
            # Show typing action
            await self.client.sendAction(chat_id, SenderAction.UPLOAD_FILE)

            # Create a larger sample file for streaming demo
            timestamp = int(asyncio.get_event_loop().time())
            large_file_path = self.downloads_dir / f"large_file_{timestamp}.txt"

            with open(large_file_path, "w") as f:
                for i in range(1000):
                    f.write(f"This is line {i + 1} of the large sample file.\n")
                    f.write("Streaming allows processing large files without loading everything into memory.\n")
                    f.write("-" * 50 + "\n")

            # Upload the large file using streaming
            with open(large_file_path, "rb") as f:
                upload_result = await self.client.uploadFileStream(
                    stream=f, uploadType="document", filename=large_file_path.name, mimeType="text/plain"
                )

            # Get file ID
            attachment = getattr(upload_result, "attachment", None)
            if attachment and hasattr(attachment, "payload"):
                file_id = attachment.payload.get("file_id")
            else:
                file_id = None

            # Stream download the file
            if not file_id:
                raise ValueError("No file ID available for download")

            streamed_content = b""
            chunk_count = 0

            download_stream = await self.client.downloadFileStream(file_id)
            async for chunk in download_stream:
                streamed_content += chunk
                chunk_count += 1

                # Log progress every 10 chunks
                if chunk_count % 10 == 0:
                    logging.info(f"📥 Streamed {chunk_count} chunks ({len(streamed_content)} bytes)")

            # Save streamed content
            streamed_file_path = self.downloads_dir / f"streamed_{file_id}.txt"
            with open(streamed_file_path, "wb") as f:
                f.write(streamed_content)

            # Send confirmation
            info_text = (
                f"🌊 *File Streaming Demo*\n\n"
                f"📄 File ID: `{file_id}`\n"
                f"📊 Chunks processed: {chunk_count}\n"
                f"💾 Total size: {len(streamed_content)} bytes\n"
                f"💾 Saved to: `{streamed_file_path.name}`\n\n"
                f"✅ Streaming completed successfully!"
            )

            await self.client.sendMessage(chatId=chat_id, text=info_text, format=cast(TextFormat, TextFormat.MARKDOWN))

            # Clean up
            os.remove(large_file_path)

            logging.info(f"✅ File streamed successfully: {streamed_file_path}")

        except MaxBotError as e:
            logging.error(f"❌ Error streaming file: {e}")
            await self.client.sendMessage(chatId=chat_id, text=f"❌ Error streaming file: {str(e)}")
        except Exception as e:
            logging.error(f"❌ Unexpected error streaming file: {e}")
            await self.client.sendMessage(chatId=chat_id, text="❌ Unexpected error streaming file")

    async def show_file_info(self, chat_id: int) -> None:
        """Show information about downloaded files.

        Args:
            chat_id: The chat ID to send messages to
        """
        try:
            # List files in downloads directory
            files = list(self.downloads_dir.glob("*"))

            if not files:
                await self.client.sendMessage(
                    chatId=chat_id, text="📁 No downloaded files found.\n\nUse the download demo to create some files!"
                )
                return

            # Build file information
            info_lines = ["📊 *Downloaded Files*\n\n"]

            total_size = 0
            for file_path in files:
                if file_path.is_file():
                    size = file_path.stat().st_size
                    total_size += size
                    modified = file_path.stat().st_mtime

                    info_lines.append(
                        f"📄 `{file_path.name}`\n" f"   💾 Size: {size:,} bytes\n" f"   🕒 Modified: {modified:.0f}\n"
                    )

            info_lines.append(f"\n📊 **Total:** {len(files)} files, {total_size:,} bytes")

            await self.client.sendMessage(
                chatId=chat_id, text="\n".join(info_lines), format=cast(TextFormat, TextFormat.MARKDOWN)
            )

        except Exception as e:
            logging.error(f"❌ Error showing file info: {e}")
            await self.client.sendMessage(chatId=chat_id, text=f"❌ Error showing file info: {str(e)}")

    async def clean_downloads(self, chat_id: int) -> None:
        """Clean up downloaded files.

        Args:
            chat_id: The chat ID to send messages to
        """
        try:
            # List and remove files
            files = list(self.downloads_dir.glob("*"))
            removed_count = 0

            for file_path in files:
                if file_path.is_file():
                    file_path.unlink()
                    removed_count += 1

            if removed_count > 0:
                await self.client.sendMessage(
                    chatId=chat_id,
                    text=f"🧹 *Cleanup Complete*\n\n"
                    f"🗑️ Removed {removed_count} files from downloads directory.\n\n"
                    f"✅ Downloads directory is now clean!",
                )
            else:
                await self.client.sendMessage(
                    chatId=chat_id, text="🧹 No files to clean up.\n\nDownloads directory is already empty!"
                )

            logging.info(f"✅ Cleaned up {removed_count} files")

        except Exception as e:
            logging.error(f"❌ Error cleaning downloads: {e}")
            await self.client.sendMessage(chatId=chat_id, text=f"❌ Error cleaning downloads: {str(e)}")

    async def handle_callback_query(self, update) -> None:
        """Handle callback queries from inline keyboard buttons.

        Args:
            update: The update object containing the callback query
        """
        callback = update.callbackQuery
        chat_id = callback.message.recipient.chat_id
        payload = callback.payload

        logging.info(f"🔘 Callback: {payload}")

        try:
            if payload == "upload_photo":
                await self.client.answerCallbackQuery(queryId=callback.query_id, text="📸 Uploading photo...")
                await self.upload_file_demo(chat_id, "photo")

            elif payload == "upload_video":
                await self.client.answerCallbackQuery(queryId=callback.query_id, text="🎥 Uploading video...")
                await self.upload_file_demo(chat_id, "video")

            elif payload == "upload_audio":
                await self.client.answerCallbackQuery(queryId=callback.query_id, text="🎵 Uploading audio...")
                await self.upload_file_demo(chat_id, "audio")

            elif payload == "upload_document":
                await self.client.answerCallbackQuery(queryId=callback.query_id, text="📄 Uploading document...")
                await self.upload_file_demo(chat_id, "document")

            elif payload == "download_demo":
                await self.client.answerCallbackQuery(queryId=callback.query_id, text="📥 Starting download demo...")
                await self.download_file_demo(chat_id)

            elif payload == "stream_demo":
                await self.client.answerCallbackQuery(queryId=callback.query_id, text="🌊 Starting streaming demo...")
                await self.stream_file_demo(chat_id)

            elif payload == "file_info":
                await self.client.answerCallbackQuery(queryId=callback.query_id, text="📊 Getting file information...")
                await self.show_file_info(chat_id)

            elif payload == "clean_downloads":
                await self.client.answerCallbackQuery(queryId=callback.query_id, text="🧹 Cleaning downloads...")
                await self.clean_downloads(chat_id)

            elif payload == "close_menu":
                await self.client.editMessage(
                    messageId=callback.message.body.mid,
                    text="👋 File operations menu closed!\n\nType /start to show it again.",
                )
                await self.client.answerCallbackQuery(queryId=callback.query_id, text="❌ Menu closed")

            else:
                await self.client.answerCallbackQuery(
                    queryId=callback.query_id, text=f"❓ Unknown action: {payload}", showAlert=True
                )

        except MaxBotError as e:
            logging.error(f"❌ Error handling callback: {e}")
            await self.client.answerCallbackQuery(
                queryId=callback.query_id, text="❌ Error occurred while processing your request", showAlert=True
            )

    async def handle_file_message(self, update) -> None:
        """Handle incoming file messages.

        Args:
            update: The update object containing the message
        """
        message = update.message
        chat_id = message.recipient.chat_id

        try:
            if message.body.attachments:
                for attachment in message.body.attachments:
                    if attachment.type == AttachmentType.PHOTO:
                        await self.client.sendMessage(chatId=chat_id, text="📸 Photo received! Nice picture! 🖼️")
                    elif attachment.type == AttachmentType.VIDEO:
                        await self.client.sendMessage(chatId=chat_id, text="🎥 Video received! Cool video! 🎬")
                    elif attachment.type == AttachmentType.AUDIO:
                        await self.client.sendMessage(chatId=chat_id, text="🎵 Audio received! Great music! 🎶")
                    elif attachment.type == AttachmentType.FILE:
                        await self.client.sendMessage(
                            chatId=chat_id, text="📄 Document received! Thanks for sharing! 📋"
                        )
                    else:
                        await self.client.sendMessage(chatId=chat_id, text=f"📎 File received: {attachment.type}")
            else:
                await self.client.sendMessage(
                    chatId=chat_id, text="📨 Message received! Use /start to see file operations."
                )

        except Exception as e:
            logging.error(f"❌ Error handling file message: {e}")

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
                    "🤖 *File Bot Help*\n\n"
                    "Available commands:\n"
                    "• `/start` - Show file operations menu\n"
                    "• `/upload <type>` - Upload a file (photo/video/audio/document)\n"
                    "• `/download <file_id>` - Download a file\n"
                    "• `/info` - Show downloaded files info\n"
                    "• `/clean` - Clean downloads directory\n"
                    "• `/help` - Show this help message\n\n"
                    "Features:\n"
                    "• 📸 Photo upload/download\n"
                    "• 🎥 Video file handling\n"
                    "• 🎵 Audio file management\n"
                    "• 📄 Document operations\n"
                    "• 🌊 File streaming\n"
                    "• 📊 File information"
                )

                await self.client.sendMessage(
                    chatId=chat_id, text=help_text, format=cast(TextFormat, TextFormat.MARKDOWN)
                )

            elif command == "/info":
                await self.show_file_info(chat_id)

            elif command == "/clean":
                await self.clean_downloads(chat_id)

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
                    # Handle file messages
                    await self.handle_file_message(update)

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

    logging.info("🚀 Starting File Bot...")
    logging.info(f"📁 Downloads directory: {ensure_downloads_directory()}")

    try:
        # Initialize the client
        async with MaxBotClient(token) as client:
            # Create bot instance
            bot = FileBot(client)

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
            logging.info("📱 Send /start to your bot to see the file operations demo!")
            logging.info("⏹️ Press Ctrl+C to stop the bot")

            update_count = 0
            offset = 0

            while True:
                try:
                    # Get updates
                    updates = await client.getUpdates(lastEventId=offset, timeout=30)

                    for update in updates.updates:
                        update_count += 1
                        logging.debug(f"📨 Processing update #{update_count}")

                        # Process the update
                        await bot.process_update(update)

                        # Update offset to mark update as processed
                        offset = update.update_id + 1

                except Exception as e:
                    logging.error(f"Error polling for updates: {e}")
                    await asyncio.sleep(5)  # Wait before retrying

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
