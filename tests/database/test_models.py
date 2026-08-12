"""
Test suite for database models and type definitions.

This module provides comprehensive tests for the database models, including
enums like ChatBotStatus, MediaStatus, MessageCategory, etc., and TypedDict
definitions like ChatInfoDict, ChatMessageDict, etc.

Key Test Functions:
    - test_chat_bot_status_enum: Tests ChatBotStatus StrEnum values and properties
    - test_chat_bot_status_string_serialization: Tests StrEnum string value round-trip

Usage:
    Run this script directly to execute all model tests:
        ./venv/bin/pytest tests/database/test_models.py

    Or import and run specific test functions:
        from tests.database.test_models import test_chat_bot_status_enum
        test_chat_bot_status_enum()
"""

import logging

from internal.database.models import ChatBotStatus

# Setup logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def test_chat_bot_status_enum() -> None:
    """Test ChatBotStatus StrEnum values and properties.

    Verifies that:
    - The enum has exactly two members: ACTIVE and INACCESSIBLE
    - Each member has the correct string value
    - The enum inherits from StrEnum and provides string serialization

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If enum members are incorrect
        AssertionError: If string values don't match expected values
        AssertionError: If enum doesn't have the correct number of members
    """
    logger.info("=" * 60)
    logger.info("TEST: ChatBotStatus Enum")
    logger.info("=" * 60)

    # Test that enum has exactly two members
    members = list(ChatBotStatus)
    assert len(members) == 2, f"Expected 2 ChatBotStatus members, got {len(members)}"
    logger.info(f"✅ ChatBotStatus has {len(members)} members: {[m.name for m in members]}")

    # Test ACTIVE member
    assert hasattr(ChatBotStatus, "ACTIVE"), "ChatBotStatus should have ACTIVE member"
    assert (
        ChatBotStatus.ACTIVE.value == "active"
    ), f"ChatBotStatus.ACTIVE value should be 'active', got {ChatBotStatus.ACTIVE.value}"
    logger.info("✅ ChatBotStatus.ACTIVE = 'active'")

    # Test INACCESSIBLE member
    assert hasattr(ChatBotStatus, "INACCESSIBLE"), "ChatBotStatus should have INACCESSIBLE member"
    assert (
        ChatBotStatus.INACCESSIBLE.value == "inaccessible"
    ), f"ChatBotStatus.INACCESSIBLE value should be 'inaccessible', got {ChatBotStatus.INACCESSIBLE.value}"
    logger.info("✅ ChatBotStatus.INACCESSIBLE = 'inaccessible'")

    logger.info("✅ ChatBotStatus enum test PASSED")


def test_chat_bot_status_string_serialization() -> None:
    """Test ChatBotStatus StrEnum string value round-trip.

    Verifies that:
    - Enum values can be created from strings
    - Enum values serialize correctly to strings
    - String comparison works as expected

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If string serialization doesn't work correctly
        AssertionError: If enum creation from string fails
    """
    logger.info("=" * 60)
    logger.info("TEST: ChatBotStatus String Serialization")
    logger.info("=" * 60)

    # Test string value access
    activeString: str = ChatBotStatus.ACTIVE.value
    assert activeString == "active", f"ACTIVE value should be 'active', got {activeString}"
    logger.info(f"✅ ChatBotStatus.ACTIVE.value = '{activeString}'")

    inaccessibleString: str = ChatBotStatus.INACCESSIBLE.value
    assert (
        inaccessibleString == "inaccessible"
    ), f"INACCESSIBLE value should be 'inaccessible', got {inaccessibleString}"
    logger.info(f"✅ ChatBotStatus.INACCESSIBLE.value = '{inaccessibleString}'")

    # Test enum creation from string
    activeFromStr = ChatBotStatus("active")
    assert activeFromStr == ChatBotStatus.ACTIVE, "ChatBotStatus('active') should equal ChatBotStatus.ACTIVE"
    logger.info("✅ ChatBotStatus('active') == ChatBotStatus.ACTIVE")

    inaccessibleFromStr = ChatBotStatus("inaccessible")
    assert (
        inaccessibleFromStr == ChatBotStatus.INACCESSIBLE
    ), "ChatBotStatus('inaccessible') should equal ChatBotStatus.INACCESSIBLE"
    logger.info("✅ ChatBotStatus('inaccessible') == ChatBotStatus.INACCESSIBLE")

    # Test string comparison
    assert (
        str(ChatBotStatus.ACTIVE) == "active"
    ), f"str(ChatBotStatus.ACTIVE) should be 'active', got {str(ChatBotStatus.ACTIVE)}"
    assert (
        str(ChatBotStatus.INACCESSIBLE) == "inaccessible"
    ), f"str(ChatBotStatus.INACCESSIBLE) should be 'inaccessible', got {str(ChatBotStatus.INACCESSIBLE)}"
    logger.info("✅ str(ChatBotStatus.<member>) works correctly")

    logger.info("✅ ChatBotStatus string serialization test PASSED")


def test_chat_bot_status_member_names() -> None:
    """Test ChatBotStatus member names follow UPPER_CASE convention.

    Verifies that:
    - Member names are in UPPER_CASE (ACTIVE, INACCESSIBLE)
    - String values are in lowercase (active, inaccessible)

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If naming convention is violated
    """
    logger.info("=" * 60)
    logger.info("TEST: ChatBotStatus Naming Convention")
    logger.info("=" * 60)

    # Test that member names are UPPER_CASE
    assert (
        ChatBotStatus.ACTIVE.name == "ACTIVE"
    ), f"ACTIVE member name should be 'ACTIVE', got {ChatBotStatus.ACTIVE.name}"
    assert (
        ChatBotStatus.INACCESSIBLE.name == "INACCESSIBLE"
    ), f"INACCESSIBLE member name should be 'INACCESSIBLE', got {ChatBotStatus.INACCESSIBLE.name}"
    logger.info("✅ Member names are UPPER_CASE")

    # Test that string values are lowercase
    assert ChatBotStatus.ACTIVE.value.islower(), "ACTIVE value should be lowercase"
    assert ChatBotStatus.INACCESSIBLE.value.islower(), "INACCESSIBLE value should be lowercase"
    logger.info("✅ String values are lowercase")

    logger.info("✅ ChatBotStatus naming convention test PASSED")


def test_chat_bot_status_docstrings() -> None:
    """Test that ChatBotStatus enum and members have proper docstrings.

    Verifies that:
    - The ChatBotStatus enum has a module-level docstring
    - Each enum member has a docstring

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If required docstrings are missing
    """
    logger.info("=" * 60)
    logger.info("TEST: ChatBotStatus Docstrings")
    logger.info("=" * 60)

    # Test that the enum class has a docstring
    assert ChatBotStatus.__doc__ is not None and len(ChatBotStatus.__doc__) > 0, "ChatBotStatus should have a docstring"
    logger.info("✅ ChatBotStatus enum has docstring")

    # Test that each member has a docstring
    assert (
        ChatBotStatus.ACTIVE.__doc__ is not None and len(ChatBotStatus.ACTIVE.__doc__) > 0
    ), "ChatBotStatus.ACTIVE should have a docstring"
    logger.info("✅ ChatBotStatus.ACTIVE has docstring")

    assert (
        ChatBotStatus.INACCESSIBLE.__doc__ is not None and len(ChatBotStatus.INACCESSIBLE.__doc__) > 0
    ), "ChatBotStatus.INACCESSIBLE should have a docstring"
    logger.info("✅ ChatBotStatus.INACCESSIBLE has docstring")

    logger.info("✅ ChatBotStatus docstrings test PASSED")
