"""Comprehensive tests for text formatter module, dood!

This module provides extensive test coverage for the text_formatter module,
including FormatType enum, OutputFormat enum, and FormatEntity class with
all its methods, edge cases, error handling, and formatting scenarios.
"""

import logging
import unittest
from unittest.mock import Mock, patch

import telegram

import lib.max_bot.models as maxModels
from internal.bot.models.text_formatter import (
    FORMATER_ENCODING,
    FormatEntity,
    FormatType,
    OutputFormat,
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# FormatEntity Initialization Tests
# ============================================================================


class TestFormatEntityInit(unittest.TestCase):
    """Test cases for FormatEntity initialization, dood!"""

    def testBasicInitialization(self):
        """Test basic FormatEntity initialization, dood!"""
        entity = FormatEntity(FormatType.BOLD, 0, 5)
        self.assertEqual(entity.type, FormatType.BOLD)
        self.assertEqual(entity.offset, 0)
        self.assertEqual(entity.length, 5)
        self.assertIsNone(entity.url)
        self.assertIsNone(entity.userId)
        self.assertIsNone(entity.userName)
        self.assertIsNone(entity.codeLanguage)

    def testInitializationWithAllParameters(self):
        """Test FormatEntity initialization with all parameters, dood!"""
        entity = FormatEntity(
            FormatType.LINK,
            10,
            15,
            url="https://example.com",
            userId=123,
            userName="testuser",
            codeLanguage="python",
        )
        self.assertEqual(entity.type, FormatType.LINK)
        self.assertEqual(entity.offset, 10)
        self.assertEqual(entity.length, 15)
        self.assertEqual(entity.url, "https://example.com")
        self.assertEqual(entity.userId, 123)
        self.assertEqual(entity.userName, "testuser")
        self.assertEqual(entity.codeLanguage, "python")


# ============================================================================
# FormatEntity fromMax Tests
# ============================================================================


class TestFormatEntityFromMax(unittest.TestCase):
    """Test cases for FormatEntity.fromMax method, dood!"""

    def testFromMaxWithInvalidInput(self):
        """Test fromMax raises ValueError with invalid input, dood!"""
        with self.assertRaises(ValueError) as context:
            FormatEntity.fromMax("not a markup element")  # type: ignore
        self.assertIn("must be an instance of MarkupElement", str(context.exception))

    def testFromMaxWithStrongMarkup(self):
        """Test fromMax converts STRONG markup correctly, dood!"""
        maxEntity = maxModels.MarkupElement(type=maxModels.MarkupType.STRONG, fromField=0, length=5)
        entity = FormatEntity.fromMax(maxEntity)
        self.assertEqual(entity.type, FormatType.BOLD)
        self.assertEqual(entity.offset, 0)
        self.assertEqual(entity.length, 5)

    def testFromMaxWithEmphasizedMarkup(self):
        """Test fromMax converts EMPHASIZED markup correctly, dood!"""
        maxEntity = maxModels.MarkupElement(type=maxModels.MarkupType.EMPHASIZED, fromField=2, length=8)
        entity = FormatEntity.fromMax(maxEntity)
        self.assertEqual(entity.type, FormatType.ITALIC)
        self.assertEqual(entity.offset, 2)
        self.assertEqual(entity.length, 8)

    def testFromMaxWithMonospacedMarkup(self):
        """Test fromMax converts MONOSPACED markup correctly, dood!"""
        maxEntity = maxModels.MarkupElement(type=maxModels.MarkupType.MONOSPACED, fromField=5, length=10)
        entity = FormatEntity.fromMax(maxEntity)
        self.assertEqual(entity.type, FormatType.INLINE_CODE)

    def testFromMaxWithStrikethroughMarkup(self):
        """Test fromMax converts STRIKETHROUGH markup correctly, dood!"""
        maxEntity = maxModels.MarkupElement(type=maxModels.MarkupType.STRIKETHROUGH, fromField=0, length=7)
        entity = FormatEntity.fromMax(maxEntity)
        self.assertEqual(entity.type, FormatType.STRIKETHROUGH)

    def testFromMaxWithUnderlineMarkup(self):
        """Test fromMax converts UNDERLINE markup correctly, dood!"""
        maxEntity = maxModels.MarkupElement(type=maxModels.MarkupType.UNDERLINE, fromField=1, length=6)
        entity = FormatEntity.fromMax(maxEntity)
        self.assertEqual(entity.type, FormatType.UNDERLINE)

    def testFromMaxWithLinkMarkup(self):
        """Test fromMax converts LINK markup correctly, dood!"""
        maxEntity = maxModels.LinkMarkup(fromField=0, length=10, url="https://test.com")
        entity = FormatEntity.fromMax(maxEntity)
        self.assertEqual(entity.type, FormatType.LINK)
        self.assertEqual(entity.url, "https://test.com")

    @patch("internal.bot.models.text_formatter.logger")
    def testFromMaxWithLinkMarkupWrongClass(self, mockLogger):
        """Test fromMax logs error when LINK type has wrong class, dood!"""
        maxEntity = maxModels.MarkupElement(type=maxModels.MarkupType.LINK, fromField=0, length=10)
        entity = FormatEntity.fromMax(maxEntity)
        self.assertEqual(entity.type, FormatType.LINK)
        self.assertIsNone(entity.url)
        mockLogger.error.assert_called()

    def testFromMaxWithUserMentionMarkup(self):
        """Test fromMax converts USER_MENTION markup correctly, dood!"""
        maxEntity = maxModels.UserMentionMarkup(fromField=0, length=8, user_id=456, user_link="testuser")
        entity = FormatEntity.fromMax(maxEntity)
        self.assertEqual(entity.type, FormatType.USER_MENTION)
        self.assertEqual(entity.userId, 456)
        self.assertEqual(entity.userName, "testuser")

    @patch("internal.bot.models.text_formatter.logger")
    def testFromMaxWithUserMentionWrongClass(self, mockLogger):
        """Test fromMax logs error when USER_MENTION type has wrong class, dood!"""
        maxEntity = maxModels.MarkupElement(type=maxModels.MarkupType.USER_MENTION, fromField=0, length=8)
        entity = FormatEntity.fromMax(maxEntity)
        self.assertEqual(entity.type, FormatType.USER_MENTION)
        self.assertIsNone(entity.userId)
        mockLogger.error.assert_called()

    def testFromMaxWithHeadingMarkup(self):
        """Test fromMax converts HEADING markup correctly, dood!"""
        maxEntity = maxModels.MarkupElement(type=maxModels.MarkupType.HEADING, fromField=0, length=12)
        entity = FormatEntity.fromMax(maxEntity)
        self.assertEqual(entity.type, FormatType.HEADING)

    def testFromMaxWithHighlightedMarkup(self):
        """Test fromMax converts HIGHLIGHTED to NORMAL, dood!"""
        maxEntity = maxModels.MarkupElement(type=maxModels.MarkupType.HIGHLIGHTED, fromField=0, length=5)
        entity = FormatEntity.fromMax(maxEntity)
        self.assertEqual(entity.type, FormatType.NORMAL)

    @patch("internal.bot.models.text_formatter.logger")
    def testFromMaxWithUnspecifiedMarkup(self, mockLogger):
        """Test fromMax handles UNSPECIFIED markup with warning, dood!"""
        maxEntity = maxModels.MarkupElement(type=maxModels.MarkupType.UNSPECIFIED, fromField=0, length=5)
        entity = FormatEntity.fromMax(maxEntity)
        self.assertEqual(entity.type, FormatType.UNSPECIFIED)
        mockLogger.warning.assert_called()


# ============================================================================
# FormatEntity fromTelegram Tests
# ============================================================================


class TestFormatEntityFromTelegram(unittest.TestCase):
    """Test cases for FormatEntity.fromTelegram method, dood!"""

    def testFromTelegramWithInvalidInput(self):
        """Test fromTelegram raises ValueError with invalid input, dood!"""
        with self.assertRaises(ValueError) as context:
            FormatEntity.fromTelegram("not a message entity")  # type: ignore
        self.assertIn("must be an instance of MessageEntity", str(context.exception))

    def testFromTelegramWithBoldEntity(self):
        """Test fromTelegram converts BOLD entity correctly, dood!"""
        tgEntity = telegram.MessageEntity(type=telegram.constants.MessageEntityType.BOLD, offset=0, length=5)
        entity = FormatEntity.fromTelegram(tgEntity)
        self.assertEqual(entity.type, FormatType.BOLD)
        self.assertEqual(entity.offset, 0)
        self.assertEqual(entity.length, 5)

    def testFromTelegramWithItalicEntity(self):
        """Test fromTelegram converts ITALIC entity correctly, dood!"""
        tgEntity = telegram.MessageEntity(type=telegram.constants.MessageEntityType.ITALIC, offset=2, length=8)
        entity = FormatEntity.fromTelegram(tgEntity)
        self.assertEqual(entity.type, FormatType.ITALIC)

    def testFromTelegramWithCodeEntity(self):
        """Test fromTelegram converts CODE entity correctly, dood!"""
        tgEntity = telegram.MessageEntity(type=telegram.constants.MessageEntityType.CODE, offset=5, length=10)
        entity = FormatEntity.fromTelegram(tgEntity)
        self.assertEqual(entity.type, FormatType.INLINE_CODE)

    def testFromTelegramWithStrikethroughEntity(self):
        """Test fromTelegram converts STRIKETHROUGH entity correctly, dood!"""
        tgEntity = telegram.MessageEntity(type=telegram.constants.MessageEntityType.STRIKETHROUGH, offset=0, length=7)
        entity = FormatEntity.fromTelegram(tgEntity)
        self.assertEqual(entity.type, FormatType.STRIKETHROUGH)

    def testFromTelegramWithUnderlineEntity(self):
        """Test fromTelegram converts UNDERLINE entity correctly, dood!"""
        tgEntity = telegram.MessageEntity(type=telegram.constants.MessageEntityType.UNDERLINE, offset=1, length=6)
        entity = FormatEntity.fromTelegram(tgEntity)
        self.assertEqual(entity.type, FormatType.UNDERLINE)

    def testFromTelegramWithSpoilerEntity(self):
        """Test fromTelegram converts SPOILER entity correctly, dood!"""
        tgEntity = telegram.MessageEntity(type=telegram.constants.MessageEntityType.SPOILER, offset=3, length=4)
        entity = FormatEntity.fromTelegram(tgEntity)
        self.assertEqual(entity.type, FormatType.SPOILER)

    def testFromTelegramWithBlockquoteEntity(self):
        """Test fromTelegram converts BLOCKQUOTE entity correctly, dood!"""
        tgEntity = telegram.MessageEntity(type=telegram.constants.MessageEntityType.BLOCKQUOTE, offset=0, length=20)
        entity = FormatEntity.fromTelegram(tgEntity)
        self.assertEqual(entity.type, FormatType.QUOTE)

    def testFromTelegramWithExpandableBlockquoteEntity(self):
        """Test fromTelegram converts EXPANDABLE_BLOCKQUOTE entity correctly, dood!"""
        tgEntity = telegram.MessageEntity(
            type=telegram.constants.MessageEntityType.EXPANDABLE_BLOCKQUOTE, offset=0, length=20
        )
        entity = FormatEntity.fromTelegram(tgEntity)
        self.assertEqual(entity.type, FormatType.QUOTE)

    def testFromTelegramWithPreEntity(self):
        """Test fromTelegram converts PRE entity correctly, dood!"""
        tgEntity = telegram.MessageEntity(
            type=telegram.constants.MessageEntityType.PRE, offset=0, length=50, language="python"
        )
        entity = FormatEntity.fromTelegram(tgEntity)
        self.assertEqual(entity.type, FormatType.CODE_BLOCK)
        self.assertEqual(entity.codeLanguage, "python")

    def testFromTelegramWithTextLinkEntity(self):
        """Test fromTelegram converts TEXT_LINK entity correctly, dood!"""
        tgEntity = telegram.MessageEntity(
            type=telegram.constants.MessageEntityType.TEXT_LINK,
            offset=0,
            length=10,
            url="https://example.com",
        )
        entity = FormatEntity.fromTelegram(tgEntity)
        self.assertEqual(entity.type, FormatType.LINK)
        self.assertEqual(entity.url, "https://example.com")

    def testFromTelegramWithUrlEntity(self):
        """Test fromTelegram converts URL entity correctly, dood!"""
        tgEntity = telegram.MessageEntity(type=telegram.constants.MessageEntityType.URL, offset=0, length=20)
        entity = FormatEntity.fromTelegram(tgEntity)
        self.assertEqual(entity.type, FormatType.LINK)

    def testFromTelegramWithTextMentionEntity(self):
        """Test fromTelegram converts TEXT_MENTION entity correctly, dood!"""
        mockUser = Mock()
        mockUser.id = 789
        mockUser.username = "testuser"
        tgEntity = telegram.MessageEntity(
            type=telegram.constants.MessageEntityType.TEXT_MENTION, offset=0, length=9, user=mockUser
        )
        entity = FormatEntity.fromTelegram(tgEntity)
        self.assertEqual(entity.type, FormatType.USER_MENTION)
        self.assertEqual(entity.userId, 789)
        self.assertEqual(entity.userName, "testuser")

    def testFromTelegramWithMentionEntity(self):
        """Test fromTelegram converts MENTION entity correctly, dood!"""
        tgEntity = telegram.MessageEntity(type=telegram.constants.MessageEntityType.MENTION, offset=0, length=9)
        entity = FormatEntity.fromTelegram(tgEntity)
        self.assertEqual(entity.type, FormatType.USER_MENTION)

    def testFromTelegramWithBotCommandEntity(self):
        """Test fromTelegram converts BOT_COMMAND to NORMAL, dood!"""
        tgEntity = telegram.MessageEntity(type=telegram.constants.MessageEntityType.BOT_COMMAND, offset=0, length=5)
        entity = FormatEntity.fromTelegram(tgEntity)
        self.assertEqual(entity.type, FormatType.NORMAL)

    def testFromTelegramWithHashtagEntity(self):
        """Test fromTelegram converts HASHTAG to NORMAL, dood!"""
        tgEntity = telegram.MessageEntity(type=telegram.constants.MessageEntityType.HASHTAG, offset=0, length=5)
        entity = FormatEntity.fromTelegram(tgEntity)
        self.assertEqual(entity.type, FormatType.NORMAL)

    def testFromTelegramWithEmailEntity(self):
        """Test fromTelegram converts EMAIL to NORMAL, dood!"""
        tgEntity = telegram.MessageEntity(type=telegram.constants.MessageEntityType.EMAIL, offset=0, length=15)
        entity = FormatEntity.fromTelegram(tgEntity)
        self.assertEqual(entity.type, FormatType.NORMAL)


# ============================================================================
# FormatEntity fromDict/toDict Tests
# ============================================================================


class TestFormatEntityDictConversion(unittest.TestCase):
    """Test cases for FormatEntity dictionary conversion methods, dood!"""

    def testToDictBasic(self):
        """Test toDict converts entity to dictionary correctly, dood!"""
        entity = FormatEntity(FormatType.BOLD, 0, 5)
        entityDict = entity.toDict()
        self.assertEqual(entityDict["type"], "bold")
        self.assertEqual(entityDict["offset"], 0)
        self.assertEqual(entityDict["length"], 5)
        # None values should not be in dictionary
        self.assertNotIn("url", entityDict)
        self.assertNotIn("userId", entityDict)

    def testToDictWithAllFields(self):
        """Test toDict includes all non-None fields, dood!"""
        entity = FormatEntity(
            FormatType.LINK,
            10,
            15,
            url="https://test.com",
            userId=123,
            userName="user",
            codeLanguage="python",
        )
        entityDict = entity.toDict()
        self.assertEqual(entityDict["type"], "link")
        self.assertEqual(entityDict["offset"], 10)
        self.assertEqual(entityDict["length"], 15)
        self.assertEqual(entityDict["url"], "https://test.com")
        self.assertEqual(entityDict["userId"], 123)
        self.assertEqual(entityDict["userName"], "user")
        self.assertEqual(entityDict["codeLanguage"], "python")

    def testFromDictBasic(self):
        """Test fromDict creates entity from dictionary correctly, dood!"""
        data = {"type": "bold", "offset": 5, "length": 10}
        entity = FormatEntity.fromDict(data)
        self.assertEqual(entity.type, FormatType.BOLD)
        self.assertEqual(entity.offset, 5)
        self.assertEqual(entity.length, 10)

    def testFromDictWithAllFields(self):
        """Test fromDict creates entity with all fields, dood!"""
        data = {
            "type": "link",
            "offset": 0,
            "length": 20,
            "url": "https://example.org",
            "userId": 999,
            "userName": "testname",
            "codeLanguage": "javascript",
        }
        entity = FormatEntity.fromDict(data)
        self.assertEqual(entity.type, FormatType.LINK)
        self.assertEqual(entity.url, "https://example.org")
        self.assertEqual(entity.userId, 999)
        self.assertEqual(entity.userName, "testname")
        self.assertEqual(entity.codeLanguage, "javascript")

    def testFromDictWithDefaults(self):
        """Test fromDict uses defaults for missing fields, dood!"""
        data = {}
        entity = FormatEntity.fromDict(data)
        self.assertEqual(entity.type, FormatType.UNSPECIFIED)
        self.assertEqual(entity.offset, 0)
        self.assertEqual(entity.length, 0)

    def testFromDictListEmpty(self):
        """Test fromDictList with empty list, dood!"""
        entities = FormatEntity.fromDictList([])
        self.assertEqual(len(entities), 0)

    def testFromDictListMultiple(self):
        """Test fromDictList with multiple dictionaries, dood!"""
        dataList = [
            {"type": "bold", "offset": 0, "length": 5},
            {"type": "italic", "offset": 10, "length": 8},
        ]
        entities = FormatEntity.fromDictList(dataList)
        self.assertEqual(len(entities), 2)
        self.assertEqual(entities[0].type, FormatType.BOLD)
        self.assertEqual(entities[1].type, FormatType.ITALIC)

    def testToDictListEmpty(self):
        """Test toDictList with empty list, dood!"""
        result = FormatEntity.toDictList([])
        self.assertEqual(len(result), 0)

    def testToDictListMultiple(self):
        """Test toDictList with multiple entities, dood!"""
        entities = [
            FormatEntity(FormatType.BOLD, 0, 5),
            FormatEntity(FormatType.ITALIC, 10, 8),
        ]
        dictList = FormatEntity.toDictList(entities)
        self.assertEqual(len(dictList), 2)
        self.assertEqual(dictList[0]["type"], "bold")
        self.assertEqual(dictList[1]["type"], "italic")


# ============================================================================
# FormatEntity String Representation Tests
# ============================================================================


class TestFormatEntityStringRepresentation(unittest.TestCase):
    """Test cases for FormatEntity string representation methods, dood!"""

    def testStrMethod(self):
        """Test __str__ returns JSON string, dood!"""
        entity = FormatEntity(FormatType.BOLD, 0, 5)
        strRepr = str(entity)
        self.assertIn("bold", strRepr)
        self.assertIn("offset", strRepr)
        self.assertIn("length", strRepr)

    def testReprMethod(self):
        """Test __repr__ returns constructor representation, dood!"""
        entity = FormatEntity(FormatType.BOLD, 0, 5)
        reprStr = repr(entity)
        self.assertIn("FormatEntity", reprStr)
        self.assertIn("bold", reprStr)


# ============================================================================
# FormatEntity fromList Tests
# ============================================================================


class TestFormatEntityFromList(unittest.TestCase):
    """Test cases for FormatEntity.fromList method, dood!"""

    def testFromListWithTelegramEntities(self):
        """Test fromList converts Telegram entities correctly, dood!"""
        tgEntities = [
            telegram.MessageEntity(type=telegram.constants.MessageEntityType.BOLD, offset=0, length=5),
            telegram.MessageEntity(type=telegram.constants.MessageEntityType.ITALIC, offset=10, length=8),
        ]
        entities = FormatEntity.fromList(tgEntities)
        self.assertEqual(len(entities), 2)
        self.assertEqual(entities[0].type, FormatType.BOLD)
        self.assertEqual(entities[1].type, FormatType.ITALIC)

    def testFromListWithMaxEntities(self):
        """Test fromList converts Max entities correctly, dood!"""
        maxEntities = [
            maxModels.MarkupElement(type=maxModels.MarkupType.STRONG, fromField=0, length=5),
            maxModels.MarkupElement(type=maxModels.MarkupType.EMPHASIZED, fromField=10, length=8),
        ]
        entities = FormatEntity.fromList(maxEntities)
        self.assertEqual(len(entities), 2)
        self.assertEqual(entities[0].type, FormatType.BOLD)
        self.assertEqual(entities[1].type, FormatType.ITALIC)

    def testFromListFiltersNormalType(self):
        """Test fromList filters out NORMAL type entities, dood!"""
        tgEntities = [
            telegram.MessageEntity(type=telegram.constants.MessageEntityType.BOLD, offset=0, length=5),
            telegram.MessageEntity(type=telegram.constants.MessageEntityType.HASHTAG, offset=10, length=8),
        ]
        entities = FormatEntity.fromList(tgEntities)
        # HASHTAG converts to NORMAL which should be filtered
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0].type, FormatType.BOLD)

    @patch("internal.bot.models.text_formatter.logger")
    def testFromListFiltersUnspecified(self, mockLogger):
        """Test fromList filters out UNSPECIFIED type entities, dood!"""
        maxEntities = [
            maxModels.MarkupElement(type=maxModels.MarkupType.STRONG, fromField=0, length=5),
            maxModels.MarkupElement(type=maxModels.MarkupType.UNSPECIFIED, fromField=10, length=8),
        ]
        entities = FormatEntity.fromList(maxEntities)
        # UNSPECIFIED should be filtered
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0].type, FormatType.BOLD)

    def testFromListWithInvalidType(self):
        """Test fromList raises ValueError with invalid entity type, dood!"""
        invalidEntities = ["not an entity"]  # type: ignore
        with self.assertRaises(ValueError) as context:
            FormatEntity.fromList(invalidEntities)  # type: ignore
        self.assertIn("Invalid entity type", str(context.exception))

    def testFromListEmpty(self):
        """Test fromList with empty list, dood!"""
        entities = FormatEntity.fromList([])
        self.assertEqual(len(entities), 0)


