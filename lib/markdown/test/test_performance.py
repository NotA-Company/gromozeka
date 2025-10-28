#!/usr/bin/env python3
"""
Performance tests for Markdown Parser.

This module tests parser performance with large documents,
many nested structures, and complex formatting.
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from lib.markdown import (  # noqa: E402
    MarkdownParser,
    markdown_to_html,
    markdown_to_markdownv2,
)

# Mark all tests in this module as slow
try:
    import pytest

    pytestmark = pytest.mark.slow
except ImportError:
    pytestmark = None


class TestLargeDocuments(unittest.TestCase):
    """Test performance with large documents."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = MarkdownParser()

    def test_large_plain_text_document(self):
        """Test parsing large plain text document (10,000+ lines)."""
        # Create a document with 10,000 lines
        lines = [f"This is line {i} of the document." for i in range(10000)]
        markdown = "\n\n".join(lines)

        start_time = time.time()
        doc = self.parser.parse(markdown)
        parse_time = time.time() - start_time

        # Should complete in reasonable time (< 5 seconds)
        self.assertLess(parse_time, 5.0, f"Parsing took {parse_time:.2f}s, expected < 5s")

        # Verify document was parsed
        self.assertIsNotNone(doc)
        self.assertGreater(len(doc.children), 0)

    def test_large_document_with_formatting(self):
        """Test parsing large document with various formatting."""
        # Create document with mixed formatting
        sections = []
        for i in range(1000):
            section = f"""## Section {i}

This is **bold text** and *italic text* in section {i}.

- Item 1 with `code`
- Item 2 with [link](http://example.com/{i})
- Item 3 with ~~strikethrough~~

```python
def function_{i}():
    return {i}
```
"""
            sections.append(section)

        markdown = "\n\n".join(sections)

        start_time = time.time()
        doc = self.parser.parse(markdown)
        parse_time = time.time() - start_time

        # Should complete in reasonable time (< 10 seconds)
        self.assertLess(parse_time, 10.0, f"Parsing took {parse_time:.2f}s, expected < 10s")

        # Verify document was parsed
        self.assertIsNotNone(doc)
        self.assertGreater(len(doc.children), 0)

    def test_large_list_document(self):
        """Test parsing document with very large list."""
        # Create a list with 5,000 items
        items = [f"- List item {i}" for i in range(5000)]
        markdown = "\n".join(items)

        start_time = time.time()
        doc = self.parser.parse(markdown)
        parse_time = time.time() - start_time

        # Should complete in reasonable time (< 5 seconds)
        self.assertLess(parse_time, 5.0, f"Parsing took {parse_time:.2f}s, expected < 5s")

        # Verify list was parsed
        self.assertIsNotNone(doc)

    def test_large_code_block(self):
        """Test parsing very large code block."""
        # Create a code block with 10,000 lines
        code_lines = [f"    line_{i} = {i}" for i in range(10000)]
        code = "\n".join(code_lines)
        markdown = f"```python\n{code}\n```"

        start_time = time.time()
        doc = self.parser.parse(markdown)
        parse_time = time.time() - start_time

        # Should complete in reasonable time (< 3 seconds)
        self.assertLess(parse_time, 3.0, f"Parsing took {parse_time:.2f}s, expected < 3s")

        # Verify code block was parsed
        self.assertIsNotNone(doc)


