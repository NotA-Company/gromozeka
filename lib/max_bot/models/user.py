"""
User models for Max Messenger Bot API.

This module contains user-related dataclasses including User, UserWithPhoto,
BotInfo, BotCommand, and BotPatch models.
"""

from typing import Any, Dict, List, Optional

from .base import BaseMaxBotModel


class User(BaseMaxBotModel):
    """
    Объект, описывающий пользователя. Имеет несколько вариаций (наследований):

    - [`User`](/docs-api/objects/User)
    - [`UserWithPhoto`](/docs-api/objects/UserWithPhoto)
    - [`BotInfo`](/docs-api/objects/BotInfo)
    - [`ChatMember`](/docs-api/objects/ChatMember)
    """

    __slots__ = (
        "user_id",
        "first_name",
        "last_name",
        "username",
        "is_bot",
        "last_activity_time",
    )

    # user_id: int
    # """ID пользователя"""
    # first_name: str
    # """Отображаемое имя пользователя"""
    # last_name: Optional[str] = None
    # """Отображаемая фамилия пользователя"""
    # name: Optional[str] = None
    # """_Устаревшее поле, скоро будет удалено_"""
    # username: Optional[str] = None
    # """Уникальное публичное имя пользователя. Может быть `null`, если пользователь недоступен или имя не задано"""
    # is_bot: bool = False
    # """`true`,  если пользователь является ботом"""
    # last_activity_time: int = 0
    # """Время последней активности пользователя в MAX (Unix-время в миллисекундах). Может быть неактуальным, если пользователь отключил статус "онлайн" в настройках."""  # noqa: E501

    def __init__(
        self,
        *,
        user_id: int,
        first_name: str,
        last_name: Optional[str] = None,
        username: Optional[str] = None,
        is_bot: bool = False,
        last_activity_time: int = 0,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.user_id: int = user_id
        self.first_name: str = first_name
        self.last_name: Optional[str] = last_name
        self.username: Optional[str] = username
        self.is_bot: bool = is_bot
        self.last_activity_time: int = last_activity_time

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "User":
        """Create User instance from API response dictionary.

        Args:
            data: Dictionary containing API response data

        Returns:
            User: New User instance
        """
        return cls(
            user_id=data.get("user_id", 0),
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name", None),
            username=data.get("username", None),
            is_bot=data.get("is_bot", False),
            last_activity_time=data.get("last_activity_time", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class UserWithPhoto(User):
    """
    Объект пользователя с фотографией
    """

    __slots__ = ("description", "avatar_url", "full_avatar_url")

    def __init__(
        self,
        *,
        description: Optional[str] = None,
        avatar_url: Optional[str] = None,
        full_avatar_url: Optional[str] = None,
        user_id: int,
        first_name: str,
        last_name: str | None = None,
        username: str | None = None,
        is_bot: bool = False,
        last_activity_time: int = 0,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(
            user_id=user_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
            is_bot=is_bot,
            last_activity_time=last_activity_time,
            api_kwargs=api_kwargs,
        )
        self.description: Optional[str] = description
        """
        Описание пользователя.
        Может быть `null`, если пользователь его не заполнил
        """
        self.avatar_url: Optional[str] = avatar_url
        """URL аватара"""
        self.full_avatar_url: Optional[str] = full_avatar_url
        """URL аватара большего размера"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserWithPhoto":
        """Create UserWithPhoto instance from API response dictionary.

        Args:
            data: Dictionary containing API response data

        Returns:
            UserWithPhoto: New UserWithPhoto instance
        """
        return cls(
            description=data.get("description", None),
            avatar_url=data.get("avatar_url", None),
            full_avatar_url=data.get("full_avatar_url", None),
            user_id=data.get("user_id", 0),
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name", None),
            username=data.get("username", None),
            is_bot=data.get("is_bot", False),
            last_activity_time=data.get("last_activity_time", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class BotCommand(BaseMaxBotModel):
    """
    до 32 элементов
    Комманды, поддерживаемые ботом
    """

    __slots__ = ("name", "description")

    # name: str
    # """Название команды"""
    # description: Optional[str] = None
    # """Описание команды (по желанию)"""

    def __init__(self, *, name: str, description: Optional[str] = None, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(api_kwargs=api_kwargs)
        self.name: str = name
        self.description: Optional[str] = description

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BotCommand":
        """Create BotCommand instance from API response dictionary.

        Args:
            data: Dictionary containing API response data

        Returns:
            BotCommand: New BotCommand instance
        """
        return cls(
            name=data.get("name", ""),
            description=data.get("description"),
            api_kwargs=cls._getExtraKwargs(data),
        )


class BotInfo(UserWithPhoto):
    """
    Объект, описывающий информацию о боте
    """

    __slots__ = ("commands",)

    def __init__(
        self,
        *,
        commands: Optional[List[BotCommand]] = None,
        description: str | None = None,
        avatar_url: str | None = None,
        full_avatar_url: str | None = None,
        user_id: int,
        first_name: str,
        last_name: str | None = None,
        username: str | None = None,
        is_bot: bool = False,
        last_activity_time: int = 0,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(
            description=description,
            avatar_url=avatar_url,
            full_avatar_url=full_avatar_url,
            user_id=user_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
            is_bot=is_bot,
            last_activity_time=last_activity_time,
            api_kwargs=api_kwargs,
        )
        self.commands: Optional[List[BotCommand]] = commands
        """Команды, поддерживаемые ботом"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BotInfo":
        """Create BotInfo instance from API response dictionary.

        Args:
            data: Dictionary containing API response data

        Returns:
            BotInfo: New BotInfo instance
        """
        commands: Optional[List[BotCommand]] = None
        commands = None
        if data.get("commands", None) is not None:
            commands = [BotCommand.from_dict(cmd) for cmd in data.get("commands", [])]

        return cls(
            commands=commands,
            description=data.get("description"),
            avatar_url=data.get("avatar_url"),
            full_avatar_url=data.get("full_avatar_url"),
            user_id=data.get("user_id", 0),
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name"),
            username=data.get("username"),
            is_bot=data.get("is_bot", False),
            last_activity_time=data.get("last_activity_time", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class BotPatch(BaseMaxBotModel):
    """
    Bot patch model
    NOTE: Looks like unused right now
    """

    __slots__ = ("first_name", "last_name", "description", "commands", "photo")

    def __init__(
        self,
        *,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        description: Optional[str] = None,
        commands: Optional[List[BotCommand]] = None,
        photo: Optional[Dict[str, Any]] = None,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.first_name: Optional[str] = first_name
        """Отображаемое имя бота"""
        self.last_name: Optional[str] = last_name
        """Отображаемое второе имя бота"""
        self.description: Optional[str] = description
        """Описание бота"""
        self.commands: Optional[List[BotCommand]] = commands
        """
        Команды, поддерживаемые ботом.
        Чтобы удалить все команды, передайте пустой список
        """
        self.photo: Optional[Dict[str, Any]] = photo
        """Запрос на установку фото бота"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BotPatch":
        """Create BotPatch instance from API response dictionary.

        Args:
            data: Dictionary containing API response data

        Returns:
            BotPatch: New BotPatch instance
        """
        commandsData = data.get("commands", None)
        commands = None
        if commandsData is not None:
            commands = [BotCommand.from_dict(cmd) for cmd in commandsData]

        return cls(
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
            description=data.get("description"),
            commands=commands,
            photo=data.get("photo"),
            api_kwargs=cls._getExtraKwargs(data),
        )
