"""
XML parser for Yandex Search API responses

This module provides utilities for parsing Base64-encoded XML responses
from the Yandex Search API and converting them to structured Python objects.

The Yandex Search API returns search results as Base64-encoded XML data.
This module handles the decoding, parsing, and conversion of this data
into the SearchResponse TypedDict structure defined in models.py.

Key features:
- Base64 decoding of API responses
- XML parsing with error handling
- Extraction of search results and metadata
- Handling of highlighted words in passages
- Graceful error handling for malformed responses

Example:
    ```python
    # Parse a response from the API
    base64_xml = "PHhtbC4uLj48L3htbD4="  # Base64-encoded XML
    response = parseSearchResponse(base64_xml)

    if response['error']:
        print(f"Search failed: {response['error']['message']}")
    else:
        print(f"Found {response['found']} results")
        for group in response['groups']:
            for doc in group['group']:
                print(f"Title: {doc['title']}")
    ```
"""

import base64
import binascii
import logging
import xml.etree.ElementTree as ET
from typing import Optional

from .models import ErrorResponse, SearchGroup, SearchResponse, SearchResult

logger = logging.getLogger(__name__)


def parseSearchResponse(base64Xml: str) -> SearchResponse:
    """
    Parse Base64-encoded XML response from Yandex Search API.

    This function decodes the Base64-encoded XML response from the API,
    parses it, and converts it into a structured SearchResponse object.
    It handles both successful responses and error responses from the API.

    The XML structure from Yandex Search API includes:
    - Root element with metadata (requestid, found, found-human, page)
    - Error element (if the search failed)
    - Multiple group elements containing document results
    - Document elements with metadata, passages, and highlighted words

    Args:
        base64Xml (str): Base64-encoded XML response string from the API.
                        This is the value found in the 'result' field of
                        the JSON response from the Yandex Search API.

    Returns:
        SearchResponse: Parsed response structure with the following fields:
            - requestId (str): Unique request identifier
            - found (int): Total number of results found
            - foundHuman (str): Human-readable result count
            - page (int): Current page number
            - groups (List[SearchGroup]): Parsed search result groups
            - error (Optional[Dict]): Error information if search failed

    Raises:
        ValueError: If the Base64 encoding is invalid or XML is malformed.
                    The error message will contain details about the parsing failure.

    Note:
        - Highlighted words in passages are marked with asterisks (*word*)
        - Empty or malformed document elements are skipped with warnings
        - The function logs debug information during parsing
        - All parsing errors are caught and logged, with None returned for
          individual failed elements but the overall structure preserved

    Example:
        ```python
        try:
            response = parseSearchResponse(base64_xml_from_api)
            if response['error']:
                print(f"API Error: {response['error']['message']}")
            else:
                print(f"Found {response['found']} results")
                for group in response['groups']:
                    for doc in group['group']:
                        print(f"{doc['title']}: {doc['url']}")
        except ValueError as e:
            print(f"Failed to parse response: {e}")
        ```
    """
    try:
        # Decode Base64
        xmlBytes = base64.b64decode(base64Xml)
        xmlString = xmlBytes.decode("utf-8")

        logger.debug(f"Decoded XML: {xmlString[:500]}...")  # Log first 500 chars

        # Parse XML
        root = ET.fromstring(xmlString)

        # Check for error response
        errorElement = root.find(".//error")
        if errorElement is not None:
            errorCode = errorElement.get("code", "UNKNOWN_ERROR")
            errorMessage = errorElement.get("message", "Unknown error")
            errorDetails = errorElement.get("details", "")

            logger.error(f"API error: {errorCode} - {errorMessage}")

            return {
                "requestId": "",
                "found": 0,
                "foundHuman": "",
                "page": 0,
                "groups": [],
                "error": {"code": errorCode, "message": errorMessage, "details": errorDetails},
            }

        # Extract response metadata
        requestId = root.get("requestid", "")
        found = int(root.get("found", 0))
        foundHuman = root.get("found-human", "")
        page = int(root.get("page", 0))

        # Parse result groups
        groups = []
        for groupElement in root.findall(".//group"):
            group = _parseGroup(groupElement)
            if group:
                groups.append(group)

        return {
            "requestId": requestId,
            "found": found,
            "foundHuman": foundHuman,
            "page": page,
            "groups": groups,
            "error": None,
        }

    except binascii.Error as e:
        logger.error(f"Base64 decoding error: {e}")
        raise ValueError(f"Invalid Base64 encoding: {e}")
    except ET.ParseError as e:
        logger.error(f"XML parsing error: {e}")
        raise ValueError(f"Invalid XML format: {e}")
    except Exception as e:
        logger.error(f"Unexpected error parsing response: {e}")
        raise ValueError(f"Failed to parse response: {e}")


def _parseGroup(groupElement: ET.Element) -> Optional[SearchGroup]:
    """
    Parse a group element from the XML response.

    This helper function extracts all document elements from a group
    and parses them into SearchResult objects. Groups are used to
    organize related documents together, typically from the same domain.

    Args:
        groupElement (ET.Element): XML element representing a group.
                                  Should contain one or more 'doc' child elements.

    Returns:
        Optional[SearchGroup]: Parsed group structure containing a list of
                              SearchResult objects. Returns None if parsing
                              fails or no valid documents are found.

    Note:
        - Individual document parsing failures are logged as warnings
        - Empty groups (no valid documents) return None
        - The function is tolerant of missing or malformed document elements
    """
    try:
        results = []
        for docElement in groupElement.findall(".//doc"):
            result = _parseDocument(docElement)
            if result:
                results.append(result)

        return {"group": results}

    except Exception as e:
        logger.warning(f"Error parsing group: {e}")
        return None


