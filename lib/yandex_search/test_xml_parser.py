"""Tests for Yandex Search XML parser.

This module contains comprehensive unit tests for the XML parser functionality,
covering successful response parsing, error handling, edge cases, and complex
passage parsing with highlighted words.
"""

import base64
import unittest

from .xml_parser import parseSearchResponse


class TestXmlParser(unittest.TestCase):
    """Test cases for XML parser functionality.

    This test class provides comprehensive coverage of the XML parser,
    including successful response parsing, error handling, invalid data
    scenarios, and complex passage parsing with multiple highlighted words.
    """

    def setUp(self):
        """Set up test fixtures.

        Initializes sample XML responses for various test scenarios including
        successful responses with multiple documents and groups, error responses,
        and empty responses. These fixtures provide realistic test data for
        validating the parser's behavior.
        """
        # Sample successful response XML
        self.successXml = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0">
    <response>
        <reqid>test-request-id</reqid>
        <found priority="all">100</found>
        <found-human>Found 100 results</found-human>
        <results>
            <grouping>
                <page>0</page>
                <group>
                    <doc>
                        <url>https://example.com</url>
                        <domain>example.com</domain>
                        <title>Example <hlword>Title</hlword></title>
                        <modtime>20231015T120000</modtime>
                        <size>1024</size>
                        <charset>utf-8</charset>
                        <saved-copy-url>https://yandexwebcache.net/example</saved-copy-url>
                        <mime-type>text/html</mime-type>
                        <passages>
                            <passage>This is a <hlword>sample</hlword> passage.</passage>
                        </passages>
                        <properties>
                            <lang>en</lang>
                            <extended-text>Extended text content</extended-text>
                        </properties>
                    </doc>
                    <doc>
                        <url>https://another.com</url>
                        <domain>another.com</domain>
                        <title>Another Title</title>
                        <mime-type>text/html</mime-type>
                        <passages>
                            <passage>Another passage without highlighting.</passage>
                        </passages>
                    </doc>
                </group>
                <group>
                    <doc>
                        <url>https://third.com</url>
                        <domain>third.com</domain>
                        <title>Third Title</title>
                        <mime-type>text/html</mime-type>
                        <passages>
                            <passage>Third passage with <hlword>different</hlword> highlighting.</passage>
                        </passages>
                    </doc>
                </group>
            </grouping>
        </results>
    </response>
</yandexsearch>"""

        # Sample error response XML
        self.errorXml = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0">
    <response>
        <error code="15">Invalid search query</error>
    </response>
</yandexsearch>"""

        # Empty response XML
        self.emptyXml = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0">
    <response>
        <reqid>empty-request</reqid>
        <found priority="all">0</found>
        <found-human>No results found</found-human>
        <results>
            <grouping>
                <page>0</page>
            </grouping>
        </results>
    </response>
