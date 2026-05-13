"""Unit tests for MessageId in internal.models.types.

Covers initialization, copy, type conversion (asStr, asInt, asMessageId),
string representation (__str__, __repr__), equality (__eq__), and
hashing (__hash__), including edge cases and error paths.
"""

import unittest
from unittest.mock import patch

from internal.models.types import MessageId


class TestMessageIdInit(unittest.TestCase):
    """Tests for MessageId.__init__."""

    def testInitWithInt(self):
        """Test initialization with an integer message ID."""
        msgId = MessageId(42)
        self.assertEqual(msgId.messageId, 42)

    def testInitWithStr(self):
        """Test initialization with a string message ID."""
        msgId = MessageId("msg_abc123")
        self.assertEqual(msgId.messageId, "msg_abc123")

    def testInitWithNegativeInt(self):
        """Test initialization with a negative integer (group chat IDs)."""
        msgId = MessageId(-100123456)
        self.assertEqual(msgId.messageId, -100123456)

    def testInitWithZeroInt(self):
        """Test initialization with zero."""
        msgId = MessageId(0)
        self.assertEqual(msgId.messageId, 0)

    def testInitWithEmptyStr(self):
        """Test initialization with an empty string."""
        msgId = MessageId("")
        self.assertEqual(msgId.messageId, "")

    def testInitFromCopy(self):
        """Test initialization from another MessageId instance copies the value."""
        original = MessageId(99)
        copy = MessageId(original)
        self.assertEqual(copy.messageId, 99)
        self.assertIsNot(copy, original)

    def testInitFromCopyStr(self):
        """Test initialization from a string-based MessageId copies the value."""
        original = MessageId("abc")
        copy = MessageId(original)
        self.assertEqual(copy.messageId, "abc")

    def testInitWithInvalidTypeRaisesValueError(self):
        """Test initialization with an unsupported type raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            MessageId(3.14)  # type: ignore[arg-type]
        self.assertIn("float", str(ctx.exception))

    def testInitWithNoneRaisesValueError(self):
        """Test initialization with None raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            MessageId(None)  # type: ignore[arg-type]
        self.assertIn("NoneType", str(ctx.exception))

    def testInitWithListRaisesValueError(self):
        """Test initialization with a list raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            MessageId([1, 2])  # type: ignore[arg-type]
        self.assertIn("list", str(ctx.exception))

    def testInitWithBoolNotRaisesValueError(self):
        """Test initialization with a bool raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            MessageId(True)  # type: ignore[arg-type]
        self.assertIn("bool", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            MessageId(False)  # type: ignore[arg-type]
        self.assertIn("bool", str(ctx.exception))


class TestMessageIdCopy(unittest.TestCase):
    """Tests for MessageId.copy."""

    def testCopyReturnsNewInstance(self):
        """Test copy returns a distinct instance with the same value."""
        original = MessageId(42)
        copied = original.copy()
        self.assertEqual(copied.messageId, original.messageId)
        self.assertIsNot(copied, original)

    def testCopyStrBased(self):
        """Test copy of a string-based instance."""
        original = MessageId("msg_xyz")
        copied = original.copy()
        self.assertEqual(copied.messageId, "msg_xyz")
        self.assertIsNot(copied, original)

    def testCopyIsIndependent(self):
        """Test that modifying the copy does not affect the original."""
        original = MessageId(10)
        copied = original.copy()
        self.assertEqual(copied.messageId, 10)
        self.assertEqual(original.messageId, 10)


class TestMessageIdAsStr(unittest.TestCase):
    """Tests for MessageId.asStr."""

    def testAsStrFromInt(self):
        """Test asStr converts an integer ID to its string representation."""
        msgId = MessageId(42)
        self.assertEqual(msgId.asStr(), "42")

    def testAsStrFromStr(self):
        """Test asStr returns the string ID unchanged."""
        msgId = MessageId("msg_abc")
        self.assertEqual(msgId.asStr(), "msg_abc")

    def testAsStrFromNegativeInt(self):
        """Test asStr converts a negative integer ID to string."""
        msgId = MessageId(-100)
        self.assertEqual(msgId.asStr(), "-100")

    def testAsStrFromZero(self):
        """Test asStr converts zero to '0'."""
        msgId = MessageId(0)
        self.assertEqual(msgId.asStr(), "0")

    def testAsStrFromEmptyStr(self):
        """Test asStr returns an empty string unchanged."""
        msgId = MessageId("")
        self.assertEqual(msgId.asStr(), "")


class TestMessageIdAsInt(unittest.TestCase):
    """Tests for MessageId.asInt."""

    def testAsIntFromInt(self):
        """Test asInt returns an integer ID directly."""
        msgId = MessageId(42)
        self.assertEqual(msgId.asInt(), 42)
        self.assertIsInstance(msgId.asInt(), int)

    def testAsIntFromNumericStr(self):
        """Test asInt parses a numeric string as an integer."""
        msgId = MessageId("42")
        self.assertEqual(msgId.asInt(), 42)
        self.assertIsInstance(msgId.asInt(), int)

    def testAsIntFromNegativeNumericStr(self):
        """Test asInt parses a negative numeric string."""
        msgId = MessageId("-100")
        self.assertEqual(msgId.asInt(), -100)

    def testAsIntFromNonNumericStrRaisesValueError(self):
        """Test asInt raises ValueError for a non-numeric string."""
        msgId = MessageId("msg_abc")
        with self.assertRaises(ValueError) as ctx:
            msgId.asInt()
        self.assertIn("not an integer", str(ctx.exception))

    def testAsIntFromEmptyStrRaisesValueError(self):
        """Test asInt raises ValueError for an empty string."""
        msgId = MessageId("")
        with self.assertRaises(ValueError):
            msgId.asInt()


class TestMessageIdAsMessageId(unittest.TestCase):
    """Tests for MessageId.asMessageId."""

    def testAsMessageIdFromInt(self):
        """Test asMessageId returns an int when the underlying value is int."""
        msgId = MessageId(42)
        self.assertEqual(msgId.asMessageId(), 42)
        self.assertIsInstance(msgId.asMessageId(), int)

    def testAsMessageIdFromNumericStr(self):
        """Test asMessageId returns an int when the string is numeric."""
        msgId = MessageId("42")
        self.assertEqual(msgId.asMessageId(), 42)
        self.assertIsInstance(msgId.asMessageId(), int)

    def testAsMessageIdFromNonNumericStr(self):
        """Test asMessageId returns a string when the string is non-numeric."""
        msgId = MessageId("msg_abc")
        result = msgId.asMessageId()
        self.assertEqual(result, "msg_abc")
        self.assertIsInstance(result, str)

    def testAsMessageIdFromEmptyStr(self):
        """Test asMessageId returns a string when the string is empty."""
        msgId = MessageId("")
        result = msgId.asMessageId()
        self.assertEqual(result, "")
        self.assertIsInstance(result, str)

    def testAsMessageIdFromNegativeNumericStr(self):
        """Test asMessageId returns int for a negative numeric string."""
        msgId = MessageId("-5")
        self.assertEqual(msgId.asMessageId(), -5)


class TestMessageIdStrRepr(unittest.TestCase):
    """Tests for MessageId.__str__ and __repr__."""

    def testStrFromInt(self):
        """Test __str__ returns the string form of an int ID."""
        msgId = MessageId(42)
        self.assertEqual(str(msgId), "42")

    def testStrFromStr(self):
        """Test __str__ returns the string ID unchanged."""
        msgId = MessageId("msg_abc")
        self.assertEqual(str(msgId), "msg_abc")

    def testReprFromInt(self):
        """Test __repr__ includes the class name and int value."""
        msgId = MessageId(42)
        self.assertEqual(repr(msgId), "MessageId(messageId=42)")

    def testReprFromStr(self):
        """Test __repr__ includes the class name and string value."""
        msgId = MessageId("msg_abc")
        self.assertEqual(repr(msgId), "MessageId(messageId=msg_abc)")


class TestMessageIdEquality(unittest.TestCase):
    """Tests for MessageId.__eq__."""

    def testEqualSameInt(self):
        """Test two MessageId instances with the same int are equal."""
        self.assertEqual(MessageId(42), MessageId(42))

    def testNotEqualDifferentInt(self):
        """Test two MessageId instances with different ints are not equal."""
        self.assertNotEqual(MessageId(42), MessageId(99))

    def testEqualSameStr(self):
        """Test two MessageId instances with the same string are equal."""
        self.assertEqual(MessageId("abc"), MessageId("abc"))

    def testNotEqualDifferentStr(self):
        """Test two MessageId instances with different strings are not equal."""
        self.assertNotEqual(MessageId("abc"), MessageId("xyz"))

    def testEqualIntAndStrSameValue(self):
        """Test int and str MessageId with the same numeric value are equal."""
        self.assertEqual(MessageId(42), MessageId("42"))

    def testEqualWithInt(self):
        """Test MessageId(42) equals the integer 42."""
        self.assertEqual(MessageId(42), 42)

    def testNotEqualWithInt(self):
        """Test MessageId(99) does not equal the integer 42."""
        self.assertNotEqual(MessageId(99), 42)

    def testEqualWithStr(self):
        """Test MessageId('abc') equals the string 'abc'."""
        self.assertEqual(MessageId("abc"), "abc")

    def testNotEqualWithStr(self):
        """Test MessageId('abc') does not equal the string 'xyz'."""
        self.assertNotEqual(MessageId("abc"), "xyz")

    def testEqualNumericStrWithInt(self):
        """Test MessageId('42') equals the integer 42 via asMessageId."""
        self.assertEqual(MessageId("42"), 42)

    def testNotEqualNonNumericStrWithInt(self):
        """Test MessageId('abc') does not equal the integer 42."""
        self.assertNotEqual(MessageId("abc"), 42)

    def testEqualWithBoolReturnsFalse(self):
        """Test MessageId never equals a bool, even if value matches."""
        self.assertNotEqual(MessageId(1), True)
        self.assertNotEqual(MessageId(0), False)
        self.assertNotEqual(MessageId(1), False)
        self.assertNotEqual(MessageId(0), True)

    def testNotEqualWithNone(self):
        """Test MessageId does not equal None."""
        self.assertNotEqual(MessageId(42), None)

    @patch("internal.models.types.logger")
    def testEqualWithUnsupportedTypeLogsWarning(self, mockLogger):
        """Test comparison with an unsupported type logs a warning."""
        msgId = MessageId(42)
        result = msgId == [1, 2]
        self.assertFalse(result)
        mockLogger.warning.assert_called_once()
        self.assertIn("list", mockLogger.warning.call_args[0][0])

    @patch("internal.models.types.logger")
    def testEqualWithUnsupportedTypeComparesStr(self, mockLogger):
        """Test comparison with an unsupported type falls back to string comparison."""
        msgId = MessageId(42)
        result = msgId == [1, 2]
        self.assertFalse(result)


class TestMessageIdHash(unittest.TestCase):
    """Tests for MessageId.__hash__."""

    def testHashConsistentWithEquality(self):
        """Test that equal instances produce the same hash."""
        a = MessageId(42)
        b = MessageId(42)
        self.assertEqual(hash(a), hash(b))

    def testHashIntAndStrSameValue(self):
        """Test that MessageId(42) and MessageId('42') have the same hash."""
        a = MessageId(42)
        b = MessageId("42")
        self.assertEqual(hash(a), hash(b))

    def testHashDifferentValuesDiffer(self):
        """Test that different values generally produce different hashes."""
        a = MessageId(42)
        b = MessageId(99)
        self.assertNotEqual(hash(a), hash(b))

    def testUsableAsDictKey(self):
        """Test MessageId instances can be used as dictionary keys."""
        d = {MessageId(1): "one", MessageId("abc"): "abc"}
        self.assertEqual(d[MessageId(1)], "one")
        self.assertEqual(d[MessageId("abc")], "abc")

    def testUsableInSet(self):
        """Test MessageId instances can be used in sets."""
        s = {MessageId(1), MessageId(2), MessageId(1)}
        self.assertEqual(len(s), 2)

    def testSetDeduplicatesIntAndStrSameValue(self):
        """Test that int and str MessageId with the same value are deduplicated in a set."""
        s = {MessageId(42), MessageId("42")}
        self.assertEqual(len(s), 1)


if __name__ == "__main__":
    unittest.main()
