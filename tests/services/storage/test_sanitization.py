"""
Comprehensive tests for storage key sanitization, dood!

This module tests the sanitizeKey() function to ensure it properly
sanitizes storage keys and prevents path traversal attacks.
"""

import pytest

from internal.services.storage.exceptions import StorageKeyError
from internal.services.storage.utils import sanitizeKey


class TestSanitizeKeyValidKeys:
    """Test that valid keys pass through unchanged, dood!"""

    def testSimpleAlphanumericKey(self):
        """Test simple alphanumeric key passes through unchanged"""
        key = "test123"
        result = sanitizeKey(key)
        assert result == key

    def testKeyWithHyphens(self):
        """Test key with hyphens passes through unchanged"""
        key = "test-key-123"
        result = sanitizeKey(key)
        assert result == key

    def testKeyWithUnderscores(self):
        """Test key with underscores passes through unchanged"""
        key = "test_key_123"
        result = sanitizeKey(key)
        assert result == key

    def testKeyWithDots(self):
        """Test key with dots passes through unchanged"""
        key = "test.key.123"
        result = sanitizeKey(key)
        assert result == key

    def testKeyWithMixedCharacters(self):
        """Test key with mixed valid characters passes through unchanged"""
        key = "test-key_123.txt"
        result = sanitizeKey(key)
        assert result == key

    def testKeyWithUppercase(self):
        """Test key with uppercase letters passes through unchanged"""
        key = "TestKey123"
        result = sanitizeKey(key)
        assert result == key

    def testKeyWithAllValidCharacters(self):
        """Test key with all valid character types"""
        key = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
        result = sanitizeKey(key)
        assert result == key


class TestSanitizeKeyPathTraversal:
    """Test that path traversal attempts are sanitized, dood!"""

    def testDoubleDotRemoval(self):
        """Test that double dots are removed"""
        key = "../../../etc/passwd"
        result = sanitizeKey(key)
        assert ".." not in result
        assert result == "etc_passwd"

    def testForwardSlashReplacement(self):
        """Test that forward slashes are replaced with underscores"""
        key = "path/to/file"
        result = sanitizeKey(key)
        assert "/" not in result
        assert result == "path_to_file"

    def testBackslashReplacement(self):
        """Test that backslashes are replaced with underscores"""
        key = "path\\to\\file"
        result = sanitizeKey(key)
        assert "\\" not in result
        assert result == "path_to_file"

    def testMixedPathSeparators(self):
        """Test that mixed path separators are replaced"""
        key = "path/to\\file"
        result = sanitizeKey(key)
        assert "/" not in result
        assert "\\" not in result
        assert result == "path_to_file"

    def testComplexPathTraversal(self):
        """Test complex path traversal attempt"""
        key = "../../etc/../passwd"
        result = sanitizeKey(key)
        assert ".." not in result
        assert "/" not in result
        assert result == "etc__passwd"

    def testWindowsPathTraversal(self):
        """Test Windows-style path traversal"""
        key = "..\\..\\windows\\system32"
        result = sanitizeKey(key)
        assert ".." not in result
        assert "\\" not in result
        assert result == "windows_system32"


class TestSanitizeKeyInvalidCharacters:
    """Test that invalid characters are removed, dood!"""

    def testNullByteRemoval(self):
        """Test that null bytes are removed"""
        key = "test\x00key"
        result = sanitizeKey(key)
        assert "\x00" not in result
        assert result == "testkey"

    def testControlCharacterRemoval(self):
        """Test that control characters are removed"""
        key = "test\x01\x02\x03key"
        result = sanitizeKey(key)
        assert result == "testkey"

    def testDeleteCharacterRemoval(self):
        """Test that DEL character (127) is removed"""
        key = "test\x7fkey"
        result = sanitizeKey(key)
        assert "\x7f" not in result
        assert result == "testkey"

    def testAllControlCharactersRemoved(self):
        """Test that all control characters (0-31, 127) are removed"""
        # Create key with all control characters
        controlChars = "".join(chr(i) for i in range(32))
        key = f"test{controlChars}key"
        result = sanitizeKey(key)
        assert result == "testkey"

    def testSpecialCharactersRemoved(self):
        """Test that special characters are removed"""
        key = "test@#$%^&*()key"
        result = sanitizeKey(key)
        assert result == "testkey"

    def testSpacesRemoved(self):
        """Test that spaces are removed"""
        key = "test key with spaces"
        result = sanitizeKey(key)
        assert " " not in result
        assert result == "testkeywithspaces"

    def testUnicodeCharactersRemoved(self):
        """Test that unicode characters are removed"""
        key = "test🔥key"
        result = sanitizeKey(key)
        assert "🔥" not in result
        assert result == "testkey"


class TestSanitizeKeyLeadingTrailingCharacters:
    """Test that dangerous leading/trailing characters are stripped, dood!"""

    def testLeadingDotsStripped(self):
        """Test that leading dots are stripped"""
        key = "...testkey"
        result = sanitizeKey(key)
        assert not result.startswith(".")
        assert result == "testkey"

    def testTrailingDotsStripped(self):
        """Test that trailing dots are stripped"""
        key = "testkey..."
        result = sanitizeKey(key)
        assert not result.endswith(".")
        assert result == "testkey"

    def testLeadingUnderscoresStripped(self):
        """Test that leading underscores are stripped"""
        key = "___testkey"
        result = sanitizeKey(key)
        assert not result.startswith("_")
        assert result == "testkey"

    def testTrailingUnderscoresStripped(self):
        """Test that trailing underscores are stripped"""
        key = "testkey___"
        result = sanitizeKey(key)
        assert not result.endswith("_")
        assert result == "testkey"

    def testLeadingWhitespaceStripped(self):
        """Test that leading whitespace is stripped"""
        key = "   testkey"
        result = sanitizeKey(key)
        assert not result.startswith(" ")
        assert result == "testkey"

    def testTrailingWhitespaceStripped(self):
        """Test that trailing whitespace is stripped"""
        key = "testkey   "
        result = sanitizeKey(key)
        assert not result.endswith(" ")
        assert result == "testkey"

    def testMixedLeadingTrailingCharacters(self):
        """Test that mixed leading/trailing dangerous characters are stripped"""
        key = " ._testkey_. "
        result = sanitizeKey(key)
        assert result == "testkey"


