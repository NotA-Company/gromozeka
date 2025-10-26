from typing import NotRequired, TypedDict


class UserMetadataDict(TypedDict):
    notSpammer: NotRequired[bool]  # True if user defined as not spammer
