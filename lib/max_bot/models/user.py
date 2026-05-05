"""
User models for Max Messenger Bot API.

This module contains user-related dataclasses including User, UserWithPhoto,
BotInfo, BotCommand, and BotPatch models.
"""

from typing import Any, Dict, List, Optional

from .base import BaseMaxBotModel


class User(BaseMaxBotModel):
    """User object representing a Max Messenger user.

    This class represents a user in the Max Messenger system. It has several
    variations through inheritance:
    - [`User`](/docs-api/objects/User)
    - [`UserWithPhoto`](/docs-api/objects/UserWithPhoto)
    - [`BotInfo`](/docs-api/objects/BotInfo)
    - [`ChatMember`](/docs-api/objects/ChatMember)

    Attributes:
        user_id: Unique identifier for the user.
        first_name: Display name of the user.
        last_name: Display surname of the user. Can be None if not set.
        username: Unique public username. Can be None if user is unavailable
            or username is not set.
        is_bot: True if the user is a bot, False otherwise.
        last_activity_time: Time of last user activity in MAX (Unix timestamp
            in milliseconds). May be outdated if user disabled online status
            in settings.
    """

    __slots__ = (
        "user_id",
        "first_name",
        "last_name",
        "username",
        "is_bot",
        "last_activity_time",
    )

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
        """Initialize a User instance.

        Args:
            user_id: Unique identifier for the user.
            first_name: Display name of the user.
            last_name: Display surname of the user. Defaults to None.
            username: Unique public username. Defaults to None.
            is_bot: True if the user is a bot. Defaults to False.
            last_activity_time: Time of last user activity in MAX (Unix timestamp
                in milliseconds). Defaults to 0.
            api_kwargs: Additional API keyword arguments not covered by the model.
                Defaults to None.
        """
        super().__init__(api_kwargs=api_kwargs)
        self.user_id: int = user_id
        """ID пользователя"""
        self.first_name: str = first_name
        """Отображаемое имя пользователя"""
        self.last_name: Optional[str] = last_name
        """Отображаемая фамилия пользователя"""
        self.username: Optional[str] = username
        """Уникальное публичное имя пользователя. Может быть `null`, если пользователь недоступен или имя не задано"""
        self.is_bot: bool = is_bot
        """`true`,  если пользователь является ботом"""
        self.last_activity_time: int = last_activity_time
        """Время последней активности пользователя в MAX (Unix-время в миллисекундах). Может быть неактуальным, если пользователь отключил статус "онлайн" в настройках."""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "User":
        """Create User instance from API response dictionary.

        Args:
            data: Dictionary containing API response data with user information.

        Returns:
            User: New User instance populated with data from the dictionary.
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
    """User object with photo information.

    Extends the User class to include user description and avatar URLs.

    Attributes:
        description: User description. Can be None if user hasn't filled it.
        avatar_url: URL of the user's avatar.
        full_avatar_url: URL of the user's avatar in larger size.
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
        """Initialize a UserWithPhoto instance.

        Args:
            description: User description. Defaults to None.
            avatar_url: URL of the user's avatar. Defaults to None.
            full_avatar_url: URL of the user's avatar in larger size. Defaults to None.
            user_id: Unique identifier for the user.
            first_name: Display name of the user.
            last_name: Display surname of the user. Defaults to None.
            username: Unique public username. Defaults to None.
            is_bot: True if the user is a bot. Defaults to False.
            last_activity_time: Time of last user activity in MAX (Unix timestamp
                in milliseconds). Defaults to 0.
            api_kwargs: Additional API keyword arguments not covered by the model.
                Defaults to None.
        """
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
            data: Dictionary containing API response data with user and photo information.

        Returns:
            UserWithPhoto: New UserWithPhoto instance populated with data from the dictionary.
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
    """Bot command supported by a bot.

    Represents a command that a bot can handle. Bots can have up to 32 commands.

    Attributes:
        name: Command name (e.g., "start", "help").
        description: Command description. Optional but recommended for better UX.
    """

    __slots__ = ("name", "description")

    def __init__(self, *, name: str, description: Optional[str] = None, api_kwargs: Dict[str, Any] | None = None):
        """Initialize a BotCommand instance.

        Args:
            name: Command name (e.g., "start", "help").
            description: Command description. Defaults to None.
            api_kwargs: Additional API keyword arguments not covered by the model.
                Defaults to None.
        """
        super().__init__(api_kwargs=api_kwargs)
        self.name: str = name
        """Название команды"""
        self.description: Optional[str] = description
        """Описание команды (по желанию)"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BotCommand":
        """Create BotCommand instance from API response dictionary.

        Args:
            data: Dictionary containing API response data with command information.

        Returns:
            BotCommand: New BotCommand instance populated with data from the dictionary.
        """
        return cls(
            name=data.get("name", ""),
            description=data.get("description"),
            api_kwargs=cls._getExtraKwargs(data),
        )


class BotInfo(UserWithPhoto):
    """Bot information object.

    Extends UserWithPhoto to include bot-specific information such as supported commands.

    Attributes:
        commands: List of commands supported by the bot. Can be None if no commands are set.
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
        """Initialize a BotInfo instance.

        Args:
            commands: List of commands supported by the bot. Defaults to None.
            description: Bot description. Defaults to None.
            avatar_url: URL of the bot's avatar. Defaults to None.
            full_avatar_url: URL of the bot's avatar in larger size. Defaults to None.
            user_id: Unique identifier for the bot.
            first_name: Display name of the bot.
            last_name: Display surname of the bot. Defaults to None.
            username: Unique public username. Defaults to None.
            is_bot: True if the user is a bot. Defaults to False.
            last_activity_time: Time of last bot activity in MAX (Unix timestamp
                in milliseconds). Defaults to 0.
            api_kwargs: Additional API keyword arguments not covered by the model.
                Defaults to None.
        """
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

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BotInfo":
        """Create BotInfo instance from API response dictionary.

        Args:
            data: Dictionary containing API response data with bot information.

        Returns:
            BotInfo: New BotInfo instance populated with data from the dictionary.
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
    """Bot patch model for updating bot information.

    This model is used to update bot information. Note: Currently appears to be unused.

    Attributes:
        first_name: Display name of the bot. Can be None to keep existing value.
        last_name: Display surname of the bot. Can be None to keep existing value.
        description: Bot description. Can be None to keep existing value.
        commands: List of commands supported by the bot. Pass empty list to remove
            all commands. Can be None to keep existing commands.
        photo: Request to set bot photo. Can be None to keep existing photo.
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
        """Initialize a BotPatch instance.

        Args:
            first_name: Display name of the bot. Defaults to None (keep existing).
            last_name: Display surname of the bot. Defaults to None (keep existing).
            description: Bot description. Defaults to None (keep existing).
            commands: List of commands supported by the bot. Pass empty list to remove
                all commands. Defaults to None (keep existing).
            photo: Request to set bot photo. Defaults to None (keep existing).
            api_kwargs: Additional API keyword arguments not covered by the model.
                Defaults to None.
        """
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
            data: Dictionary containing API response data with bot patch information.

        Returns:
            BotPatch: New BotPatch instance populated with data from the dictionary.
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