class TestSanitizeKeyEdgeCases:
    """Test edge cases and boundary conditions, dood!"""

    def testEmptyStringRaisesError(self):
        """Test that empty string raises StorageKeyError"""
        with pytest.raises(StorageKeyError, match="cannot be empty"):
            sanitizeKey("")

    def testWhitespaceOnlyRaisesError(self):
        """Test that whitespace-only string raises StorageKeyError"""
        with pytest.raises(StorageKeyError, match="cannot be empty"):
            sanitizeKey("   ")

    def testInvalidCharactersOnlyRaisesError(self):
        """Test that string with only invalid characters raises error"""
        with pytest.raises(StorageKeyError, match="empty or too short after sanitization"):
            sanitizeKey("@#$%^&*()")

    def testPathSeparatorsOnlyRaisesError(self):
        """Test that string with only path separators raises error"""
        with pytest.raises(StorageKeyError, match="empty or too short after sanitization"):
            sanitizeKey("///")

    def testDoubleDotOnlyRaisesError(self):
        """Test that string with only double dots raises error"""
        with pytest.raises(StorageKeyError, match="empty or too short after sanitization"):
            sanitizeKey("....")

    def testMaxLengthKey(self):
        """Test that key at maximum length (255) is accepted"""
        key = "a" * 255
        result = sanitizeKey(key)
        assert result == key
        assert len(result) == 255

    def testExceedsMaxLengthRaisesError(self):
        """Test that key exceeding maximum length raises error"""
        key = "a" * 256
        with pytest.raises(StorageKeyError, match="exceeds maximum length"):
            sanitizeKey(key)

    def testVeryLongKeyRaisesError(self):
        """Test that very long key raises error"""
        key = "a" * 1000
        with pytest.raises(StorageKeyError, match="exceeds maximum length"):
            sanitizeKey(key)

    def testSingleCharacterKey(self):
        """Test that single character key is accepted"""
        key = "a"
        result = sanitizeKey(key)
        assert result == key

    def testKeyBecomesEmptyAfterSanitization(self):
        """Test that key becoming empty after sanitization raises error"""
        key = "   ...   "
        with pytest.raises(StorageKeyError, match="empty or too short after sanitization"):
            sanitizeKey(key)


class TestSanitizeKeyRealWorldScenarios:
    """Test real-world scenarios and common use cases, dood!"""

    def testFilenameWithExtension(self):
        """Test typical filename with extension"""
        key = "document.pdf"
        result = sanitizeKey(key)
        assert result == key

    def testUuidKey(self):
        """Test UUID-style key"""
        key = "550e8400-e29b-41d4-a716-446655440000"
        result = sanitizeKey(key)
        assert result == key

    def testTimestampKey(self):
        """Test timestamp-style key"""
        key = "2024-01-15_14-30-00"
        result = sanitizeKey(key)
        assert result == key

    def testUserUploadedFilename(self):
        """Test user-uploaded filename with spaces and special chars"""
        key = "My Document (final).pdf"
        result = sanitizeKey(key)
        assert " " not in result
        assert "(" not in result
        assert ")" not in result
        assert result == "MyDocumentfinal.pdf"

    def testMaliciousFilename(self):
        """Test malicious filename attempt"""
        key = "../../../etc/passwd"
        result = sanitizeKey(key)
        assert ".." not in result
        assert "/" not in result
        assert result == "etc_passwd"

    def testWindowsMaliciousPath(self):
        """Test Windows malicious path"""
        key = "..\\..\\windows\\system32\\config\\sam"
        result = sanitizeKey(key)
        assert ".." not in result
        assert "\\" not in result
        assert result == "windows_system32_config_sam"

    def testUrlAsKey(self):
        """Test URL-like string as key"""
        key = "https://example.com/path/to/file"
        result = sanitizeKey(key)
        assert "/" not in result
        assert ":" not in result
        assert result == "https__example.com_path_to_file"

    def testKeyWithMultipleExtensions(self):
        """Test key with multiple extensions"""
        key = "archive.tar.gz"
        result = sanitizeKey(key)
        assert result == key

    def testKeyWithVersionNumber(self):
        """Test key with version number"""
        key = "document-v1.2.3.pdf"
        result = sanitizeKey(key)
        assert result == key

    def testKeyWithDate(self):
        """Test key with date"""
        key = "report-2024-01-15.xlsx"
        result = sanitizeKey(key)
        assert result == key


class TestSanitizeKeyConsistency:
    """Test that sanitization is consistent and idempotent, dood!"""

    def testIdempotence(self):
        """Test that sanitizing twice produces same result"""
        key = "test/../key"
        result1 = sanitizeKey(key)
        result2 = sanitizeKey(result1)
        assert result1 == result2

    def testConsistentResults(self):
        """Test that same input always produces same output"""
        key = "test@#$key"
        results = [sanitizeKey(key) for _ in range(10)]
        assert all(r == results[0] for r in results)

    def testDifferentInputsDifferentOutputs(self):
        """Test that different inputs produce different outputs"""
        key1 = "test-key-1"
        key2 = "test-key-2"
        result1 = sanitizeKey(key1)
        result2 = sanitizeKey(key2)
        assert result1 != result2
