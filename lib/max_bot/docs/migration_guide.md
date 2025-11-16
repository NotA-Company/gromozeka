# Migration Guide

This guide helps developers migrate from other popular bot libraries to the Max Bot client library. We provide specific examples and mappings for common patterns.

## Table of Contents

- [Overview](#overview)
- [Migrating from python-telegram-bot](#migrating-from-python-telegram-bot)
- [Migrating from aiogram](#migrating-from-aiogram)
- [Migrating from pyTelegramBotAPI](#migrating-from-pytelegrambotapi)
- [Migrating from discord.py](#migrating-from-discordpy)
- [Migrating from Slack SDK](#migrating-from-slack-sdk)
- [Common Patterns Comparison](#common-patterns-comparison)
- [Migration Checklist](#migration-checklist)

## Overview

The Max Bot client library provides a modern, async-first interface for building Max Messenger bots. While the API is designed to be intuitive, developers coming from other platforms may need to adjust their patterns.

### Key Differences

| Feature | Max Bot | Other Libraries |
|---------|---------|-----------------|
| **Async Support** | Native async/await | Varies (some sync, some async) |
| **Context Management** | Required (`async with`) | Optional or different pattern |
| **Update Handling** | Iterator-based polling | Decorator-based or callback-based |
| **Keyboard Creation** | Method-based | Class-based or function-based |
| **Error Handling** | Exception hierarchy | Varies widely |
| **State Management** | Built-in StateManager | Usually custom implementation |

## Migrating from python-telegram-bot

python-telegram-bot is one of the most popular Telegram bot libraries. Here's how to migrate:

### Basic Bot Setup

**python-telegram-bot:**
```python
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Hello!')

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(update.message.text)

def main():
    application = Application.builder().token("TOKEN").build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    
    application.run_polling()

if __name__ == "__main__":
    main()
```

**Max Bot:**
```python
from lib.max_bot import MaxBotClient, UpdateType

async def handle_start(client, chat_id, user_name):
    await client.sendMessage(
        chatId=chat_id,
        text=f"Hello, {user_name}!"
    )

async def handle_echo(client, chat_id, text):
    await client.sendMessage(
        chatId=chat_id,
        text=text
    )

async def handle_update(client, update):
    if update.updateType == UpdateType.MESSAGE_CREATED:
        message = update.message
        chat_id = message.recipient.chat_id
        text = message.body.text or ""
        user_name = message.sender.first_name or "User"
        
        if text.startswith("/"):
            if text.lower() == "/start":
                await handle_start(client, chat_id, user_name)
        else:
            await handle_echo(client, chat_id, text)

async def main():
    async with MaxBotClient("TOKEN") as client:
        async for update in client.startPolling():
            await handle_update(client, update)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

### Keyboards

**python-telegram-bot:**
```python
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

keyboard = [
    [InlineKeyboardButton("Option 1", callback_data='1')],
    [InlineKeyboardButton("Option 2", callback_data='2')]
]
reply_markup = InlineKeyboardMarkup(keyboard)

await update.message.reply_text('Choose:', reply_markup=reply_markup)
```

**Max Bot:**
```python
keyboard = client.createInlineKeyboard([
    [{"type": "callback", "text": "Option 1", "payload": "1"}],
    [{"type": "callback", "text": "Option 2", "payload": "2"}]
])

await client.sendMessage(
    chatId=chat_id,
    text="Choose:",
    inlineKeyboard=keyboard
)
```

### Callback Handling

**python-telegram-bot:**
```python
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text=f"Selected option: {query.data}")

application.add_handler(CallbackQueryHandler(button))
```

**Max Bot:**
```python
async def handle_callback(client, update):
    if update.updateType == UpdateType.MESSAGE_CALLBACK:
        callback = update.callbackQuery
        payload = callback.payload
        
        await client.answerCallbackQuery(queryId=callback.queryId)
        await client.editMessage(
            messageId=callback.message.body.mid,
            text=f"Selected option: {payload}"
        )
```

## Migrating from aiogram

aiogram is another popular async Telegram bot library for Python.

### Basic Bot Setup

**aiogram:**
```python
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

bot = Bot(token="TOKEN")
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Hello!")

@dp.message()
async def echo(message: types.Message):
    await message.answer(message.text)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

**Max Bot:**
```python
from lib.max_bot import MaxBotClient, UpdateType

async def handle_update(client, update):
    if update.updateType == UpdateType.MESSAGE_CREATED:
        message = update.message
        chat_id = message.recipient.chat_id
        text = message.body.text or ""
        
        if text.startswith("/"):
            if text.lower() == "/start":
                await client.sendMessage(
                    chatId=chat_id,
                    text="Hello!"
                )
        else:
            await client.sendMessage(
                chatId=chat_id,
                text=text
            )

async def main():
    async with MaxBotClient("TOKEN") as client:
        async for update in client.startPolling():
            await handle_update(client, update)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

### State Machines

**aiogram:**
```python
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

class Form(StatesGroup):
    name = State()
    age = State()

@dp.message(Form.name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(Form.age)
    await message.answer("How old are you?")

@dp.message(Form.age)
async def process_age(message: types.Message, state: FSMContext):
    await state.update_data(age=message.text)
    data = await state.get_data()
    await message.answer(f"Name: {data['name']}, Age: {data['age']}")
    await state.clear()
```

**Max Bot:**
```python
from lib.max_bot import StateManager

class FormBot:
    def __init__(self, client):
        self.client = client
        self.state_manager = StateManager()
    
    async def handle_message(self, update):
        message = update.message
        user_id = message.sender.user_id
        text = message.body.text or ""
        
        state = await self.state_manager.getState(user_id)
        
        if not state:
            if text.startswith("/form"):
                await self.state_manager.setState(user_id, "name")
                await self.client.sendMessage(
                    chatId=message.recipient.chat_id,
                    text="What's your name?"
                )
        elif state.state == "name":
            await self.state_manager.setState(user_id, "age", {"name": text})
            await self.client.sendMessage(
                chatId=message.recipient.chat_id,
                text="How old are you?"
            )
        elif state.state == "age":
            data = state.data
            await self.client.sendMessage(
                chatId=message.recipient.chat_id,
                text=f"Name: {data['name']}, Age: {text}"
            )
            await self.state_manager.deleteState(user_id)
```

## Migrating from pyTelegramBotAPI

pyTelegramBotAPI (TeleBot) is a synchronous library, so the migration involves more significant changes.

### Basic Bot Setup

**pyTelegramBotAPI:**
```python
import telebot

bot = telebot.TeleBot("TOKEN")

@bot.message_handler(commands=['start'])
def start_message(message):
    bot.send_message(message.chat.id, 'Hello!')

@bot.message_handler(func=lambda message: True)
def echo_message(message):
    bot.send_message(message.chat.id, message.text)

bot.polling()
```

**Max Bot:**
```python
from lib.max_bot import MaxBotClient, UpdateType

async def handle_update(client, update):
    if update.updateType == UpdateType.MESSAGE_CREATED:
        message = update.message
        chat_id = message.recipient.chat_id
        text = message.body.text or ""
        
        if text.startswith("/"):
            if text.lower() == "/start":
                await client.sendMessage(
                    chatId=chat_id,
                    text="Hello!"
                )
        else:
            await client.sendMessage(
                chatId=chat_id,
                text=text
            )

async def main():
    async with MaxBotClient("TOKEN") as client:
        async for update in client.startPolling():
            await handle_update(client, update)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

### Key Differences

1. **Async vs Sync**: Max Bot is async-only, while pyTelegramBotAPI is sync
2. **Context Manager**: Max Bot requires using `async with`
3. **Update Structure**: Different object structure for messages and updates
4. **Method Names**: Different naming conventions

## Migrating from discord.py

If you're coming from Discord bot development, the concepts are similar but the API differs.

### Basic Bot Setup

**discord.py:**
```python
import discord

intents = discord.Intents.default()
intents.message_content = True

bot = discord.Client(intents=intents)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    
    if message.content.startswith('/hello'):
        await message.channel.send('Hello!')

bot.run('TOKEN')
```

**Max Bot:**
```python
from lib.max_bot import MaxBotClient, UpdateType

async def handle_update(client, update):
    if update.updateType == UpdateType.MESSAGE_CREATED:
        message = update.message
        chat_id = message.recipient.chat_id
        text = message.body.text or ""
        
        if text.startswith("/hello"):
            await client.sendMessage(
                chatId=chat_id,
                text="Hello!"
            )

async def main():
    async with MaxBotClient("TOKEN") as client:
        bot_info = await client.getMyInfo()
        print(f'Logged in as {bot_info.first_name}')
        
        async for update in client.startPolling():
            await handle_update(client, update)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

### Embeds vs Rich Messages

**discord.py:**
```python
embed = discord.Embed(
    title="Title",
    description="Description",
    color=discord.Color.blue()
)
embed.add_field(name="Field", value="Value", inline=False)
await message.channel.send(embed=embed)
```

**Max Bot:**
```python
await client.sendMessage(
    chatId=chat_id,
    text="*Title*\n\nDescription\n\n**Field:** Value",
    format=TextFormat.MARKDOWN
)
```

## Migrating from Slack SDK

Slack bot development has different patterns but similar concepts.

### Basic Bot Setup

**Slack SDK:**
```python
from slack_sdk import WebClient
from slack_sdk.socket_mode import SocketModeClient

slack_token = "xoxb-your-token"
app_token = "xapp-your-token"

client = WebClient(token=slack_token)
socket_client = SocketModeClient(
    app_token=app_token,
    web_client=client
)

@socket_client.websockets[0].on("message")
def handle_message(client, req):
    if req["event"]["type"] == "message":
        channel = req["event"]["channel"]
        client.chat_postMessage(channel=channel, text="Hello!")

socket_client.connect()
```

**Max Bot:**
```python
from lib.max_bot import MaxBotClient, UpdateType

async def handle_update(client, update):
    if update.updateType == UpdateType.MESSAGE_CREATED:
        message = update.message
        chat_id = message.recipient.chat_id
        
        await client.sendMessage(
            chatId=chat_id,
            text="Hello!"
        )

async def main():
    async with MaxBotClient("TOKEN") as client:
        async for update in client.startPolling():
            await handle_update(client, update)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

### Interactive Components

**Slack SDK:**
```python
client.chat_postMessage(
    channel=channel,
    text="Choose:",
    blocks=[
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Option 1"},
                    "action_id": "option1"
                }
            ]
        }
    ]
)
```

**Max Bot:**
```python
keyboard = client.createInlineKeyboard([
    [{"type": "callback", "text": "Option 1", "payload": "option1"}]
])

await client.sendMessage(
    chatId=chat_id,
    text="Choose:",
    inlineKeyboard=keyboard
)
```

## Common Patterns Comparison

### Command Handling

| Library | Pattern |
|---------|---------|
| **python-telegram-bot** | Decorator-based handlers |
| **aiogram** | Decorator-based with filters |
| **pyTelegramBotAPI** | Decorator-based (sync) |
| **discord.py** | Event-based handlers |
| **Slack SDK** | Event-based or web API |
| **Max Bot** | Manual routing in update handler |

### File Handling

| Library | Upload Method |
|---------|---------------|
| **python-telegram-bot** | `send_document()` with file path or InputFile |
| **aiogram** | `send_document()` with FSInputFile or BufferedInputFile |
| **pyTelegramBotAPI** | `send_document()` with file path or file object |
| **discord.py** | `send(file=discord.File())` |
| **Slack SDK** | `files_upload()` |
| **Max Bot** | `sendDocument()` with path, bytes, or file-like object |

### State Management

| Library | Approach |
|---------|----------|
| **python-telegram-bot** | `ConversationHandler` or custom |
| **aiogram** | Built-in FSM |
| **pyTelegramBotAPI** | Custom implementation |
| **discord.py** | Custom implementation |
| **Slack SDK** | Custom implementation |
| **Max Bot** | Built-in `StateManager` |

### Error Handling

| Library | Approach |
|---------|----------|
| **python-telegram-bot** | Exception handling in handlers |
| **aiogram** | Exception handlers |
| **pyTelegramBotAPI** | Try/catch in handlers |
| **discord.py** | `on_command_error` event |
| **Slack SDK** | Error responses from API |
| **Max Bot** | Exception hierarchy with specific types |

## Migration Checklist

### Pre-Migration

- [ ] Review current bot functionality
- [ ] Identify all features that need migration
- [ ] Check for Max Bot API equivalents
- [ ] Plan for async conversion (if coming from sync library)
- [ ] Set up development environment

### Code Migration

- [ ] Install Max Bot library: `pip install max-bot`
- [ ] Update imports from old library to Max Bot
- [ ] Convert bot initialization to use `async with MaxBotClient`
- [ ] Update message handling to use Max Bot update structure
- [ ] Convert command handlers to manual routing
- [ ] Update keyboard creation to use Max Bot methods
- [ ] Migrate state management to use `StateManager`
- [ ] Update error handling to use Max Bot exceptions
- [ ] Convert file operations to Max Bot methods

### Testing

- [ ] Test basic message sending/receiving
- [ ] Test all command handlers
- [ ] Test keyboard interactions
- [ ] Test file upload/download
- [ ] Test state management flows
- [ ] Test error scenarios
- [ ] Test with multiple users

### Deployment

- [ ] Update deployment configuration
- [ ] Set environment variables for Max Bot
- [ ] Update webhook configuration (if applicable)
- [ ] Test in staging environment
- [ ] Deploy to production
- [ ] Monitor for issues

### Post-Migration

- [ ] Monitor bot performance
- [ ] Check for any missing features
- [ ] Update documentation
- [ ] Train team on new patterns
- [ ] Plan for future improvements

### Quick Reference

| Task | Old Library | Max Bot |
|------|-------------|---------|
| **Send message** | `bot.send_message(chat_id, text)` | `await client.sendMessage(chatId=chat_id, text=text)` |
| **Send photo** | `bot.send_photo(chat_id, photo)` | `await client.sendPhoto(chatId=chat_id, photo=photo)` |
| **Create keyboard** | `InlineKeyboardMarkup(buttons)` | `client.createInlineKeyboard(buttons)` |
| **Get bot info** | `bot.get_me()` | `await client.getMyInfo()` |
| **Handle updates** | Decorators/events | `async for update in client.startPolling()` |
| **Error handling** | Generic exceptions | `MaxBotError`, `AuthenticationError`, etc. |

---

This migration guide should help you transition from other bot libraries to Max Bot. If you need help with specific migration scenarios, please check the [examples directory](../examples/) or open an issue on GitHub.