</yandexsearch>"""

    def testParseSuccessResponse(self):
        """Test parsing a successful search response.

        Verifies that the parser correctly handles successful search responses
        with multiple documents, groups, and highlighted words. Tests the
        complete parsing pipeline including Base64 decoding, XML parsing,
        and data structure validation.
        """
        # Encode XML to Base64
        base64Xml = base64.b64encode(self.successXml.encode("utf-8")).decode("utf-8")

        # Parse response
        response = parseSearchResponse(base64Xml)

        # Verify response structure
        self.assertEqual(response["requestId"], "test-request-id")
        self.assertEqual(response["found"], 100)
        self.assertEqual(response["foundHuman"], "Found 100 results")
        self.assertEqual(response["page"], 0)
        self.assertIsNone(response.get("error"))

        # Verify groups
        self.assertEqual(len(response["groups"]), 2)

        # Verify first group
        firstGroup = response["groups"][0]
        self.assertEqual(len(firstGroup), 2)

        # Verify first document
        firstDoc = firstGroup[0]
        self.assertEqual(firstDoc["url"], "https://example.com")
        self.assertEqual(firstDoc["domain"], "example.com")
        self.assertEqual(firstDoc["title"], "Example **Title**")
        self.assertEqual(len(firstDoc["passages"]), 1)
        self.assertEqual(firstDoc["passages"][0], "This is a **sample** passage.")
        hlwords = firstDoc.get("hlwords")
        self.assertIsNotNone(hlwords)
        if hlwords:
            self.assertEqual(set(hlwords), {"sample"})
        # Verify new fields
        self.assertEqual(firstDoc.get("mimeType"), "text/html")
        self.assertEqual(firstDoc.get("charset"), "utf-8")
        self.assertEqual(firstDoc.get("savedCopyUrl"), "https://yandexwebcache.net/example")
        self.assertIsNotNone(firstDoc.get("modtime"))
        self.assertEqual(firstDoc.get("size"), 1024)
        self.assertEqual(firstDoc.get("lang"), "en")
        self.assertEqual(firstDoc.get("extendedText"), "Extended text content")

        # Verify second document
        secondDoc = firstGroup[1]
        self.assertEqual(secondDoc["url"], "https://another.com")
        self.assertEqual(secondDoc["domain"], "another.com")
        self.assertEqual(secondDoc["title"], "Another Title")
        self.assertEqual(len(secondDoc["passages"]), 1)
        self.assertEqual(secondDoc["passages"][0], "Another passage without highlighting.")
        self.assertIn("hlwords", secondDoc)
        if "hlwords" in secondDoc:
            self.assertEqual(secondDoc["hlwords"], [])

        # Verify second group
        secondGroup = response["groups"][1]
        self.assertEqual(len(secondGroup), 1)

        # Verify third document
        thirdDoc = secondGroup[0]
        self.assertEqual(thirdDoc["url"], "https://third.com")
        self.assertEqual(thirdDoc["domain"], "third.com")
        self.assertEqual(thirdDoc["title"], "Third Title")
        self.assertEqual(len(thirdDoc["passages"]), 1)
        self.assertEqual(thirdDoc["passages"][0], "Third passage with **different** highlighting.")
        self.assertIn("hlwords", thirdDoc)
        if "hlwords" in thirdDoc:
            self.assertEqual(thirdDoc["hlwords"], ["different"])

    def testParseErrorResponse(self):
        """Test parsing an error response.

        Verifies that the parser correctly handles error responses from the
        API, properly extracting error codes and messages while maintaining
        the expected response structure for error scenarios.
        """
        # Encode XML to Base64
        base64Xml = base64.b64encode(self.errorXml.encode("utf-8")).decode("utf-8")

        # Parse response
        response = parseSearchResponse(base64Xml)

        # Verify error structure
        self.assertEqual(response["requestId"], "")
        self.assertEqual(response["found"], 0)
        self.assertEqual(response["foundHuman"], "")
        self.assertEqual(response["page"], 0)
        self.assertEqual(len(response["groups"]), 0)

        # Verify error details
        error = response.get("error")
        self.assertIsNotNone(error)
        if error:
            self.assertEqual(error.get("code"), "15")
            self.assertEqual(error.get("message"), "Invalid search query")

    def testParseEmptyResponse(self):
        """Test parsing an empty response.

        Verifies that the parser correctly handles responses with no search
        results, ensuring proper parsing of metadata fields and empty result
        sets without errors.
        """
        # Encode XML to Base64
        base64Xml = base64.b64encode(self.emptyXml.encode("utf-8")).decode("utf-8")

        # Parse response
        response = parseSearchResponse(base64Xml)

        # Verify response structure
        self.assertEqual(response["requestId"], "empty-request")
        self.assertEqual(response["found"], 0)
        self.assertEqual(response["foundHuman"], "No results found")
        self.assertEqual(response["page"], 0)
        self.assertIsNone(response.get("error"))
        self.assertEqual(len(response["groups"]), 0)

    def testParseInvalidBase64(self):
        """Test parsing invalid Base64 data.

        Verifies that the parser properly handles and reports errors when
        encountering invalid Base64 encoding, ensuring graceful error handling
        with appropriate error messages.
        """
        with self.assertRaises(ValueError) as context:
            parseSearchResponse("invalid-base64-data")

        self.assertIn("Invalid Base64 encoding", str(context.exception))

    def testParseInvalidXml(self):
        """Test parsing invalid XML.

        Verifies that the parser properly handles and reports errors when
        encountering malformed XML data, ensuring graceful error handling
        with appropriate error messages for invalid XML structures.
        """
        # Create invalid XML
        invalidXml = "<invalid><xml>"
        base64Xml = base64.b64encode(invalidXml.encode("utf-8")).decode("utf-8")

        with self.assertRaises(ValueError) as context:
            parseSearchResponse(base64Xml)

        self.assertIn("Invalid XML format", str(context.exception))

    def testComplexPassageParsing(self):
        """Test parsing complex passages with multiple highlighted words.

        Verifies that the parser correctly handles complex passage structures
        with multiple highlighted words across different passages, ensuring
        proper extraction and deduplication of highlighted words while
        maintaining passage text integrity.
        """
        complexXml = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0">
    <response>
        <reqid>complex-test</reqid>
        <found priority="all">1</found>
        <found-human>Found 1 result</found-human>
        <results>
            <grouping>
                <page>0</page>
                <group>
                    <doc>
                        <url>https://complex.com</url>
                        <domain>complex.com</domain>
                        <title>Complex Title</title>
                        <mime-type>text/html</mime-type>
                        <passages>
                            <passage>Start <hlword>1st</hlword> middle <hlword>2nd</hlword> end.</passage>
                            <passage>With <hlword>third</hlword> and <hlword>fourth</hlword> words.</passage>
                        </passages>
                    </doc>
                </group>
            </grouping>
        </results>
    </response>
</yandexsearch>"""

        # Encode XML to Base64
        base64Xml = base64.b64encode(complexXml.encode("utf-8")).decode("utf-8")

        # Parse response
        response = parseSearchResponse(base64Xml)

        # Verify document
        doc = response["groups"][0][0]
        self.assertEqual(len(doc["passages"]), 2)
        self.assertEqual(doc["passages"][0], "Start **1st** middle **2nd** end.")
        self.assertEqual(doc["passages"][1], "With **third** and **fourth** words.")
        hlwords = doc.get("hlwords")
        self.assertIsNotNone(hlwords)
        if hlwords:
            self.assertEqual(set(hlwords), {"1st", "2nd", "third", "fourth"})


if __name__ == "__main__":
    unittest.main()
