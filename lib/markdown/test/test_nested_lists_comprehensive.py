#!/usr/bin/env python3
"""
Comprehensive test for nested lists functionality.
"""

import unittest
import sys
import os

# Add the lib directory to the path so we can import the markdown module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from lib.markdown import MarkdownParser  # noqa: E402
from lib.markdown.ast_nodes import MDList, MDListItem, ListType  # noqa: E402


class TestNestedLists(unittest.TestCase):
    """Test nested lists functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = MarkdownParser()

    def test_user_example_nested_lists(self):
        """Test the user's specific nested list example."""
        input_text = """1. Item 1
2. Item 2
3. Item 3
   - Item 3.1
   - Item 3.2
      - Item 3.2.1
      - Item 3.2.2
   - Item 3.3"""

        doc = self.parser.parse(input_text)

        # Should have one ordered list
        self.assertEqual(len(doc.children), 1)
        main_list = doc.children[0]
        self.assertIsInstance(main_list, MDList)
        self.assertEqual(main_list.list_type, ListType.ORDERED)  # type: ignore

        # Should have 3 items in the main list
        self.assertEqual(len(main_list.children), 3)

        # Third item should have a nested unordered list
        third_item = main_list.children[2]
        self.assertIsInstance(third_item, MDListItem)

        # Find the nested list in the third item
        nested_list = None
        for child in third_item.children:
            if isinstance(child, MDList):
                nested_list = child
                break

        self.assertIsNotNone(nested_list, "Third item should contain a nested list")
        self.assertEqual(nested_list.list_type, ListType.UNORDERED)  # type: ignore

        # The nested list should have 3 items: Item 3.1, Item 3.2, Item 3.3
        self.assertIsNotNone(nested_list)
        self.assertEqual(
            len(nested_list.children),  # type: ignore
            3,
            f"Expected 3 items in nested list, got {len(nested_list.children)}",  # type: ignore
        )

        # Item 3.2 should have its own nested list with 2 items
        item_3_2 = nested_list.children[1]  # type: ignore
        self.assertIsInstance(item_3_2, MDListItem)

        # Find the deeply nested list in Item 3.2
        deeply_nested_list = None
        for child in item_3_2.children:
            if isinstance(child, MDList):
                deeply_nested_list = child
                break

        self.assertIsNotNone(deeply_nested_list, "Item 3.2 should contain a nested list")
        self.assertEqual(
            len(deeply_nested_list.children),  # type: ignore
            2,
            f"Expected 2 items in deeply nested list, got {len(deeply_nested_list.children)}",  # type: ignore
        )

    def test_simple_nested_lists(self):
        """Test simple nested lists."""
        input_text = """- Item 1
- Item 2
  - Item 2.1
  - Item 2.2
- Item 3"""

        doc = self.parser.parse(input_text)

        # Should have one unordered list
        self.assertEqual(len(doc.children), 1)
        main_list = doc.children[0]
        self.assertIsInstance(main_list, MDList)
        self.assertEqual(main_list.list_type, ListType.UNORDERED)  # type: ignore

        # Should have 3 items in the main list
        self.assertEqual(len(main_list.children), 3)

        # Second item should have a nested list
        second_item = main_list.children[1]
        self.assertIsInstance(second_item, MDListItem)

        # Find the nested list in the second item
        nested_list = None
        for child in second_item.children:
            if isinstance(child, MDList):
                nested_list = child
                break

        self.assertIsNotNone(nested_list, "Second item should contain a nested list")

        # The nested list should have 2 items: Item 2.1, Item 2.2
        self.assertEqual(
            len(nested_list.children),  # type: ignore
            2,
            f"Expected 2 items in nested list, got {len(nested_list.children)}",  # type: ignore
        )


if __name__ == "__main__":
    unittest.main()
