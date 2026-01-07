from typing import NotRequired, TypedDict


class UserMetadataDict(TypedDict):
    notSpammer: NotRequired[bool]  # True if user defined as not spammer
    dropMessages: NotRequired[bool]  # True if bot need to delete all new user messages