# ============================================================================
# FormatEntity formatText Tests
# ============================================================================


class TestFormatEntityFormatText(unittest.TestCase):
    """Test cases for FormatEntity.formatText method, dood!"""

    def testFormatTextBold(self):
        """Test formatText formats bold text correctly, dood!"""
        entity = FormatEntity(FormatType.BOLD, 0, 5)
        formatted = entity.formatText("hello")
        self.assertEqual(formatted, "**hello**")

    def testFormatTextItalic(self):
        """Test formatText formats italic text correctly, dood!"""
        entity = FormatEntity(FormatType.ITALIC, 0, 5)
        formatted = entity.formatText("hello")
        self.assertEqual(formatted, "_hello_")

    def testFormatTextInlineCode(self):
        """Test formatText formats inline code correctly, dood!"""
        entity = FormatEntity(FormatType.INLINE_CODE, 0, 5)
        formatted = entity.formatText("code")
        self.assertEqual(formatted, "`code`")

    def testFormatTextStrikethrough(self):
        """Test formatText formats strikethrough text correctly, dood!"""
        entity = FormatEntity(FormatType.STRIKETHROUGH, 0, 5)
        formatted = entity.formatText("text")
        self.assertEqual(formatted, "~~text~~")

    def testFormatTextUnderline(self):
        """Test formatText formats underline text correctly, dood!"""
        entity = FormatEntity(FormatType.UNDERLINE, 0, 5)
        formatted = entity.formatText("text")
        self.assertEqual(formatted, "++text++")

    def testFormatTextSpoiler(self):
        """Test formatText formats spoiler text correctly, dood!"""
        entity = FormatEntity(FormatType.SPOILER, 0, 5)
        formatted = entity.formatText("secret")
        self.assertEqual(formatted, "||secret||")

    def testFormatTextHeading(self):
        """Test formatText formats heading correctly, dood!"""
        entity = FormatEntity(FormatType.HEADING, 0, 5)
        formatted = entity.formatText("Title")
        self.assertEqual(formatted, "# Title")

    def testFormatTextHeadingMultiline(self):
        """Test formatText formats multiline heading correctly, dood!"""
        entity = FormatEntity(FormatType.HEADING, 0, 10)
        formatted = entity.formatText("Line 1\nLine 2")
        self.assertEqual(formatted, "# Line 1\n# Line 2")

    def testFormatTextQuote(self):
        """Test formatText formats quote correctly, dood!"""
        entity = FormatEntity(FormatType.QUOTE, 0, 5)
        formatted = entity.formatText("quote")
        self.assertEqual(formatted, "> quote")

    def testFormatTextQuoteMultiline(self):
        """Test formatText formats multiline quote correctly, dood!"""
        entity = FormatEntity(FormatType.QUOTE, 0, 10)
        formatted = entity.formatText("Line 1\nLine 2")
        self.assertEqual(formatted, "> Line 1\n> Line 2")

    def testFormatTextQuoteMarkdownMax(self):
        """Test formatText formats quote with newlines for MAX format, dood!"""
        entity = FormatEntity(FormatType.QUOTE, 0, 5)
        formatted = entity.formatText("quote", OutputFormat.MARKDOWN_MAX)
        self.assertEqual(formatted, "\n> quote\n")

    def testFormatTextCodeBlock(self):
        """Test formatText formats code block correctly, dood!"""
        entity = FormatEntity(FormatType.CODE_BLOCK, 0, 10)
        formatted = entity.formatText("print('hi')")
        self.assertEqual(formatted, "```\nprint('hi')\n```")

    def testFormatTextCodeBlockWithLanguage(self):
        """Test formatText formats code block with language, dood!"""
        entity = FormatEntity(FormatType.CODE_BLOCK, 0, 10, codeLanguage="python")
        formatted = entity.formatText("print('hi')")
        self.assertEqual(formatted, "```python\nprint('hi')\n```")

    def testFormatTextLink(self):
        """Test formatText formats link correctly, dood!"""
        entity = FormatEntity(FormatType.LINK, 0, 5, url="https://test.com")
        formatted = entity.formatText("link")
        self.assertEqual(formatted, "[link](https://test.com)")

    def testFormatTextLinkWithoutUrl(self):
        """Test formatText uses text as URL when url is None, dood!"""
        entity = FormatEntity(FormatType.LINK, 0, 5)
        formatted = entity.formatText("https://auto.com")
        self.assertEqual(formatted, "[https://auto.com](https://auto.com)")

    def testFormatTextUserMentionWithUsername(self):
        """Test formatText formats user mention with username, dood!"""
        entity = FormatEntity(FormatType.USER_MENTION, 0, 5, userName="testuser")
        formatted = entity.formatText("user")
        self.assertEqual(formatted, "@testuser")

    def testFormatTextUserMentionWithUsernameNoAt(self):
        """Test formatText adds @ to username if missing, dood!"""
        entity = FormatEntity(FormatType.USER_MENTION, 0, 5, userName="testuser")
        formatted = entity.formatText("user")
        self.assertEqual(formatted, "@testuser")

    def testFormatTextUserMentionWithUserIdMarkdown(self):
        """Test formatText formats user mention with userId in markdown, dood!"""
        entity = FormatEntity(FormatType.USER_MENTION, 0, 5, userId=123)
        formatted = entity.formatText("user", OutputFormat.MARKDOWN)
        self.assertEqual(formatted, "[user](123)")

    def testFormatTextUserMentionWithUserIdTelegram(self):
        """Test formatText formats user mention with userId for Telegram, dood!"""
        entity = FormatEntity(FormatType.USER_MENTION, 0, 5, userId=123)
        formatted = entity.formatText("user", OutputFormat.MARKDOWN_TG)
        self.assertEqual(formatted, "[user](tg://user?id=123)")

    def testFormatTextUserMentionWithUserIdMax(self):
        """Test formatText formats user mention with userId for Max, dood!"""
        entity = FormatEntity(FormatType.USER_MENTION, 0, 5, userId=123)
        formatted = entity.formatText("user", OutputFormat.MARKDOWN_MAX)
        self.assertEqual(formatted, "[user](max://max.ru/123)")

    def testFormatTextUserMentionNoData(self):
        """Test formatText returns text when no user data, dood!"""
        entity = FormatEntity(FormatType.USER_MENTION, 0, 5)
        formatted = entity.formatText("user")
        self.assertEqual(formatted, "user")

    def testFormatTextUserMentionInvalidFormat(self):
        """Test formatText raises error for invalid output format, dood!"""
        entity = FormatEntity(FormatType.USER_MENTION, 0, 5, userId=123)
        with self.assertRaises(ValueError) as context:
            entity.formatText("user", "invalid-format")  # type: ignore
        self.assertIn("Unsupported output format", str(context.exception))

    def testFormatTextNormal(self):
        """Test formatText returns text unchanged for NORMAL type, dood!"""
        entity = FormatEntity(FormatType.NORMAL, 0, 5)
        formatted = entity.formatText("normal")
        self.assertEqual(formatted, "normal")

    @patch("internal.bot.models.text_formatter.logger")
    def testFormatTextUnspecified(self, mockLogger):
        """Test formatText logs error for UNSPECIFIED type, dood!"""
        entity = FormatEntity(FormatType.UNSPECIFIED, 0, 5)
        formatted = entity.formatText("text")
        self.assertEqual(formatted, "text")
        mockLogger.error.assert_called()

    def testFormatTextWithLeadingWhitespace(self):
        """Test formatText preserves leading whitespace, dood!"""
        entity = FormatEntity(FormatType.BOLD, 0, 7)
        formatted = entity.formatText("  hello")
        self.assertEqual(formatted, "  **hello**")

    def testFormatTextWithTrailingWhitespace(self):
        """Test formatText preserves trailing whitespace, dood!"""
        entity = FormatEntity(FormatType.BOLD, 0, 7)
        formatted = entity.formatText("hello  ")
        self.assertEqual(formatted, "**hello**  ")

    def testFormatTextWithBothWhitespace(self):
        """Test formatText preserves both leading and trailing whitespace, dood!"""
        entity = FormatEntity(FormatType.BOLD, 0, 9)
        formatted = entity.formatText("  hello  ")
        self.assertEqual(formatted, "  **hello**  ")

    def testFormatTextEmptyBody(self):
        """Test formatText returns text unchanged when body is empty, dood!"""
        entity = FormatEntity(FormatType.BOLD, 0, 2)
        formatted = entity.formatText("  ")
        self.assertEqual(formatted, "  ")


