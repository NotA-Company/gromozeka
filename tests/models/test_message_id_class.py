"""Unit tests for MessageIdClass in internal.models.types.

Covers initialization, copy, type conversion (asStr, asInt, asMessageId),
string representation (__str__, __repr__), equality (__eq__), and
hashing (__hash__), including edge cases and error paths.
"""

import unittest
from unittest.mock import patch

from internal.models.types import MessageIdClass


class TestMessageIdClassInit(unittest.TestCase):
    """Tests for MessageIdClass.__init__."""

    def testInitWithInt(self):
        """Test initialization with an integer message ID."""
        msgId = MessageIdClass(42)
        self.assertEqual(msgId.messageId, 42)

    def testInitWithStr(self):
        """Test initialization with a string message ID."""
        msgId = MessageIdClass("msg_abc123")
        self.assertEqual(msgId.messageId, "msg_abc123")

    def testInitWithNegativeInt(self):
        """Test initialization with a negative integer (group chat IDs)."""
        msgId = MessageIdClass(-100123456)
        self.assertEqual(msgId.messageId, -100123456)

    def testInitWithZeroInt(self):
        """Test initialization with zero."""
        msgId = MessageIdClass(0)
        self.assertEqual(msgId.messageId, 0)

    def testInitWithEmptyStr(self):
        """Test initialization with an empty string."""
        msgId = MessageIdClass("")
        self.assertEqual(msgId.messageId, "")

    def testInitFromCopy(self):
        """Test initialization from another MessageIdClass instance copies the value."""
        original = MessageIdClass(99)
        copy = MessageIdClass(original)
        self.assertEqual(copy.messageId, 99)
        self.assertIsNot(copy, original)

    def testInitFromCopyStr(self):
        """Test initialization from a string-based MessageIdClass copies the value."""
        original = MessageIdClass("abc")
        copy = MessageIdClass(original)
        self.assertEqual(copy.messageId, "abc")

    def testInitWithInvalidTypeRaisesValueError(self):
        """Test initialization with an unsupported type raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            MessageIdClass(3.14)  # type: ignore[arg-type]
        self.assertIn("float", str(ctx.exception))

    def testInitWithNoneRaisesValueError(self):
        """Test initialization with None raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            MessageIdClass(None)  # type: ignore[arg-type]
        self.assertIn("NoneType", str(ctx.exception))

    def testInitWithListRaisesValueError(self):
        """Test initialization with a list raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            MessageIdClass([1, 2])  # type: ignore[arg-type]
        self.assertIn("list", str(ctx.exception))

    def testInitWithBoolNotRaisesValueError(self):
        """Test initialization with a bool raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            MessageIdClass(True)  # type: ignore[arg-type]
        self.assertIn("bool", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            MessageIdClass(False)  # type: ignore[arg-type]
        self.assertIn("bool", str(ctx.exception))


class TestMessageIdClassCopy(unittest.TestCase):
    """Tests for MessageIdClass.copy."""

    def testCopyReturnsNewInstance(self):
        """Test copy returns a distinct instance with the same value."""
        original = MessageIdClass(42)
        copied = original.copy()
        self.assertEqual(copied.messageId, original.messageId)
        self.assertIsNot(copied, original)

    def testCopyStrBased(self):
        """Test copy of a string-based instance."""
        original = MessageIdClass("msg_xyz")
        copied = original.copy()
        self.assertEqual(copied.messageId, "msg_xyz")
        self.assertIsNot(copied, original)

    def testCopyIsIndependent(self):
        """Test that modifying the copy does not affect the original."""
        original = MessageIdClass(10)
        copied = original.copy()
        self.assertEqual(copied.messageId, 10)
        self.assertEqual(original.messageId, 10)


class TestMessageIdClassAsStr(unittest.TestCase):
    """Tests for MessageIdClass.asStr."""

    def testAsStrFromInt(self):
        """Test asStr converts an integer ID to its string representation."""
        msgId = MessageIdClass(42)
        self.assertEqual(msgId.asStr(), "42")

    def testAsStrFromStr(self):
        """Test asStr returns the string ID unchanged."""
        msgId = MessageIdClass("msg_abc")
        self.assertEqual(msgId.asStr(), "msg_abc")

    def testAsStrFromNegativeInt(self):
        """Test asStr converts a negative integer ID to string."""
        msgId = MessageIdClass(-100)
        self.assertEqual(msgId.asStr(), "-100")

    def testAsStrFromZero(self):
        """Test asStr converts zero to '0'."""
        msgId = MessageIdClass(0)
        self.assertEqual(msgId.asStr(), "0")

    def testAsStrFromEmptyStr(self):
        """Test asStr returns an empty string unchanged."""
        msgId = MessageIdClass("")
        self.assertEqual(msgId.asStr(), "")


class TestMessageIdClassAsInt(unittest.TestCase):
    """Tests for MessageIdClass.asInt."""

    def testAsIntFromInt(self):
        """Test asInt returns an integer ID directly."""
        msgId = MessageIdClass(42)
        self.assertEqual(msgId.asInt(), 42)
        self.assertIsInstance(msgId.asInt(), int)

    def testAsIntFromNumericStr(self):
        """Test asInt parses a numeric string as an integer."""
        msgId = MessageIdClass("42")
        self.assertEqual(msgId.asInt(), 42)
        self.assertIsInstance(msgId.asInt(), int)

    def testAsIntFromNegativeNumericStr(self):
        """Test asInt parses a negative numeric string."""
        msgId = MessageIdClass("-100")
        self.assertEqual(msgId.asInt(), -100)

    def testAsIntFromNonNumericStrRaisesValueError(self):
        """Test asInt raises ValueError for a non-numeric string."""
        msgId = MessageIdClass("msg_abc")
        with self.assertRaises(ValueError) as ctx:
            msgId.asInt()
        self.assertIn("not an integer", str(ctx.exception))

    def testAsIntFromEmptyStrRaisesValueError(self):
        """Test asInt raises ValueError for an empty string."""
        msgId = MessageIdClass("")
        with self.assertRaises(ValueError):
            msgId.asInt()


class TestMessageIdClassAsMessageId(unittest.TestCase):
    """Tests for MessageIdClass.asMessageId."""

    def testAsMessageIdFromInt(self):
        """Test asMessageId returns an int when the underlying value is int."""
        msgId = MessageIdClass(42)
        self.assertEqual(msgId.asMessageId(), 42)
        self.assertIsInstance(msgId.asMessageId(), int)

    def testAsMessageIdFromNumericStr(self):
        """Test asMessageId returns an int when the string is numeric."""
        msgId = MessageIdClass("42")
        self.assertEqual(msgId.asMessageId(), 42)
        self.assertIsInstance(msgId.asMessageId(), int)

    def testAsMessageIdFromNonNumericStr(self):
        """Test asMessageId returns a string when the string is non-numeric."""
        msgId = MessageIdClass("msg_abc")
        result = msgId.asMessageId()
        self.assertEqual(result, "msg_abc")
        self.assertIsInstance(result, str)

    def testAsMessageIdFromEmptyStr(self):
        """Test asMessageId returns a string when the string is empty."""
        msgId = MessageIdClass("")
        result = msgId.asMessageId()
        self.assertEqual(result, "")
        self.assertIsInstance(result, str)

    def testAsMessageIdFromNegativeNumericStr(self):
        """Test asMessageId returns int for a negative numeric string."""
        msgId = MessageIdClass("-5")
        self.assertEqual(msgId.asMessageId(), -5)


class TestMessageIdClassStrRepr(unittest.TestCase):
    """Tests for MessageIdClass.__str__ and __repr__."""

    def testStrFromInt(self):
        """Test __str__ returns the string form of an int ID."""
        msgId = MessageIdClass(42)
        self.assertEqual(str(msgId), "42")

    def testStrFromStr(self):
        """Test __str__ returns the string ID unchanged."""
        msgId = MessageIdClass("msg_abc")
        self.assertEqual(str(msgId), "msg_abc")

    def testReprFromInt(self):
        """Test __repr__ includes the class name and int value."""
        msgId = MessageIdClass(42)
        self.assertEqual(repr(msgId), "MessageIdClass(messageId=42)")

    def testReprFromStr(self):
        """Test __repr__ includes the class name and string value."""
        msgId = MessageIdClass("msg_abc")
        self.assertEqual(repr(msgId), "MessageIdClass(messageId=msg_abc)")


class TestMessageIdClassEquality(unittest.TestCase):
    """Tests for MessageIdClass.__eq__."""

    def testEqualSameInt(self):
        """Test two MessageIdClass instances with the same int are equal."""
        self.assertEqual(MessageIdClass(42), MessageIdClass(42))

    def testNotEqualDifferentInt(self):
        """Test two MessageIdClass instances with different ints are not equal."""
        self.assertNotEqual(MessageIdClass(42), MessageIdClass(99))

    def testEqualSameStr(self):
        """Test two MessageIdClass instances with the same string are equal."""
        self.assertEqual(MessageIdClass("abc"), MessageIdClass("abc"))

    def testNotEqualDifferentStr(self):
        """Test two MessageIdClass instances with different strings are not equal."""
        self.assertNotEqual(MessageIdClass("abc"), MessageIdClass("xyz"))

    def testEqualIntAndStrSameValue(self):
        """Test int and str MessageIdClass with the same numeric value are equal."""
        self.assertEqual(MessageIdClass(42), MessageIdClass("42"))

    def testEqualWithInt(self):
        """Test MessageIdClass(42) equals the integer 42."""
        self.assertEqual(MessageIdClass(42), 42)

    def testNotEqualWithInt(self):
        """Test MessageIdClass(99) does not equal the integer 42."""
        self.assertNotEqual(MessageIdClass(99), 42)

    def testEqualWithStr(self):
        """Test MessageIdClass('abc') equals the string 'abc'."""
        self.assertEqual(MessageIdClass("abc"), "abc")

    def testNotEqualWithStr(self):
        """Test MessageIdClass('abc') does not equal the string 'xyz'."""
        self.assertNotEqual(MessageIdClass("abc"), "xyz")

    def testEqualNumericStrWithInt(self):
        """Test MessageIdClass('42') equals the integer 42 via asMessageId."""
        self.assertEqual(MessageIdClass("42"), 42)

    def testNotEqualNonNumericStrWithInt(self):
        """Test MessageIdClass('abc') does not equal the integer 42."""
        self.assertNotEqual(MessageIdClass("abc"), 42)

    def testEqualWithBoolReturnsFalse(self):
        """Test MessageIdClass never equals a bool, even if value matches."""
        self.assertNotEqual(MessageIdClass(1), True)
        self.assertNotEqual(MessageIdClass(0), False)
        self.assertNotEqual(MessageIdClass(1), False)
        self.assertNotEqual(MessageIdClass(0), True)

    def testNotEqualWithNone(self):
        """Test MessageIdClass does not equal None."""
        self.assertNotEqual(MessageIdClass(42), None)

    @patch("internal.models.types.logger")
    def testEqualWithUnsupportedTypeLogsWarning(self, mockLogger):
        """Test comparison with an unsupported type logs a warning."""
        msgId = MessageIdClass(42)
        result = msgId == [1, 2]
        self.assertFalse(result)
        mockLogger.warning.assert_called_once()
        self.assertIn("list", mockLogger.warning.call_args[0][0])

    @patch("internal.models.types.logger")
    def testEqualWithUnsupportedTypeComparesStr(self, mockLogger):
        """Test comparison with an unsupported type falls back to string comparison."""
        msgId = MessageIdClass(42)
        result = msgId == [1, 2]
        self.assertFalse(result)


class TestMessageIdClassHash(unittest.TestCase):
    """Tests for MessageIdClass.__hash__."""

    def testHashConsistentWithEquality(self):
        """Test that equal instances produce the same hash."""
        a = MessageIdClass(42)
        b = MessageIdClass(42)
        self.assertEqual(hash(a), hash(b))

    def testHashIntAndStrSameValue(self):
        """Test that MessageIdClass(42) and MessageIdClass('42') have the same hash."""
        a = MessageIdClass(42)
        b = MessageIdClass("42")
        self.assertEqual(hash(a), hash(b))

    def testHashDifferentValuesDiffer(self):
        """Test that different values generally produce different hashes."""
        a = MessageIdClass(42)
        b = MessageIdClass(99)
        self.assertNotEqual(hash(a), hash(b))

    def testUsableAsDictKey(self):
        """Test MessageIdClass instances can be used as dictionary keys."""
        d = {MessageIdClass(1): "one", MessageIdClass("abc"): "abc"}
        self.assertEqual(d[MessageIdClass(1)], "one")
        self.assertEqual(d[MessageIdClass("abc")], "abc")

    def testUsableInSet(self):
        """Test MessageIdClass instances can be used in sets."""
        s = {MessageIdClass(1), MessageIdClass(2), MessageIdClass(1)}
        self.assertEqual(len(s), 2)

    def testSetDeduplicatesIntAndStrSameValue(self):
        """Test that int and str MessageIdClass with the same value are deduplicated in a set."""
        s = {MessageIdClass(42), MessageIdClass("42")}
        self.assertEqual(len(s), 1)


if __name__ == "__main__":
    unittest.main()
