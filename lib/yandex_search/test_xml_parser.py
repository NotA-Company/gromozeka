"""
Tests for Yandex Search XML parser

This module contains unit tests for the XML parser functionality.
"""

import base64
import unittest

from .xml_parser import parseErrorResponse, parseSearchResponse


class TestXmlParser(unittest.TestCase):
    """Test cases for XML parser functionality"""

    def setUp(self):
        """Set up test fixtures"""
        # Sample successful response XML
        self.successXml = """<?xml version="1.0" encoding="utf-8"?>
<search requestid="test-request-id" found="100" found-human="Found 100 results" page="0">
    <group>
        <doc url="https://example.com" domain="example.com" title="Example Title">
            <passage>This is a <hlword>sample</hlword> passage with <hlword>highlighted</hlword> words.</passage>
            <mime-type>text/html</mime-type>
        </doc>
        <doc url="https://another.com" domain="another.com" title="Another Title">
            <passage>Another passage without highlighting.</passage>
            <mime-type>text/html</mime-type>
        </doc>
    </group>
    <group>
        <doc url="https://third.com" domain="third.com" title="Third Title">
            <passage>Third passage with <hlword>different</hlword> highlighting.</passage>
            <mime-type>text/html</mime-type>
        </doc>
    </group>
</search>"""

        # Sample error response XML
        self.errorXml = """<?xml version="1.0" encoding="utf-8"?>
<search>
    <error code="INVALID_QUERY" message="Invalid search query" details="The query contains forbidden characters"/>
</search>"""

        # Empty response XML
        self.emptyXml = """<?xml version="1.0" encoding="utf-8"?>
<search requestid="empty-request" found="0" found-human="No results found" page="0">
</search>"""

    def testParseSuccessResponse(self):
        """Test parsing a successful search response"""
        # Encode XML to Base64
        base64Xml = base64.b64encode(self.successXml.encode("utf-8")).decode("utf-8")

        # Parse response
        response = parseSearchResponse(base64Xml)

        # Verify response structure
        self.assertEqual(response["requestId"], "test-request-id")
        self.assertEqual(response["found"], 100)
        self.assertEqual(response["foundHuman"], "Found 100 results")
        self.assertEqual(response["page"], 0)
        self.assertIsNone(response["error"])

        # Verify groups
        self.assertEqual(len(response["groups"]), 2)

        # Verify first group
        firstGroup = response["groups"][0]
        self.assertEqual(len(firstGroup["group"]), 2)

        # Verify first document
        firstDoc = firstGroup["group"][0]
        self.assertEqual(firstDoc["url"], "https://example.com")
        self.assertEqual(firstDoc["domain"], "example.com")
        self.assertEqual(firstDoc["title"], "Example Title")
        self.assertEqual(len(firstDoc["passages"]), 1)
        self.assertEqual(firstDoc["passages"][0], "This is a *sample* passage with *highlighted* words.")
        hlwords = firstDoc.get("hlwords")
        self.assertIsNotNone(hlwords)
        if hlwords:
            self.assertEqual(set(hlwords), {"sample", "highlighted"})
        mimetypes = firstDoc.get("mimetypes")
        self.assertIsNotNone(mimetypes)
        self.assertEqual(mimetypes, ["text/html"])

        # Verify second document
        secondDoc = firstGroup["group"][1]
        self.assertEqual(secondDoc["url"], "https://another.com")
        self.assertEqual(secondDoc["domain"], "another.com")
        self.assertEqual(secondDoc["title"], "Another Title")
        self.assertEqual(len(secondDoc["passages"]), 1)
        self.assertEqual(secondDoc["passages"][0], "Another passage without highlighting.")
        self.assertIsNone(secondDoc["hlwords"])

        # Verify second group
        secondGroup = response["groups"][1]
        self.assertEqual(len(secondGroup["group"]), 1)

        # Verify third document
        thirdDoc = secondGroup["group"][0]
        self.assertEqual(thirdDoc["url"], "https://third.com")
        self.assertEqual(thirdDoc["domain"], "third.com")
        self.assertEqual(thirdDoc["title"], "Third Title")
        self.assertEqual(len(thirdDoc["passages"]), 1)
        self.assertEqual(thirdDoc["passages"][0], "Third passage with *different* highlighting.")
        self.assertEqual(thirdDoc["hlwords"], ["different"])

    def testParseErrorResponse(self):
        """Test parsing an error response"""
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
            self.assertEqual(error.get("code"), "INVALID_QUERY")
            self.assertEqual(error.get("message"), "Invalid search query")
            self.assertEqual(error.get("details"), "The query contains forbidden characters")

    def testParseEmptyResponse(self):
        """Test parsing an empty response"""
        # Encode XML to Base64
        base64Xml = base64.b64encode(self.emptyXml.encode("utf-8")).decode("utf-8")

        # Parse response
        response = parseSearchResponse(base64Xml)

        # Verify response structure
        self.assertEqual(response["requestId"], "empty-request")
        self.assertEqual(response["found"], 0)
        self.assertEqual(response["foundHuman"], "No results found")
        self.assertEqual(response["page"], 0)
        self.assertIsNone(response["error"])
        self.assertEqual(len(response["groups"]), 0)

    def testParseInvalidBase64(self):
        """Test parsing invalid Base64 data"""
        with self.assertRaises(ValueError) as context:
            parseSearchResponse("invalid-base64-data")

        self.assertIn("Invalid Base64 encoding", str(context.exception))

    def testParseInvalidXml(self):
        """Test parsing invalid XML"""
        # Create invalid XML
        invalidXml = "<invalid><xml>"
        base64Xml = base64.b64encode(invalidXml.encode("utf-8")).decode("utf-8")

        with self.assertRaises(ValueError) as context:
            parseSearchResponse(base64Xml)

        self.assertIn("Invalid XML format", str(context.exception))

    def testParseErrorResponseFunction(self):
        """Test the dedicated error response parser function"""
        # Encode error XML to Base64
        base64Xml = base64.b64encode(self.errorXml.encode("utf-8")).decode("utf-8")

        # Parse error response
        error = parseErrorResponse(base64Xml)

        # Verify error structure
        self.assertEqual(error["code"], "INVALID_QUERY")
        self.assertEqual(error["message"], "Invalid search query")
        self.assertEqual(error["details"], "The query contains forbidden characters")

    def testParseErrorResponseFunctionWithInvalidData(self):
        """Test error response parser with invalid data"""
        # Test with completely invalid data
        error = parseErrorResponse("invalid-base64-data")

        # Should return a generic error
        self.assertEqual(error["code"], "PARSE_ERROR")
        self.assertIn("Failed to parse error response", error["message"])

    def testComplexPassageParsing(self):
        """Test parsing complex passages with multiple highlighted words"""
        complexXml = """<?xml version="1.0" encoding="utf-8"?>
<search requestid="complex-test" found="1" found-human="Found 1 result" page="0">
    <group>
        <doc url="https://complex.com" domain="complex.com" title="Complex Title">
            <passage>Start text <hlword>first</hlword> middle text <hlword>second</hlword> end text.</passage>
            <passage>Another passage with <hlword>third</hlword> and <hlword>fourth</hlword> words.</passage>
            <mime-type>text/html</mime-type>
        </doc>
    </group>
</search>"""

        # Encode XML to Base64
        base64Xml = base64.b64encode(complexXml.encode("utf-8")).decode("utf-8")

        # Parse response
        response = parseSearchResponse(base64Xml)

        # Verify document
        doc = response["groups"][0]["group"][0]
        self.assertEqual(len(doc["passages"]), 2)
        self.assertEqual(doc["passages"][0], "Start text *first* middle text *second* end text.")
        self.assertEqual(doc["passages"][1], "Another passage with *third* and *fourth* words.")
        hlwords = doc.get("hlwords")
        self.assertIsNotNone(hlwords)
        if hlwords:
            self.assertEqual(set(hlwords), {"first", "second", "third", "fourth"})


if __name__ == "__main__":
    unittest.main()