# ============================================================================
# FormatEntity parseText Tests
# ============================================================================


class TestFormatEntityParseText(unittest.TestCase):
    """Test cases for FormatEntity.parseText method, dood!"""

    def testParseTextNoEntities(self):
        """Test parseText with no entities returns text unchanged, dood!"""
        text = "Hello world"
        result = FormatEntity.parseText(text, [])
        self.assertEqual(result, text)

    def testParseTextSingleBoldEntity(self):
        """Test parseText with single bold entity, dood!"""
        text = "Hello world"
        entities = [FormatEntity(FormatType.BOLD, 0, 5)]
        result = FormatEntity.parseText(text, entities)
        self.assertEqual(result, "**Hello** world")

    def testParseTextMultipleEntities(self):
        """Test parseText with multiple non-overlapping entities, dood!"""
        text = "Hello world test"
        entities = [
            FormatEntity(FormatType.BOLD, 0, 5),
            FormatEntity(FormatType.ITALIC, 6, 5),
        ]
        result = FormatEntity.parseText(text, entities)
        self.assertEqual(result, "**Hello** _world_ test")

    def testParseTextNestedEntities(self):
        """Test parseText with nested entities, dood!"""
        text = "Hello world"
        entities = [
            FormatEntity(FormatType.BOLD, 0, 11),
            FormatEntity(FormatType.ITALIC, 6, 5),
        ]
        result = FormatEntity.parseText(text, entities)
        self.assertEqual(result, "**Hello _world_**")

    def testParseTextWithUnicodeCharacters(self):
        """Test parseText handles Unicode characters correctly, dood!"""
        text = "Привет мир"
        entities = [FormatEntity(FormatType.BOLD, 0, 6)]
        result = FormatEntity.parseText(text, entities)
        self.assertEqual(result, "**Привет** мир")

    def testParseTextWithEmoji(self):
        """Test parseText handles emoji correctly, dood!"""
        text = "Hello 👋 world"
        # Emoji takes 2 UTF-16 code units
        entities = [FormatEntity(FormatType.BOLD, 0, 5)]
        result = FormatEntity.parseText(text, entities)
        self.assertIn("**Hello**", result)

    def testParseTextWithLink(self):
        """Test parseText formats link correctly, dood!"""
        text = "Click here"
        entities = [FormatEntity(FormatType.LINK, 6, 4, url="https://test.com")]
        result = FormatEntity.parseText(text, entities)
        self.assertEqual(result, "Click [here](https://test.com)")

    def testParseTextWithCodeBlock(self):
        """Test parseText formats code block correctly, dood!"""
        text = "Check this code"
        entities = [FormatEntity(FormatType.CODE_BLOCK, 11, 4, codeLanguage="py")]
        result = FormatEntity.parseText(text, entities)
        self.assertEqual(result, "Check this ```py\ncode\n```")

    def testParseTextEntitiesSortedByOffset(self):
        """Test parseText sorts entities by offset, dood!"""
        text = "First second third"
        # Provide entities in wrong order
        entities = [
            FormatEntity(FormatType.ITALIC, 13, 5),
            FormatEntity(FormatType.BOLD, 0, 5),
        ]
        result = FormatEntity.parseText(text, entities)
        self.assertEqual(result, "**First** second _third_")

    def testParseTextWithBytesInput(self):
        """Test parseText handles bytes input correctly, dood!"""
        text = "Hello world"
        textBytes = text.encode(FORMATER_ENCODING)
        entities = [FormatEntity(FormatType.BOLD, 0, 5)]
        result = FormatEntity.parseText(textBytes, entities)
        self.assertEqual(result, "**Hello** world")

    @patch("internal.bot.models.text_formatter.logger")
    def testParseTextWithDecodeError(self, mockLogger):
        """Test parseText handles decode errors gracefully, dood!"""
        # Create invalid UTF-16 bytes
        invalidBytes = b"\xff\xfe\x00\xd8"  # Invalid surrogate pair
        entities = []
        result = FormatEntity.parseText(invalidBytes, entities)
        # Should not crash and should log error
        self.assertIsInstance(result, str)
        mockLogger.error.assert_called()

    def testParseTextComplexNesting(self):
        """Test parseText with complex nested entities, dood!"""
        text = "This is complex text"
        entities = [
            FormatEntity(FormatType.BOLD, 0, 20),
            FormatEntity(FormatType.ITALIC, 8, 7),
            FormatEntity(FormatType.INLINE_CODE, 8, 7),
        ]
        result = FormatEntity.parseText(text, entities)
        # Should handle complex nesting
        self.assertIn("**", result)
        self.assertIn("_", result)

    def testParseTextWithDifferentOutputFormat(self):
        """Test parseText respects output format parameter, dood!"""
        text = "Quoted text"
        entities = [FormatEntity(FormatType.QUOTE, 0, 11)]
        resultMarkdown = FormatEntity.parseText(text, entities, OutputFormat.MARKDOWN)
        resultMax = FormatEntity.parseText(text, entities, OutputFormat.MARKDOWN_MAX)
        # MAX format should add newlines around quotes
        self.assertNotEqual(resultMarkdown, resultMax)