def _parseDocument(docElement: ET.Element) -> Optional[SearchResult]:
    """
    Parse a document element from the XML response.

    This helper function extracts all document metadata and content from
    a document element, including URL, title, passages, and highlighted
    words. It handles the complex nested structure of document elements
    in the Yandex Search API XML format.

    The document element structure includes:
    - Attributes: url, domain, title, modtime, size, charset
    - Child elements: mime-type, passage (with hlword elements)

    Args:
        docElement (ET.Element): XML element representing a document.
                                Should have attributes for basic metadata
                                and child elements for passages and MIME types.

    Returns:
        Optional[SearchResult]: Parsed document structure with all available
                              fields populated. Returns None if parsing fails.

    Note:
        - Missing attributes are set to empty strings
        - Missing optional elements result in None values
        - Highlighted words are deduplicated across all passages
        - Passage text preserves highlighted words marked with asterisks
        - Parsing failures are logged as warnings
    """
    try:
        # Extract basic document info
        url = docElement.get("url", "")
        domain = docElement.get("domain", "")
        title = docElement.get("title", "")
        modtime = docElement.get("modtime", "")
        size = docElement.get("size", "")
        charset = docElement.get("charset", "")

        # Extract MIME types
        mimetypes = []
        for mimeElement in docElement.findall(".//mime-type"):
            mimetype = mimeElement.text
            if mimetype:
                mimetypes.append(mimetype)

        # Extract passages with highlighted words
        passages = []
        hlwords = []

        for passageElement in docElement.findall(".//passage"):
            passageText = _extractPassageText(passageElement)
            if passageText:
                passages.append(passageText)

            # Extract highlighted words from this passage
            for hlwordElement in passageElement.findall(".//hlword"):
                hlword = hlwordElement.text
                if hlword and hlword not in hlwords:
                    hlwords.append(hlword)

        return {
            "url": url,
            "domain": domain,
            "title": title,
            "passages": passages,
            "modtime": modtime,
            "size": size,
            "charset": charset,
            "mimetypes": mimetypes if mimetypes else None,
            "hlwords": hlwords if hlwords else None,
        }

    except Exception as e:
        logger.warning(f"Error parsing document: {e}")
        return None


def _extractPassageText(passageElement: ET.Element) -> str:
    """
    Extract text from a passage element, preserving highlighted words.

    This helper function reconstructs the passage text from the XML element,
    properly handling text nodes, child elements, and highlighted words.
    Highlighted words (hlword elements) are wrapped in asterisks to
    maintain the highlighting information in the plain text output.

    The passage element structure:
    <passage>
        Text before highlighted word
        <hlword>highlighted</hlword>
        Text after highlighted word
        <hlword>another</hlword>
        More text
    </passage>

    Args:
        passageElement (ET.Element): XML element representing a passage.
                                   May contain text nodes and hlword child elements.

    Returns:
        str: Reconstructed passage text with highlighted words marked
             with asterisks (e.g., "This is *highlighted* text").
             Returns empty string if extraction fails.

    Note:
        - Text before and after child elements is preserved
        - Only hlword elements are specially handled
        - Other child elements are treated as plain text
        - Whitespace is preserved as in the original XML
        - The result is stripped of leading/trailing whitespace
    """
    try:
        # Build text content, handling highlighted words
        textParts = []

        if passageElement.text:
            textParts.append(passageElement.text)

        for child in passageElement:
            if child.tag == "hlword":
                # Mark highlighted words with asterisks
                textParts.append(f"*{child.text}*")
                if child.tail:
                    textParts.append(child.tail)
            else:
                if child.text:
                    textParts.append(child.text)
                if child.tail:
                    textParts.append(child.tail)

        return "".join(textParts).strip()

    except Exception as e:
        logger.warning(f"Error extracting passage text: {e}")
        return passageElement.text or ""


def parseErrorResponse(base64Xml: str) -> ErrorResponse:
    """
    Parse Base64-encoded XML error response from the Yandex Search API.

    This function specifically handles error responses from the API,
    extracting error codes, messages, and additional details. It's used
    when the API returns an error response instead of search results.

    The error XML structure:
    <response>
        <error code="ERROR_CODE" message="Error message" details="Additional info" />
    </response>

    Args:
        base64Xml (str): Base64-encoded XML error response from the API.
                        This is typically found in the 'result' field when
                        the API returns an error status.

    Returns:
        ErrorResponse: Parsed error structure with the following fields:
            - code (str): Machine-readable error code
            - message (str): Human-readable error message
            - details (str): Additional error details (may be empty)

    Note:
        - If no error element is found, a generic error is returned
        - Missing attributes default to empty strings
        - Parsing errors are logged but don't raise exceptions
        - This function is more tolerant than parseSearchResponse()

    Example:
        ```python
        error = parseErrorResponse(base64_error_xml)
        print(f"Error {error['code']}: {error['message']}")
        if error['details']:
            print(f"Details: {error['details']}")
        ```
    """
    try:
        # Decode Base64
        xmlBytes = base64.b64decode(base64Xml)
        xmlString = xmlBytes.decode("utf-8")

        # Parse XML
        root = ET.fromstring(xmlString)

        # Extract error information
        errorElement = root.find(".//error")
        if errorElement is None:
            # If no error element, create a generic error
            return {"code": "UNKNOWN_ERROR", "message": "Unknown error occurred", "details": ""}

        errorCode = errorElement.get("code", "UNKNOWN_ERROR")
        errorMessage = errorElement.get("message", "Unknown error")
        errorDetails = errorElement.get("details", "")

        return {"code": errorCode, "message": errorMessage, "details": errorDetails}

    except Exception as e:
        logger.error(f"Error parsing error response: {e}")
        return {"code": "PARSE_ERROR", "message": f"Failed to parse error response: {str(e)}", "details": ""}