class TestManyNestedStructures(unittest.TestCase):
    """Test performance with many nested structures."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = MarkdownParser()

    def test_many_nested_lists(self):
        """Test document with many nested list structures."""
        # Create 100 nested list structures
        sections = []
        for i in range(100):
            section = f"""- Item {i}
  - Nested {i}.1
    - Deep {i}.1.1
      - Deeper {i}.1.1.1
  - Nested {i}.2
  - Nested {i}.3"""
            sections.append(section)

        markdown = "\n\n".join(sections)

        start_time = time.time()
        doc = self.parser.parse(markdown)
        parse_time = time.time() - start_time

        # Should complete in reasonable time (< 5 seconds)
        self.assertLess(parse_time, 5.0, f"Parsing took {parse_time:.2f}s, expected < 5s")

        self.assertIsNotNone(doc)

    def test_many_blockquotes(self):
        """Test document with many blockquote structures."""
        # Create 1,000 blockquotes
        quotes = [f"> This is quote number {i}\n> With multiple lines" for i in range(1000)]
        markdown = "\n\n".join(quotes)

        start_time = time.time()
        doc = self.parser.parse(markdown)
        parse_time = time.time() - start_time

        # Should complete in reasonable time (< 5 seconds)
        self.assertLess(parse_time, 5.0, f"Parsing took {parse_time:.2f}s, expected < 5s")

        self.assertIsNotNone(doc)

    def test_many_code_blocks(self):
        """Test document with many code blocks."""
        # Create 500 code blocks
        blocks = []
        for i in range(500):
            block = f"""```python
def function_{i}():
    return {i}
```"""
            blocks.append(block)

        markdown = "\n\n".join(blocks)

        start_time = time.time()
        doc = self.parser.parse(markdown)
        parse_time = time.time() - start_time

        # Should complete in reasonable time (< 5 seconds)
        self.assertLess(parse_time, 5.0, f"Parsing took {parse_time:.2f}s, expected < 5s")

        self.assertIsNotNone(doc)

    def test_deeply_nested_mixed_structures(self):
        """Test deeply nested mixed structures."""
        # Create complex nested structure
        markdown = """- List item 1
  > Blockquote in list
  > - List in blockquote
  >   - Nested list in blockquote
  >     > Quote in nested list
  >     > - Another list
  - Back to main list
    - Nested again
      > Quote in nested list
      > ```python
      > code_in_quote()
      > ```
- Main list continues"""

        # Repeat this structure 50 times
        markdown = (markdown + "\n\n") * 50

        start_time = time.time()
        doc = self.parser.parse(markdown)
        parse_time = time.time() - start_time

        # Should complete in reasonable time (< 10 seconds)
        self.assertLess(parse_time, 10.0, f"Parsing took {parse_time:.2f}s, expected < 10s")

        self.assertIsNotNone(doc)


class TestComplexFormatting(unittest.TestCase):
    """Test performance with complex formatting."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = MarkdownParser()

    def test_many_inline_elements(self):
        """Test document with many inline formatting elements."""
        # Create text with many inline elements
        elements = []
        for i in range(1000):
            elements.append(f"**bold{i}** *italic{i}* `code{i}` [link{i}](http://ex.com/{i})")

        markdown = " ".join(elements)

        start_time = time.time()
        doc = self.parser.parse(markdown)
        parse_time = time.time() - start_time

        # Should complete in reasonable time (< 5 seconds)
        self.assertLess(parse_time, 5.0, f"Parsing took {parse_time:.2f}s, expected < 5s")

        self.assertIsNotNone(doc)

    def test_many_links(self):
        """Test document with many links."""
        # Create 2,000 links
        links = [f"[Link {i}](http://example.com/page{i})" for i in range(2000)]
        markdown = " ".join(links)

        start_time = time.time()
        doc = self.parser.parse(markdown)
        parse_time = time.time() - start_time

        # Should complete in reasonable time (< 5 seconds)
        self.assertLess(parse_time, 5.0, f"Parsing took {parse_time:.2f}s, expected < 5s")

        self.assertIsNotNone(doc)

    def test_many_images(self):
        """Test document with many images."""
        # Create 1,000 images
        images = [f"![Alt {i}](http://example.com/img{i}.jpg)" for i in range(1000)]
        markdown = "\n\n".join(images)

        start_time = time.time()
        doc = self.parser.parse(markdown)
        parse_time = time.time() - start_time

        # Should complete in reasonable time (< 5 seconds)
        self.assertLess(parse_time, 5.0, f"Parsing took {parse_time:.2f}s, expected < 5s")

        self.assertIsNotNone(doc)

    def test_complex_nested_emphasis(self):
        """Test complex nested emphasis patterns."""
        # Create complex nested emphasis
        patterns = []
        for i in range(500):
            patterns.append(f"***bold italic {i}*** **bold with *italic {i}* inside**")

        markdown = " ".join(patterns)

        start_time = time.time()
        doc = self.parser.parse(markdown)
        parse_time = time.time() - start_time

        # Should complete in reasonable time (< 5 seconds)
        self.assertLess(parse_time, 5.0, f"Parsing took {parse_time:.2f}s, expected < 5s")

        self.assertIsNotNone(doc)


class TestRenderingPerformance(unittest.TestCase):
    """Test rendering performance for different output formats."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = MarkdownParser()

    def test_html_rendering_performance(self):
        """Test HTML rendering performance with large document."""
        # Create a moderately large document
        sections = []
        for i in range(500):
            section = f"""## Section {i}

