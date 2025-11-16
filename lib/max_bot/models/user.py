"""
User models for Max Messenger Bot API.

This module contains user-related dataclasses including User, UserWithPhoto,
BotInfo, BotCommand, and BotPatch models.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(slots=True)
class User:
    """
    Объект, описывающий пользователя. Имеет несколько вариаций (наследований):

    - [`User`](/docs-api/objects/User)
    - [`UserWithPhoto`](/docs-api/objects/UserWithPhoto)
    - [`BotInfo`](/docs-api/objects/BotInfo)
    - [`ChatMember`](/docs-api/objects/ChatMember)
    """

    user_id: int
    """ID пользователя"""
    first_name: str
    """Отображаемое имя пользователя"""
    last_name: Optional[str] = None
    """Отображаемая фамилия пользователя"""
    name: Optional[str] = None
    """_Устаревшее поле, скоро будет удалено_"""
    username: Optional[str] = None
    """Уникальное публичное имя пользователя. Может быть `null`, если пользователь недоступен или имя не задано"""
    is_bot: bool = False
    """`true`,  если пользователь является ботом"""
    last_activity_time: int = 0
    """Время последней активности пользователя в MAX (Unix-время в миллисекундах). Может быть неактуальным, если пользователь отключил статус "онлайн" в настройках."""  # noqa: E501
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "User":
        """Create User instance from API response dictionary."""
        return cls(
            user_id=data.get("user_id", 0),
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name"),
            name=data.get("name"),
            username=data.get("username"),
            is_bot=data.get("is_bot", False),
            last_activity_time=data.get("last_activity_time", 0),
            api_kwargs={
                k: v
                for k, v in data.items()
                if k not in {"user_id", "first_name", "last_name", "name", "username", "is_bot", "last_activity_time"}
            },
        )


@dataclass(slots=True)
class UserWithPhoto(User):
    """
    Объект пользователя с фотографией
    """

    description: Optional[str] = None
    """Описание пользователя. Может быть `null`, если пользователь его не заполнил"""
    avatar_url: Optional[str] = None
    """URL аватара"""
    full_avatar_url: Optional[str] = None
    """URL аватара большего размера"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserWithPhoto":
        """Create UserWithPhoto instance from API response dictionary."""
        return cls(
            user_id=data.get("user_id", 0),
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name"),
            name=data.get("name"),
            username=data.get("username"),
            is_bot=data.get("is_bot", False),
            last_activity_time=data.get("last_activity_time", 0),
            description=data.get("description"),
            avatar_url=data.get("avatar_url"),
            full_avatar_url=data.get("full_avatar_url"),
            api_kwargs={
                k: v
                for k, v in data.items()
                if k
                not in {
                    "user_id",
                    "first_name",
                    "last_name",
                    "name",
                    "username",
                    "is_bot",
                    "last_activity_time",
                    "description",
                    "avatar_url",
                    "full_avatar_url",
                }
            },
        )


@dataclass(slots=True)
class BotCommand:
    """
    до 32 элементов<br/>Комманды, поддерживаемые ботом
    """

    name: str
    """Название команды"""
    description: Optional[str] = None
    """Описание команды (по желанию)"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BotCommand":
        """Create BotCommand instance from API response dictionary."""
        return cls(
            name=data.get("name", ""),
            description=data.get("description"),
            api_kwargs={k: v for k, v in data.items() if k not in {"name", "description"}},
        )


@dataclass(slots=True)
class BotInfo(UserWithPhoto):
    """
    Объект, описывающий информацию о боте
    """

    commands: Optional[List[BotCommand]] = None
    """Команды, поддерживаемые ботом"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BotInfo":
        """Create BotInfo instance from API response dictionary."""
        commands_data = data.get("commands")
        commands = None
        if commands_data:
            commands = [BotCommand.from_dict(cmd) for cmd in commands_data]

        return cls(
            user_id=data.get("user_id", 0),
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name"),
            name=data.get("name"),
            username=data.get("username"),
            is_bot=data.get("is_bot", False),
            last_activity_time=data.get("last_activity_time", 0),
            description=data.get("description"),
            avatar_url=data.get("avatar_url"),
            full_avatar_url=data.get("full_avatar_url"),
            commands=commands,
            api_kwargs={
                k: v
                for k, v in data.items()
                if k
                not in {
                    "user_id",
                    "first_name",
                    "last_name",
                    "name",
                    "username",
                    "is_bot",
                    "last_activity_time",
                    "description",
                    "avatar_url",
                    "full_avatar_url",
                    "commands",
                }
            },
        )


@dataclass(slots=True)
class BotPatch:
    """
    Bot patch model for updating bot information
    """

    first_name: Optional[str] = None
    """Отображаемое имя бота"""
    last_name: Optional[str] = None
    """Отображаемое второе имя бота"""
    name: Optional[str] = None
    """_Поле устарело, скоро будет удалено. Используйте_ `first_name`"""
    description: Optional[str] = None
    """Описание бота"""
    commands: Optional[List[BotCommand]] = None
    """Команды, поддерживаемые ботом. Чтобы удалить все команды, передайте пустой список"""
    photo: Optional[Dict[str, Any]] = None
    """Запрос на установку фото бота"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BotPatch":
        """Create BotPatch instance from API response dictionary."""
        commands_data = data.get("commands")
        commands = None
        if commands_data:
            commands = [BotCommand.from_dict(cmd) for cmd in commands_data]

        return cls(
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
            name=data.get("name"),
            description=data.get("description"),
            commands=commands,
            photo=data.get("photo"),
            api_kwargs={
                k: v
                for k, v in data.items()
                if k not in {"first_name", "last_name", "name", "description", "commands", "photo"}
            },
        )