# ============================================================================
# FormatEntity extractEntityText Tests
# ============================================================================


class TestFormatEntityExtractText(unittest.TestCase):
    """Test cases for FormatEntity.extractEntityText method, dood!"""

    def testExtractEntityTextBasic(self):
        """Test extractEntityText extracts correct substring, dood!"""
        text = "Hello world"
        entity = FormatEntity(FormatType.BOLD, 0, 5)
        extracted = entity.extractEntityText(text)
        self.assertEqual(extracted, "Hello")

    def testExtractEntityTextMiddle(self):
        """Test extractEntityText extracts from middle of text, dood!"""
        text = "Hello world test"
        entity = FormatEntity(FormatType.BOLD, 6, 5)
        extracted = entity.extractEntityText(text)
        self.assertEqual(extracted, "world")

    def testExtractEntityTextEnd(self):
        """Test extractEntityText extracts from end of text, dood!"""
        text = "Hello world"
        entity = FormatEntity(FormatType.BOLD, 6, 5)
        extracted = entity.extractEntityText(text)
        self.assertEqual(extracted, "world")

    def testExtractEntityTextWithUnicode(self):
        """Test extractEntityText handles Unicode correctly, dood!"""
        text = "Привет мир"
        entity = FormatEntity(FormatType.BOLD, 0, 6)
        extracted = entity.extractEntityText(text)
        self.assertEqual(extracted, "Привет")

    def testExtractEntityTextWithEmoji(self):
        """Test extractEntityText handles emoji correctly, dood!"""
        text = "Hello 👋 world"
        # Note: emoji positioning depends on UTF-16 encoding
        entity = FormatEntity(FormatType.BOLD, 0, 5)
        extracted = entity.extractEntityText(text)
        self.assertEqual(extracted, "Hello")

    @patch("internal.bot.models.text_formatter.logger")
    def testExtractEntityTextDecodeError(self, mockLogger):
        """Test extractEntityText handles decode errors, dood!"""
        text = "Hello world"
        # Create entity that would cause issues
        entity = FormatEntity(FormatType.BOLD, 0, 5)
        # Mock the encoding to cause an error
        with patch.object(entity, "offset", 100):
            # This should handle the error gracefully
            result = entity.extractEntityText(text)
            self.assertIsInstance(result, str)

    def testExtractEntityTextBytesInput(self):
        """Test extractEntityText handles bytes input, dood!"""
        text = "Hello world"
        textBytes = text.encode(FORMATER_ENCODING)
        entity = FormatEntity(FormatType.BOLD, 0, 5)
        extracted = entity.extractEntityText(textBytes)  # type: ignore
        self.assertEqual(extracted, "Hello")


