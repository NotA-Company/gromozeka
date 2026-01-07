from typing import TypedDict


class UserMetadataDict(TypedDict, total=False):
    """
    Typed Dict of user metadata JSON
    """
    isSpammer: bool
    """True if user defined as spammer"""
    notSpammer: bool
    """True if user defined as not spammer"""
    dropMessages: bool
    """True if bot need to delete all new user messages"""