Paragraph with **bold** and *italic* text.

- List item 1
- List item 2

```python
code_{i}()
```
"""
            sections.append(section)

        markdown = "\n\n".join(sections)

        start_time = time.time()
        html = markdown_to_html(markdown)
        render_time = time.time() - start_time

        # Should complete in reasonable time (< 10 seconds)
        self.assertLess(render_time, 10.0, f"Rendering took {render_time:.2f}s, expected < 10s")

        # Verify HTML was generated
        self.assertIsNotNone(html)
        self.assertGreater(len(html), 0)

    def test_markdownv2_rendering_performance(self):
        """Test MarkdownV2 rendering performance with large document."""
        # Create a moderately large document
        sections = []
        for i in range(500):
            section = f"""## Section {i}

Paragraph with **bold** and *italic* text.

- List item 1
- List item 2

```python
code_{i}()
```
"""
            sections.append(section)

        markdown = "\n\n".join(sections)

        start_time = time.time()
        result = markdown_to_markdownv2(markdown)
        render_time = time.time() - start_time

        # Should complete in reasonable time (< 10 seconds)
        self.assertLess(render_time, 10.0, f"Rendering took {render_time:.2f}s, expected < 10s")

        # Verify MarkdownV2 was generated
        self.assertIsNotNone(result)
        self.assertGreater(len(result), 0)

    def test_multiple_format_conversions(self):
        """Test converting same document to multiple formats."""
        markdown = """# Test Document

This is a **test** document with *various* formatting.

- Item 1
- Item 2
  - Nested item

```python
def test():
    pass
```

[Link](http://example.com)
"""

        # Repeat to create larger document
        markdown = (markdown + "\n\n") * 100

        start_time = time.time()

        # Parse once
        doc = self.parser.parse(markdown)

        # Render to multiple formats
        html = self.parser.parse_to_html(markdown)
        markdownv2 = self.parser.parse_to_markdownv2(markdown)

        total_time = time.time() - start_time

        # Should complete in reasonable time (< 15 seconds)
        self.assertLess(total_time, 15.0, f"Total conversion took {total_time:.2f}s, expected < 15s")

        # Verify all outputs
        self.assertIsNotNone(doc)
        self.assertIsNotNone(html)
        self.assertIsNotNone(markdownv2)


class TestBenchmarkComparison(unittest.TestCase):
    """Benchmark tests to compare performance across different scenarios."""

    def setUp(self):
        """Set up test fixtures."""
        self.parser = MarkdownParser()

    def test_simple_vs_complex_parsing(self):
        """Compare parsing time for simple vs complex documents."""
        # Simple document
        simple_markdown = "# Header\n\nSimple paragraph.\n\n- Item 1\n- Item 2"
        simple_markdown = (simple_markdown + "\n\n") * 1000

        start_time = time.time()
        self.parser.parse(simple_markdown)
        simple_time = time.time() - start_time

        # Complex document
        complex_markdown = """# Header

**Bold** *italic* ~~strike~~ `code` [link](http://ex.com)

- Item 1
  - Nested
    > Quote
    > ```python
    > code()
    > ```
- Item 2

```python
def complex():
    pass
```
"""
        complex_markdown = (complex_markdown + "\n\n") * 1000

        start_time = time.time()
        self.parser.parse(complex_markdown)
        complex_time = time.time() - start_time

        # Complex should take more time but not exponentially more
        # Allow up to 5x slower for complex documents
        self.assertLess(
            complex_time,
            simple_time * 5,
            f"Complex parsing ({complex_time:.2f}s) should not be more than 5x slower than simple ({simple_time:.2f}s)",
        )

    def test_incremental_size_scaling(self):
        """Test that parsing time scales reasonably with document size."""
        base_markdown = """# Section

Paragraph with **formatting**.

- List item
"""

        times = []
        sizes = [100, 500, 1000, 2000]

        for size in sizes:
            markdown = (base_markdown + "\n\n") * size

            start_time = time.time()
            self.parser.parse(markdown)
            parse_time = time.time() - start_time

            times.append(parse_time)

        # Check that time scaling is reasonable (not exponential)
        # Time for 2000 should be less than 6x time for 500 (allowing for variance and system load)
        if len(times) >= 4:
            self.assertLess(
                times[3],
                times[1] * 6,
                f"Parsing time should scale reasonably: {times}",
            )


if __name__ == "__main__":
    # Run tests with verbose output
    unittest.main(verbosity=2)