# ============================================================================
# Integration Tests
# ============================================================================


class TestFormatEntityIntegration(unittest.TestCase):
    """Integration tests for FormatEntity with complex scenarios, dood!"""

    def testFullWorkflowTelegramToMarkdown(self):
        """Test complete workflow from Telegram entities to Markdown, dood!"""
        text = "Hello bold world"
        tgEntity = telegram.MessageEntity(type=telegram.constants.MessageEntityType.BOLD, offset=6, length=4)
        entity = FormatEntity.fromTelegram(tgEntity)
        result = FormatEntity.parseText(text, [entity])
        self.assertEqual(result, "Hello **bold** world")

    def testFullWorkflowMaxToMarkdown(self):
        """Test complete workflow from Max entities to Markdown, dood!"""
        text = "Hello italic world"
        maxEntity = maxModels.MarkupElement(type=maxModels.MarkupType.EMPHASIZED, fromField=6, length=6)
        entity = FormatEntity.fromMax(maxEntity)
        result = FormatEntity.parseText(text, [entity])
        self.assertEqual(result, "Hello _italic_ world")

    def testComplexMessageWithMultipleFormats(self):
        """Test complex message with multiple format types, dood!"""
        text = "Bold text, italic text, and code"
        entities = [
            FormatEntity(FormatType.BOLD, 0, 4),
            FormatEntity(FormatType.ITALIC, 11, 6),
            FormatEntity(FormatType.INLINE_CODE, 28, 4),
        ]
        result = FormatEntity.parseText(text, entities)
        self.assertEqual(result, "**Bold** text, _italic_ text, and `code`")

    def testRoundTripToDictAndBack(self):
        """Test entity can be converted to dict and back, dood!"""
        originalEntity = FormatEntity(FormatType.LINK, 5, 10, url="https://test.com", userId=123, userName="user")
        entityDict = originalEntity.toDict()
        restoredEntity = FormatEntity.fromDict(entityDict)

        self.assertEqual(originalEntity.type, restoredEntity.type)
        self.assertEqual(originalEntity.offset, restoredEntity.offset)
        self.assertEqual(originalEntity.length, restoredEntity.length)
        self.assertEqual(originalEntity.url, restoredEntity.url)
        self.assertEqual(originalEntity.userId, restoredEntity.userId)
        self.assertEqual(originalEntity.userName, restoredEntity.userName)

    def testMessageWithAllFormatTypes(self):
        """Test message containing all supported format types, dood!"""
        # This is more of a smoke test to ensure no crashes
        text = "A" * 100  # Long text to accommodate all entities
        entities = [
            FormatEntity(FormatType.BOLD, 0, 5),
            FormatEntity(FormatType.ITALIC, 6, 5),
            FormatEntity(FormatType.INLINE_CODE, 12, 5),
            FormatEntity(FormatType.STRIKETHROUGH, 18, 5),
            FormatEntity(FormatType.UNDERLINE, 24, 5),
            FormatEntity(FormatType.SPOILER, 30, 5),
            FormatEntity(FormatType.LINK, 36, 5, url="https://test.com"),
            FormatEntity(FormatType.USER_MENTION, 42, 5, userName="user"),
        ]
        result = FormatEntity.parseText(text, entities)
        # Just verify it doesn't crash and returns a string
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)


if __name__ == "__main__":
    unittest.main()
