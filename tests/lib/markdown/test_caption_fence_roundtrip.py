#!/usr/bin/env python3
"""
Test suite for caption-in-fence round-trip regression.

This module tests that markdownToMarkdownV2 round-trips caption-in-fence code blocks
correctly, preserving NBSP (U+00A0) characters in language strings and ensuring
fence-content escaping is independent of the language line.
"""

import unittest

from lib.markdown import MarkdownParser, MDCodeBlock, markdownToMarkdownV2


class TestCaptionFenceRoundtrip(unittest.TestCase):
    """Test cases for caption-in-fence round-trip regression."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = MarkdownParser()

    def testRoundtrip_simpleCaption(self):
        """Test full-equality round-trip with simple caption-in-fence.

        Tests that a code block with a simple caption (```` ```Top: ````)
        round-trips through markdownToMarkdownV2 without modification.
        """
        markdown = "```Top:\n• a  1\n```"
        result = markdownToMarkdownV2(markdown)
        self.assertEqual(result, markdown)

    def testRoundtrip_nbspCaption_preservesNbsp(self):
        """Test round-trip with NBSP in caption preserves the NBSP character.

        Tests that a code block with a multi-word caption using NBSP (```` ```Top\xa0models: ````)
        round-trips correctly, with the NBSP character preserved in the output and the
        space-separated "Top models:" string NOT present (verifying it's not normalized).
        """
        markdown = "```Top\xa0models:\n• a  1\n```"
        result = markdownToMarkdownV2(markdown)
        self.assertEqual(result, markdown)
        self.assertIn("\xa0", result, "NBSP character should be preserved in output")
        self.assertNotIn("Top models:", result, "Space-separated caption should not appear")

    def testRoundtrip_parserLayer_nbspInLanguage(self):
        """Test parser layer preserves NBSP in code block language attribute.

        Tests that the parser's tokenize+parse pipeline correctly extracts the language
        attribute from a caption-in-fence code block, preserving NBSP characters exactly
        as they appear in the source.
        """
        markdown = "```Top\xa0models:\n• a  1\n```"
        doc = self.parser.parse(markdown)

        # Find the code block node
        codeBlock = None
        for child in doc.children:
            if isinstance(child, MDCodeBlock):
                codeBlock = child
                break

        self.assertIsNotNone(codeBlock, "Should have parsed a code block")
        if codeBlock is not None:
            self.assertEqual(
                codeBlock.language, "Top\xa0models:", "Language attribute should preserve NBSP character verbatim"
            )

    def testRoundtrip_fenceContentEscaping_untouchedLanguage(self):
        """Test fence-content escaping is independent of language line handling.

        Tests that content containing backticks and backslashes gets pre_code escaping
        in the CONTENT portion of the block, while the language line (caption-in-fence)
        remains untouched and not escaped.
        """
        markdown = "```Top:\ncode with `backtick` and \\backslash\n```"
        result = markdownToMarkdownV2(markdown)

        # Full equality: language line untouched, content pre_code escaped
        expected = "```Top:\ncode with \\`backtick\\` and \\\\backslash\n```"
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
