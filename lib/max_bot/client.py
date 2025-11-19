"""
Max Bot Async Client

This module provides the main MaxBotClient class for interacting with
the Max Messenger Bot API using httpx with proper authentication and error handling.
"""

import asyncio
import logging
from collections.abc import Awaitable
from typing import Any, Callable, Dict, List, Optional, Union
from urllib.parse import urljoin

import httpx

from lib import utils
from lib.max_bot.models.keyboard import Button, Keyboard

from .constants import (
    API_BASE_URL,
    CONTENT_TYPE_JSON,
    DEFAULT_TIMEOUT,
    HTTP_DELETE,
    HTTP_GET,
    HTTP_PATCH,
    HTTP_POST,
    HTTP_PUT,
    MAX_RETRIES,
    RETRY_BACKOFF_FACTOR,
    VERSION,
)
from .exceptions import (
    AuthenticationError,
    MaxBotError,
    NetworkError,
    ValidationError,
    parseApiError,
)
from .models import (
    Attachment,
    AttachmentPayload,
    BotInfo,
    Chat,
    ChatAdmin,
    ChatList,
    ChatMembersList,
    InlineKeyboardAttachment,
    Message,
    MessageLinkType,
    MessageList,
    NewMessageBody,
    NewMessageLink,
    PhotoAttachment,
    PhotoAttachmentPayload,
    PhotoUploadResult,
    ReplyKeyboardAttachment,
    SenderAction,
    SendMessageResult,
    TextFormat,
    UpdateList,
    UploadedAttachment,
    UploadedPhoto,
    UploadEndpoint,
    UploadType,
)
from .models.update import Update

logger = logging.getLogger(__name__)

# Enable extended debug. Useful only for Client debugging
EXTENDED_DEBUG: bool = True


class MaxBotClient:
    """Async client for Max Messenger Bot API with authentication and error handling, dood!

    Provides a clean, type-safe interface for interacting with the Max Messenger Bot API.
    Handles authentication, request/response processing, error handling, and retries.

    The client supports async context manager usage for proper resource cleanup:

    Example:
        >>> from lib.max_bot import MaxBotClient
        >>>
        >>> async with MaxBotClient("your_access_token") as client:
        ...     bot_info = await client.getMyInfo()
        ...     print(f"Bot name: {bot_info['name']}")

    Or manual management:
        >>> client = MaxBotClient("your_access_token")
        >>> try:
        ...     bot_info = await client.getMyInfo()
        ... finally:
        ...     await client.aclose()

    Attributes:
        accessToken: The bot access token for API authentication
        baseUrl: Base URL for the API (default: https://platform-api.max.ru)
        timeout: Request timeout in seconds (default: 30)
        maxRetries: Maximum number of retry attempts (default: 3)
        retryBackoffFactor: Backoff factor for retry delays (default: 1.0)
    """

    __slots__ = (
        "accessToken",
        "baseUrl",
        "timeout",
        "maxRetries",
        "retryBackoffFactor",
        "_httpClient",
        "_pollingTask",
        "_isPolling",
        "_myInfo",
    )

    def __init__(
        self,
        accessToken: str,
        baseUrl: str = API_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
        maxRetries: int = MAX_RETRIES,
        retryBackoffFactor: float = RETRY_BACKOFF_FACTOR,
    ) -> None:
        """Initialize the Max Bot client.

        Args:
            accessToken: Bot access token for API authentication
            baseUrl: Base URL for the API (default: https://platform-api.max.ru)
            timeout: Request timeout in seconds (default: 30)
            maxRetries: Maximum number of retry attempts (default: 3)
            retryBackoffFactor: Backoff factor for retry delays (default: 1.0)

        Raises:
            ConfigurationError: If accessToken is empty or invalid
        """
        if not accessToken or not accessToken.strip():
            raise MaxBotError("Access token cannot be empty")

        self.accessToken = accessToken.strip()
        self.baseUrl = baseUrl.rstrip("/")
        self.timeout = timeout
        self.maxRetries = maxRetries
        self.retryBackoffFactor = retryBackoffFactor
        self._httpClient: Optional[httpx.AsyncClient] = None
        self._pollingTask: Optional[asyncio.Task] = None
        self._isPolling = False
        self._myInfo: Optional[BotInfo] = None

        logger.debug(f"MaxBotClient initialized for {self.baseUrl}")

    async def __aenter__(self) -> "MaxBotClient":
        """Async context manager entry point.

        Returns:
            Self for context manager usage
        """
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit point.

        Args:
            exc_type: Exception type (if any)
            exc_val: Exception value (if any)
            exc_tb: Exception traceback (if any)
        """
        await self.aclose()

    def _getHttpClient(self) -> httpx.AsyncClient:
        """Get or create the HTTP client with proper configuration.

        Returns:
            Configured httpx.AsyncClient instance
        """
        if self._httpClient is None or self._httpClient.is_closed:
            self._httpClient = httpx.AsyncClient(
                base_url=self.baseUrl,
                timeout=httpx.Timeout(self.timeout),
                headers={
                    "User-Agent": f"Gromozeka/{VERSION}",
                },
                # params={"v": "0.0.1"},
            )
            logger.debug("Created new HTTP client")

        self._httpClient.headers.update(
            {
                "Accept": CONTENT_TYPE_JSON,
                "Content-Type": CONTENT_TYPE_JSON,
                "Authorization": self.accessToken,
            }
        )

        return self._httpClient

    async def aclose(self) -> None:
        """Close the HTTP client and cleanup resources."""
        if self._httpClient and not self._httpClient.is_closed:
            await self._httpClient.aclose()
            logger.debug("HTTP client closed")

    def _buildUrl(self, endpoint: str) -> str:
        """Build full URL for API endpoint.

        Args:
            endpoint: API endpoint path (e.g., "/me")

        Returns:
            Full URL for the endpoint
        """
        return urljoin(self.baseUrl + "/", endpoint.lstrip("/"))

    async def _makeRequest(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Make HTTP request with retry logic and error handling.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, PATCH)
            endpoint: API endpoint path
            **kwargs: Additional arguments passed to httpx request

        Returns:
            Parsed JSON response data

        Raises:
            MaxBotError: Various error types based on API response
            NetworkError: For network-related issues
        """
        client = self._getHttpClient()
        url = self._buildUrl(endpoint)

        isUpdatePolling = method == HTTP_GET and endpoint == "/updates"

        if EXTENDED_DEBUG and not isUpdatePolling:
            logger.debug(f"Making {method} request to {url} with body {kwargs}")

        # Log request (without sensitive data)
        logger.debug(f"Making {method} request to {url}")

        last_exception = None
        attempt = 0
        while attempt < self.maxRetries + 1:
            try:
                response = await client.request(method, url, **kwargs)

                # Handle successful responses
                if response.status_code == 200:
                    try:
                        data = response.json()
                        logger.debug(f"Request successful: {method} {url}")
                        return data
                    except Exception as e:
                        raise MaxBotError(f"Invalid JSON response: {e}")

                # Handle error responses
                try:
                    error_data = response.json()
                except Exception:
                    error_data = {"message": response.text or "Unknown error"}

                # Parse and raise appropriate exception
                logger.warning(f"API error: {response.status_code} {error_data}")
                raise parseApiError(response.status_code, error_data)

            except AuthenticationError as e:
                logger.error(f"Authentication error: {e}")
                raise e

            except ValidationError as e:
                logger.error(f"Validation error: {e}")
                logger.exception(e)
                raise e

            except MaxBotError as e:
                last_exception = e
                logger.warning(f"API error on attempt {attempt + 1}: {type(e).__name__}#{e}, {e.response}")

            except httpx.HTTPStatusError as e:
                last_exception = parseApiError(e.response.status_code, e.response.json() if e.response.content else {})
                logger.warning(f"HTTP error on attempt {attempt + 1}: {last_exception}, {type(e).__name__}#{e}")

            except httpx.ReadTimeout as e:
                if isUpdatePolling:
                    # It is natural to get such error during polling
                    #  if there is no updates. Just skip
                    if EXTENDED_DEBUG:
                        logger.debug("No updates for now...")
                    continue
                last_exception = NetworkError(f"Read timeout: {type(e).__name__}#{e}")
                logger.warning(f"Read timeout on attempt {attempt + 1}: {type(e).__name__}#{e}")

            except httpx.RequestError as e:
                last_exception = NetworkError(f"Network error: {type(e).__name__}#{e}")
                logger.warning(f"Network error on attempt {attempt + 1}: {type(e).__name__}#{e}")

            except Exception as e:
                last_exception = MaxBotError(f"Unexpected error: {type(e).__name__}#{e}")
                logger.warning(f"Unexpected error on attempt {attempt + 1}: {type(e).__name__}#{e}")
                logger.exception(e)

            # Retry logic with exponential backoff
            if attempt < self.maxRetries:
                delay = self.retryBackoffFactor * (2**attempt)
                logger.debug(f"Retrying in {delay} seconds...")
                await asyncio.sleep(delay)
            attempt += 1

        # All retries exhausted
        logger.error(f"Request failed after {self.maxRetries + 1} attempts")
        raise last_exception or MaxBotError("Request failed after all retries")

    async def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make GET request to API endpoint.

        Args:
            endpoint: API endpoint path
            params: Query parameters

        Returns:
            Parsed JSON response data
        """
        return await self._makeRequest(HTTP_GET, endpoint, params=params)

    async def post(
        self,
        endpoint: str,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make POST request to API endpoint.

        Args:
            endpoint: API endpoint path
            json: JSON request body
            data: Form data
            files: Files to upload

        Returns:
            Parsed JSON response data
        """
        kwargs: Dict[str, Any] = {}
        if json is not None:
            kwargs["json"] = json
        if data is not None:
            kwargs["data"] = data
        if files is not None:
            kwargs["files"] = files
            # Remove content-type header for multipart uploads
            client = self._getHttpClient()
            client.headers.pop("Content-Type", None)

        return await self._makeRequest(HTTP_POST, endpoint, **kwargs)

    async def put(self, endpoint: str, json: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make PUT request to API endpoint.

        Args:
            endpoint: API endpoint path
            json: JSON request body

        Returns:
            Parsed JSON response data
        """
        return await self._makeRequest(HTTP_PUT, endpoint, json=json)

    async def patch(self, endpoint: str, json: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make PATCH request to API endpoint.

        Args:
            endpoint: API endpoint path
            json: JSON request body

        Returns:
            Parsed JSON response data
        """
        return await self._makeRequest(HTTP_PATCH, endpoint, json=json)

    async def delete(self, endpoint: str) -> Dict[str, Any]:
        """Make DELETE request to API endpoint.

        Args:
            endpoint: API endpoint path

        Returns:
            Parsed JSON response data
        """
        return await self._makeRequest(HTTP_DELETE, endpoint)

    # Basic API methods (Phase 1)
    async def getMyInfo(self, useCache: bool = True) -> BotInfo:
        """Get information about the current bot.
        TODO: Rewrite

        Returns information about the current bot identified by the access token.
        The method returns the bot ID, name, and avatar (if available).

        Returns:
            Bot information including ID, name, and avatar

        Raises:
            AuthenticationError: If access token is invalid
            NetworkError: If network request fails

        Example:
            >>> async with MaxBotClient("token") as client:
            ...     bot_info = await client.getMyInfo()
            ...     print(f"Bot ID: {bot_info.user_id}")
            ...     print(f"Bot name: {bot_info.first_name}")
        """

        if useCache and self._myInfo is not None:
            return self._myInfo

        response = await self.get("/me")
        self._myInfo = BotInfo.from_dict(response)

        return self._myInfo

    async def healthCheck(self) -> bool:
        """Perform a simple health check against the API.

        Makes a lightweight request to verify that the API is accessible
        and the authentication token is valid.

        Returns:
            True if API is accessible and authentication works

        Raises:
            AuthenticationError: If access token is invalid
            NetworkError: If network request fails

        Example:
            >>> async with MaxBotClient("token") as client:
            ...     if await client.healthCheck():
            ...         print("API is healthy!")
        """
        try:
            await self.getMyInfo()
            return True
        except AuthenticationError:
            raise
        except Exception as e:
            logger.debug(f"Health check failed: {e}")
            return False

    # Phase 3: Basic Operations

    # Chat Management Methods
    async def getChats(self, count: int = 50, marker: Optional[int] = None) -> ChatList:
        """Get list of chats where the bot participated.

        Returns information about chats where the bot participated. The result includes
        a list of chats and a marker for navigating to the next page.

        Args:
            count: Number of chats to request (1-100, default: 50)
            marker: Pointer to the next page of data. Pass null for the first page

        Returns:
            Paginated list of chats

        Raises:
            AuthenticationError: If access token is invalid
            NetworkError: If network request fails

        Example:
            >>> async with MaxBotClient("token") as client:
            ...     chats = await client.getChats(count=20)
            ...     for chat in chats.chats:
            ...         print(f"Chat: {chat.title}")
        """
        params = {"count": count}
        if marker is not None:
            params["marker"] = marker

        response = await self.get("/chats", params=params)
        return ChatList.from_dict(response)

    async def getChat(self, chatId: int) -> Chat:
        """Get information about a chat by its ID.

        Returns detailed information about a specific chat.

        Args:
            chatId: ID of the chat to get information about

        Returns:
            Chat information

        Raises:
            AuthenticationError: If access token is invalid
            NetworkError: If network request fails

        Example:
            >>> async with MaxBotClient("token") as client:
            ...     chat = await client.getChat(12345)
            ...     print(f"Chat title: {chat.title}")
        """
        response = await self.get(f"/chats/{chatId}")
        return Chat.from_dict(response)

    async def editChatInfo(
        self,
        chatId: int,
        title: Optional[str] = None,
        icon: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
    ) -> Chat:
        """Edit chat information.

        Allows editing chat information including title, icon, and pinned message.

        Args:
            chatId: ID of the chat to edit
            title: New chat title (optional)
            icon: New chat icon (optional)
            description: New chat description (optional)

        Returns:
            Updated chat object

        Raises:
            AuthenticationError: If access token is invalid
            NetworkError: If network request fails

        Example:
            >>> async with MaxBotClient("token") as client:
            ...     chat = await client.editChatInfo(12345, title="New Title")
        """
        patch_data = {}
        if title is not None:
            patch_data["title"] = title
        if icon is not None:
            patch_data["icon"] = icon
        if description is not None:
            patch_data["description"] = description

        response = await self.patch(f"/chats/{chatId}", json=patch_data)
        return Chat.from_dict(response)

    async def sendAction(self, chatId: int, action: SenderAction) -> bool:
        """Send chat action.

        Allows sending bot actions to chat, such as "typing" or "sending photo".

        Args:
            chatId: ID of the chat
            action: Action to send (typing_on, upload_photo, etc.)

        Returns:
            True if action was sent successfully

        Raises:
            AuthenticationError: If access token is invalid
            NetworkError: If network request fails

        Example:
            >>> async with MaxBotClient("token") as client:
            ...     await client.sendAction(12345, SenderAction.TYPING)
        """
        ret = await self.post(f"/chats/{chatId}/actions", json={"action": action.value})
        logger.debug(f"sendAction ret: {ret}")
        return True

    async def pinMessage(self, chatId: int, messageId: str) -> bool:
        """Pin a message in chat.

        Pins a message in the chat.

        Args:
            chatId: ID of the chat where message should be pinned
            messageId: ID of the message to pin

        Returns:
            True if message was pinned successfully

        Raises:
            AuthenticationError: If access token is invalid
            NetworkError: If network request fails

        Example:
            >>> async with MaxBotClient("token") as client:
            ...     await client.pinMessage(12345, "msg_67890")
        """
        await self.put(f"/chats/{chatId}/pin", json={"pin": messageId})
        return True

    async def unpinMessage(self, chatId: int) -> bool:
        """Unpin message in chat.

        Removes the pinned message from the chat.

        Args:
            chatId: ID of the chat

        Returns:
            True if message was unpinned successfully

        Raises:
            AuthenticationError: If access token is invalid
            NetworkError: If network request fails

        Example:
            >>> async with MaxBotClient("token") as client:
            ...     await client.unpinMessage(12345)
        """
        await self.delete(f"/chats/{chatId}/pin")
        return True

    # Member Management Methods
    async def getMembers(
        self, chatId: int, userIds: Optional[List[int]] = None, marker: Optional[int] = None, count: int = 20
    ) -> ChatMembersList:
        """Get chat members.

        Returns users participating in the chat.

        Args:
            chatId: ID of the chat
            userIds: List of user IDs whose membership should be retrieved.
                    When this parameter is passed, count and marker parameters are ignored
            marker: Pointer to the next page of data
            count: Number of members to return (1-100, default: 20)

        Returns:
            List of chat members and pointer to next page

        Raises:
            AuthenticationError: If access token is invalid
            NetworkError: If network request fails

        Example:
            >>> async with MaxBotClient("token") as client:
            ...     members = await client.getMembers(12345, count=10)
            ...     for member in members.members:
            ...         print(f"Member: {member.first_name}")
        """
        params: Dict[str, Any] = {"count": count}
        if userIds is not None:
            params["user_ids"] = userIds
        if marker is not None:
            params["marker"] = marker

        response = await self.get(f"/chats/{chatId}/members", params=params)
        return ChatMembersList.from_dict(response)

    async def addMembers(self, chatId: int, userIds: List[int]) -> bool:
        """Add members to chat.

        Adds participants to the chat. May require additional permissions.

        Args:
            chatId: ID of the chat
            userIds: List of user IDs to add to the chat

        Returns:
            True if members were added successfully

        Raises:
            AuthenticationError: If access token is invalid
            NetworkError: If network request fails

        Example:
            >>> async with MaxBotClient("token") as client:
            ...     await client.addMembers(12345, [67890, 98765])
        """
        await self.post(f"/chats/{chatId}/members", json={"user_ids": userIds})
        return True

    async def removeMember(self, chatId: int, userId: int, block: bool = False) -> bool:
        """Remove member from chat.

        Removes a participant from the chat. May require additional permissions.

        Args:
            chatId: ID of the chat
            userId: ID of the user to remove from the chat
            block: If true, the user will be blocked in the chat.
                   Only applies to chats with public or private links

        Returns:
            True if member was removed successfully

        Raises:
            AuthenticationError: If access token is invalid
            NetworkError: If network request fails

        Example:
            >>> async with MaxBotClient("token") as client:
            ...     await client.removeMember(12345, 67890)
        """
        params = {"user_id": userId}
        if block:
            params["block"] = block

        await self.delete(f"/chats/{chatId}/members?user_id={userId}&block={block}")
        return True

    async def getAdmins(self, chatId: int) -> ChatMembersList:
        """Get chat administrators.

        Returns all chat administrators. The bot must be an administrator
        in the requested chat.

        Args:
            chatId: ID of the chat

        Returns:
            List of chat administrators

        Raises:
            AuthenticationError: If access token is invalid
            NetworkError: If network request fails

        Example:
            >>> async with MaxBotClient("token") as client:
            ...     admins = await client.getAdmins(12345)
            ...     for admin in admins.members:
            ...         print(f"Admin: {admin.first_name}")
        """
        response = await self.get(f"/chats/{chatId}/members/admins")
        return ChatMembersList.from_dict(response)

    # Admin Permission Methods
    async def editAdminPermissions(self, chatId: int, admins: List[ChatAdmin]) -> bool:
        """Set chat administrators.

        Sets administrators for the chat with their permissions.

        Args:
            chatId: ID of the chat
            admins: List of administrators with their permissions

        Returns:
            True if administrators were set successfully

        Raises:
            AuthenticationError: If access token is invalid
            NetworkError: If network request fails

        Example:
            >>> from lib.max_bot.models import ChatAdmin, ChatAdminPermission
            >>> admin = ChatAdmin(
            ...     user_id=67890,
            ...     permissions=[ChatAdminPermission.WRITE, ChatAdminPermission.PIN_MESSAGE]
            ... )
            >>> async with MaxBotClient("token") as client:
            ...     await client.editAdminPermissions(12345, [admin])
        """
        admins_data = []
        for admin in admins:
            admin_dict = {"user_id": admin.user_id, "permissions": [perm.value for perm in admin.permissions]}
            if admin.alias:
                admin_dict["alias"] = admin.alias
            admins_data.append(admin_dict)

        await self.post(f"/chats/{chatId}/members/admins", json={"admins": admins_data})
        return True

    # Phase 4: Messaging System

    # Message Operations
    async def sendMessage(
        self,
        *,
        chatId: Optional[int] = None,
        userId: Optional[int] = None,
        text: Optional[str] = None,
        attachments: Optional[List[Attachment]] = None,
        replyTo: Optional[str] = None,
        forwardFrom: Optional[str] = None,
        notify: bool = True,
        format: Optional[TextFormat] = None,
        inlineKeyboard: Optional[InlineKeyboardAttachment] = None,
        replyKeyboard: Optional[ReplyKeyboardAttachment] = None,
        disableLinkPreview: Optional[bool] = None,
    ) -> SendMessageResult:
        """Send a message to a chat or user.

        Sends a message to a chat or user with various options including text,
        attachments, keyboards, and formatting.

        Args:
            chatId: ID of the chat to send message to
            userId: ID of the user to send message to
            text: Message text (optional)
            attachments: List of message attachments (optional)
            replyTo: Message ID to reply to (optional)
            forwardFrom: Message ID to forward from (optional)
            notify: Whether to notify users (default: True)
            format: Text formatting (markdown/html) (optional)
            inlineKeyboard: Inline keyboard attachment (optional)
            keyboard: Reply keyboard attachment (optional)
            disableLinkPreview: Whether to disable link preview (default: False)

        Returns:
            Sent message information

        Raises:
            AuthenticationError: If access token is invalid
            NetworkError: If network request fails

        Example:
            >>> async with MaxBotClient("token") as client:
            ...     result = await client.sendMessage(
            ...         chatId=12345,
            ...         text="Hello, World!",
            ...         format=TextFormat.MARKDOWN
            ...     )
            ...     print(f"Message sent: {result.message.body.mid}")
        """
        if not chatId and not userId:
            raise MaxBotError("Either chatId or userId must be provided")

        # Build message body
        message_body = NewMessageBody(
            text=text,
            attachments=attachments,
            notify=notify,
            format=format,
        )

        # Add link if reply or forward
        if replyTo or forwardFrom:

            link_type = MessageLinkType.REPLY if replyTo else MessageLinkType.FORWARD
            link_mid = replyTo if replyTo else forwardFrom
            # Ensure link_mid is not None
            if link_mid is None:
                raise MaxBotError("Message ID for reply/forward cannot be None")
            message_body.link = NewMessageLink(type=link_type, mid=link_mid)

        # Convert to dict for API
        body_data = {
            "text": message_body.text,
            "notify": message_body.notify,
        }

        if message_body.format:
            body_data["format"] = message_body.format.value

        if message_body.link:
            body_data["link"] = {
                "type": message_body.link.type.value,
                "mid": message_body.link.mid,
            }

        # Add keyboards to attachments
        final_attachments = attachments.copy() if attachments else []

        if inlineKeyboard:
            final_attachments.append(inlineKeyboard)

        if replyKeyboard:
            final_attachments.append(replyKeyboard)

        if final_attachments or attachments is not None:
            body_data["attachments"] = [v.to_dict(recursive=True) for v in final_attachments]

        # Build query parameters
        query_params = []
        if chatId:
            query_params.append(f"chat_id={chatId}")
        if userId:
            query_params.append(f"user_id={userId}")
        if disableLinkPreview is not None:
            query_params.append(f"disable_link_preview={disableLinkPreview}")

        endpoint = "/messages"
        if query_params:
            endpoint += "?" + "&".join(query_params)

        response = await self.post(endpoint, json=body_data)
        return SendMessageResult.from_dict(response)

    async def editMessage(
        self,
        messageId: str,
        text: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        inlineKeyboard: Optional[Dict[str, Any]] = None,
        format: Optional[TextFormat] = None,
    ) -> bool:
        """Edit a message in a chat.

        Edits a message in a chat. If the attachments field is null,
        the attachments of the current message are not changed. If an empty
        list is passed in this field, all attachments will be deleted.

        Args:
            messageId: ID of the message to edit
            text: New message text (optional)
            attachments: New message attachments (optional)
            inlineKeyboard: New inline keyboard (optional)
            format: Text formatting (markdown/html) (optional)

        Returns:
            True if message was edited successfully

        Raises:
            AuthenticationError: If access token is invalid
            NetworkError: If network request fails

        Example:
            >>> async with MaxBotClient("token") as client:
            ...     await client.editMessage(
            ...         messageId="msg_67890",
            ...         text="Updated text"
            ...     )
        """
        # Build message body
        body_data = {}

        if text is not None:
            body_data["text"] = text

        if attachments is not None:
            body_data["attachments"] = attachments

        if format is not None:
            body_data["format"] = format.value

        # Add inline keyboard to attachments if provided
        if inlineKeyboard is not None:
            final_attachments = attachments.copy() if attachments else []
            final_attachments.append(inlineKeyboard)
            body_data["attachments"] = final_attachments

        await self.put(f"/messages?message_id={messageId}", json=body_data)
        return True

    async def deleteMessages(self, messageIds: List[str]) -> bool:
        """Delete messages from a chat.

        Deletes messages in a dialog or chat if the bot has permission
        to delete messages.

        Args:
            messageIds: List of message IDs to delete

        Returns:
            True if messages were deleted successfully

        Raises:
            AuthenticationError: If access token is invalid
            NetworkError: If network request fails

        Example:
            >>> async with MaxBotClient("token") as client:
            ...     await client.deleteMessages(["msg_67890", "msg_12345"])
        """
        # Note: API only supports deleting one message at a time
        # So we need to make multiple requests
        for messageId in messageIds:
            await self.delete(f"/messages?message_id={messageId}")

        return True

    async def getMessages(
        self,
        chatId: Optional[int] = None,
        messageIds: Optional[List[str]] = None,
        fromTime: Optional[int] = None,
        toTime: Optional[int] = None,
        count: int = 50,
    ) -> MessageList:
        """Get messages from a chat.

        Returns messages in a chat: a page with results and a marker
        pointing to the next page. Messages are returned in reverse order,
        i.e., the last messages in the chat will be first in the array.

        Args:
            chatId: ID of the chat to get messages from
            messageIds: List of message IDs to get (comma-separated)
            fromTime: Start time for requested messages (Unix timestamp)
            toTime: End time for requested messages (Unix timestamp)
            count: Maximum number of messages in response (1-100, default: 50)

        Returns:
            List of messages

        Raises:
            AuthenticationError: If access token is invalid
            NetworkError: If network request fails

        Example:
            >>> async with MaxBotClient("token") as client:
            ...     messages = await client.getMessages(chatId=12345, count=20)
            ...     for message in messages.messages:
            ...         print(f"Message: {message.body.text}")
        """
        params: Dict[str, Any] = {"count": count}

        if chatId is not None:
            params["chat_id"] = chatId

        if messageIds is not None:
            params["message_ids"] = ",".join(messageIds)

        if fromTime is not None:
            params["from"] = fromTime

        if toTime is not None:
            params["to"] = toTime

        response = await self.get("/messages", params=params)
        return MessageList.from_dict(response)

    async def getMessageById(self, messageId: str) -> Message:
        """Get a single message by its ID.

        Returns a single message by its ID.

        Args:
            messageId: ID of the message to get

        Returns:
            Message information

        Raises:
            AuthenticationError: If access token is invalid
            NetworkError: If network request fails

        Example:
            >>> async with MaxBotClient("token") as client:
            ...     message = await client.getMessageById("msg_67890")
            ...     print(f"Message text: {message.body.text}")
        """
        response = await self.get(f"/messages/{messageId}")
        return Message.from_dict(response)

    async def answerCallbackQuery(
        self,
        queryId: str,
        text: Optional[str] = None,
        showAlert: bool = False,
        url: Optional[str] = None,
    ) -> bool:
        """Answer a callback query.

        This method is used to send a response after a user clicks a button.
        The response can be an updated message and/or a one-time notification
        for the user.

        Args:
            queryId: Callback button identifier that the user clicked on
            text: Text to show in the notification (optional)
            showAlert: Whether to show an alert (default: False)
            url: URL to open (optional)

        Returns:
            True if callback was answered successfully

        Raises:
            AuthenticationError: If access token is invalid
            NetworkError: If network request fails

        Example:
            >>> async with MaxBotClient("token") as client:
            ...     await client.answerCallbackQuery(
            ...         queryId="callback_123",
            ...         text="Button clicked!"
            ...     )
        """
        # Build callback answer
        answer_data: Dict[str, Any] = {}

        if text is not None:
            answer_data["message"] = {"text": text}

        if showAlert:
            answer_data["notification"] = {"show_alert": showAlert}

        if url is not None:
            if "notification" not in answer_data:
                notification: Dict[str, Any] = {"show_alert": False}
                answer_data["notification"] = notification
            answer_data["notification"]["url"] = url  # type: ignore

        await self.post(f"/answers?callback_id={queryId}", json=answer_data)
        return True

    # Phase 5: Advanced Features - Updates and Webhooks

    # Updates Polling Methods
    async def getUpdates(
        self,
        lastEventId: Optional[int] = None,
        limit: int = 100,
        timeout: int = 30,
        types: Optional[List[str]] = None,
    ) -> UpdateList:
        """Get updates via long polling.

        URL: GET /updates
        tags: ["subscriptions"]
        summary: Получение обновлений
        description:
            Этот метод можно использовать для получения обновлений,
            если ваш бот не подписан на WebHook.
            Метод использует долгий опрос (long polling).

            Каждое обновление имеет свой номер последовательности.
            Свойство `marker` в ответе указывает на следующее ожидаемое обновление.

            Все предыдущие обновления считаются завершенными после прохождения параметра `marker`.
            Если параметр `marker` **не передан**, бот получит все обновления,
            произошедшие после последнего подтверждения.

        parameters:
          - limit: int[1-1000], Default: 100
            description: "Максимальное количество обновлений для получения"
          - timeout: int[0-90], Default: 30
            description: "Тайм-аут в секундах для долгого опроса",
          - marker: Optional[int64]
            description:
                Если передан, бот получит обновления, которые еще не были получены.
                Если не передан, получит все новые обновления
          - types: Optional[List[str]]
            description:
                Список типов обновлений, которые бот хочет получить
                (например, `message_created`, `message_callback`,...)",

        responses:
          - 200:
            description: "Список обновлений"
            "content": UpdateList
          - 401: Unauthorized
          - 405: NotAllowed
          - 500: InternalError

        Args:
            lastEventId: If passed, bot will receive updates that haven't been received yet.
                        If not passed, will receive all new updates
            limit: Maximum number of updates to receive (1-1000, default: 100)
            timeout: Timeout in seconds for long polling (0-90, default: 30)
            types: List of update types the bot wants to receive
                  (e.g., ["message_created", "message_callback"])

        Returns:
            List of updates with marker for next request

        Raises:
            AuthenticationError: If access token is invalid
            NetworkError: If network request fails

        Example:
            >>> async with MaxBotClient("token") as client:
            ...     updates = await client.getUpdates(limit=50, timeout=20)
            ...     for update in updates.updates:
            ...         print(f"Update type: {update.type}")
        """
        params: Dict[str, Any] = {
            "limit": max(1, min(1000, limit)),
            "timeout": max(0, min(90, timeout)),
        }

        if lastEventId is not None:
            params["marker"] = lastEventId

        if types is not None:
            params["types"] = ",".join(types)

        response = await self.get("/updates", params=params)
        if EXTENDED_DEBUG:
            logger.debug(f"Received updates: {utils.jsonDumps(response, indent=2)}")
        return UpdateList.from_dict(response)

    async def startPolling(
        self,
        handler: Callable[[Update], Union[None, Awaitable[None]]],
        types: Optional[List[str]] = None,
        timeout: int = 30,
        errorHandler: Optional[Callable[[Exception], Union[None, Awaitable[None]]]] = None,
    ) -> None:
        """Start continuous polling loop.

        Starts a background task that continuously polls for updates and calls the handler
        for each update received.

        Args:
            handler: Function to call for each update received
            types: List of update types to receive (optional)
            timeout: Timeout for each polling request (default: 30)
            errorHandler: Function to call when an error occurs (optional)

        Raises:
            MaxBotError: If polling is already started

        Example:
            >>> async def handle_update(update):
            ...     print(f"Received: {update.type}")
            >>>
            >>> async with MaxBotClient("token") as client:
            ...     await client.startPolling(handle_update)
            ...     # Polling will run in background
        """
        if self._isPolling:
            raise MaxBotError("Polling is already started")

        self._isPolling = True
        self._pollingTask = asyncio.create_task(self._pollingLoop(handler, types, timeout, errorHandler))
        logger.info("Started polling for updates")

    async def stopPolling(self) -> None:
        """Stop the polling loop.

        Stops the background polling task gracefully.

        Example:
            >>> async with MaxBotClient("token") as client:
            ...     await client.startPolling(handle_update)
            ...     # ... do some work ...
            ...     await client.stopPolling()
        """
        if not self._isPolling:
            return

        self._isPolling = False

        if self._pollingTask and not self._pollingTask.done():
            self._pollingTask.cancel()
            try:
                await self._pollingTask
            except asyncio.CancelledError:
                pass

        logger.info("Stopped polling for updates")

    async def _pollingLoop(
        self,
        handler: Callable[[Update], Union[None, Awaitable[None]]],
        types: Optional[List[str]],
        timeout: int,
        errorHandler: Optional[Callable[[Exception], Union[None, Awaitable[None]]]],
    ) -> None:
        """Internal polling loop that runs in background."""
        last_marker = None

        while self._isPolling:
            try:
                updates = await self.getUpdates(last_marker, 100, timeout, types)

                if updates.updates:
                    for update in updates.updates:
                        if not self._isPolling:
                            break

                        try:
                            if asyncio.iscoroutinefunction(handler):
                                await handler(update)
                            else:
                                handler(update)
                        except Exception as e:
                            logger.error(f"Error in update handler: {e}")
                            if errorHandler:
                                try:
                                    if asyncio.iscoroutinefunction(errorHandler):
                                        result = errorHandler(e)
                                        if result is not None:
                                            await result
                                    else:
                                        errorHandler(e)
                                except Exception as handler_error:
                                    logger.error(f"Error in error handler: {handler_error}")

                # Update marker for next request
                if hasattr(updates, "marker") and updates.marker:
                    last_marker = updates.marker

            except asyncio.CancelledError:
                logger.debug("Polling loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in polling loop: {e}")
                if errorHandler:
                    try:
                        if asyncio.iscoroutinefunction(errorHandler):
                            result = errorHandler(e)
                            if result is not None:
                                await result
                        else:
                            errorHandler(e)
                    except Exception as handler_error:
                        logger.error(f"Error in error handler: {handler_error}")

                # Wait a bit before retrying
                if self._isPolling:
                    await asyncio.sleep(5)

    # Webhook Management Methods
    async def setWebhook(
        self,
        url: str,
        types: Optional[List[str]] = None,
        secret: Optional[str] = None,
    ) -> bool:
        """Set webhook URL for receiving updates.

        Subscribes the bot to receive updates via WebHook. After calling this method,
        the bot will receive notifications about new events in chats to the specified URL.

        Args:
            url: URL to receive webhook updates
            types: List of update types to receive (optional)
            secret: Secret for webhook verification (optional)

        Returns:
            True if webhook was set successfully

        Raises:
            AuthenticationError: If access token is invalid
            NetworkError: If network request fails

        Example:
            >>> async with MaxBotClient("token") as client:
            ...     await client.setWebhook("https://example.com/webhook")
        """
        webhook_data = {"url": url}

        if types is not None:
            webhook_data["update_types"] = ",".join(types)

        if secret is not None:
            webhook_data["secret"] = secret

        await self.post("/subscriptions", json=webhook_data)
        return True

    async def deleteWebhook(self, url: str) -> bool:
        """Delete webhook subscription.

        Unsubscribes the bot from receiving updates via WebHook. After calling this method,
        the bot stops receiving notifications about new events, and update delivery via
        API with long polling becomes available.

        Args:
            url: URL to delete from webhook subscriptions

        Returns:
            True if webhook was deleted successfully

        Raises:
            AuthenticationError: If access token is invalid
            NetworkError: If network request fails

        Example:
            >>> async with MaxBotClient("token") as client:
            ...     await client.deleteWebhook("https://example.com/webhook")
        """
        await self.delete(f"/subscriptions?url={url}")
        return True

    async def getWebhookInfo(self) -> Dict[str, Any]:
        """Get webhook information.

        If your bot receives data via WebHook, this method returns a list of all subscriptions.

        Returns:
            List of webhook subscriptions

        Raises:
            AuthenticationError: If access token is invalid
            NetworkError: If network request fails

        Example:
            >>> async with MaxBotClient("token") as client:
            ...     info = await client.getWebhookInfo()
            ...     print(f"Webhooks: {info}")
        """
        response = await self.get("/subscriptions")
        return response

    async def sendPhoto(
        self,
        photoToken: str,
        chatId: Optional[int] = None,
        userId: Optional[int] = None,
        text: Optional[str] = None,
        replyTo: Optional[str] = None,
        forwardFrom: Optional[str] = None,
        notify: bool = True,
        inlineKeyboard: Optional[InlineKeyboardAttachment] = None,
        replyKeyboard: Optional[ReplyKeyboardAttachment] = None,
        format: Optional[TextFormat] = None,
        disableLinkPreview: bool = False,
    ) -> SendMessageResult:
        """Send a photo message to a chat or user.

        Sends a photo message to a chat or user with optional text and keyboards.

        Args:
            chatId: ID of the chat to send message to
            userId: ID of the user to send message to
            photoToken: Token for the photo attachment
            text: Message text (optional)
            replyTo: Message ID to reply to (optional)
            forwardFrom: Message ID to forward from (optional)
            notify: Whether to notify users (default: True)
            inlineKeyboard: Inline keyboard attachment (optional)
            keyboard: Reply keyboard attachment (optional)
            format: Text formatting (markdown/html) (optional)
            disableLinkPreview: Whether to disable link preview (default: False)

        Returns:
            Sent message information

        Raises:
            AuthenticationError: If access token is invalid
            NetworkError: If network request fails

        Example:
            >>> async with MaxBotClient("token") as client:
            ...     result = await client.sendPhoto(
            ...         chatId=12345,
            ...         photoToken="photo_token_123",
            ...         text="Check out this photo!"
            ...     )
        """
        photo_attachment = PhotoAttachment(
            payload=PhotoAttachmentPayload(
                photo_id=0,
                token=photoToken,
                url="",
            )
        )

        return await self.sendMessage(
            attachments=[photo_attachment],
            chatId=chatId,
            userId=userId,
            text=text,
            replyTo=replyTo,
            forwardFrom=forwardFrom,
            notify=notify,
            inlineKeyboard=inlineKeyboard,
            replyKeyboard=replyKeyboard,
            format=format,
            disableLinkPreview=disableLinkPreview,
        )

    # Phase 6: File Operations

    # Upload Methods
    async def getUploadUrl(self, uploadType: UploadType) -> UploadEndpoint:
        """
        Возвращает URL для последующей загрузки файла.

        Поддерживаются два типа загрузки:
        - **Multipart upload** — более простой, но менее надежный способ.
          В этом случае используется заголовок `Content-Type: multipart/form-data`.
          Этот способ имеет ограничения:
            - Максимальный размер файла: 4 ГБ
            - Можно загружать только один файл за раз
            - Невозможно перезапустить загрузку, если она была остановлена

        - **Resumable upload** — более надежный способ, если заголовок
          `Content-Type` не равен `multipart/form-data`.
          Этот способ позволяет загружать файл частями и возобновить загрузку
          с последней успешно загруженной части в случае ошибок.

        Пример использования cURL для загрузки файла:

        ```shell
        curl -i -X POST \
            -H "Content-Type: multipart/form-data" \
           -F "data=@movie.pdf" "%UPLOAD_URL%"
        ```

        Где %UPLOAD_URL% — это URL из результата метода в примере cURL запроса

        **Для загрузки видео и аудио:**
        1. Когда получаем ссылку на загрузку видео или аудио
          (`POST /uploads` с `type` = `video` или `type` = `audio`),
          вместе с `url` в ответе приходит `token`, который нужно
          использовать в сообщении (когда формируете `body` с `attachments`)
          в `POST /messages`
        2. После загрузки видео или аудио (по `url` из шага выше) сервер возвращает `retval`
        3. C этого момента можно использовать `token`, чтобы прикреплять вложение в сообщение бота

        Механика отличается от `type` = `image` | `file`, где `token` возвращается
          в ответе на загрузку изображения или файла

        ## Прикрепление медиа
        Медиафайлы прикрепляются к сообщениям поэтапно:

        1. Получите URL для загрузки медиафайлов
        2. Загрузите бинарные данные соответствующего формата по полученному URL
        3. После успешной загрузки получите JSON-объект в ответе. Используйте этот объект для создания вложения.
          Структура вложения:
            - `type`: тип медиа (например, `"video"`)
            - `payload`: JSON-объект, который вы получили

        Пример для видео:
        1. Получите URL для загрузки
        ```bash
        curl -X POST 'https://platform-api.max.ru/uploads?type=video' \
            -H 'Authorization: Bearer %access_token%'
        ```

        Ответ:
        ```json
        {
            "url": "https://vu.mycdn.me/upload.do…"
        }
        ```

        2. Загрузите видео по URL
        ```bash
        curl -i -X POST -H "Content-Type: multipart/form-data" \
            -F \"data=@movie.mp4\" \"https://vu.mycdn.me/upload.do…"
        ```

        Ответ:
        ```json
        {
            "token": "_3R..."
        }
        ```

        3. Отправьте сообщение с вложением
        ```json
        {
            "text": "Message with video",
            "attachments": [
            {
                "type": "video",
                "payload": {
                    "token": "_3Rarhcf1PtlMXy8jpgie8Ai_KARnVFYNQTtmIRWNh4"
                }
            }
            ]
        }
        ```
        """

        response = await self.post(f"/uploads?type={uploadType.value}")
        return UploadEndpoint.from_dict(response)

    async def uploadFile(
        self,
        filename: str,
        data: bytes,
        mimeType: str,
        uploadType: UploadType,
    ) -> UploadedAttachment:
        """TODO"""

        # Validate file for upload

        # Get upload URL
        uploadInfo = await self.getUploadUrl(uploadType)
        logger.debug(f"Upload info: {uploadInfo}")
        uploadUrl = uploadInfo.url

        # Upload file
        files = {"data": (filename, data, mimeType)}

        try:
            # Make direct HTTP request to upload URL (not through our API)
            client = self._getHttpClient()

            # Remove content-type header for multipart uploads
            client.headers.pop("Content-Type", None)
            client.headers.pop("Accept", None)
            client.headers.pop("Authorization", None)

            async with client.stream("POST", uploadUrl, files=files) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    raise MaxBotError(f"Upload failed with status {response.status_code}: {error_text.decode()}")

                await response.aread()
                # logger.debug(ret)
                # logger.debug(response.headers)
                # logger.debug(response.encoding)
                # logger.debug(response.charset_encoding)
                # logger.debug(response.content)
                # logger.debug(response.request)
                # logger.debug(response.request.headers)

                result = response.json()
                # {"error_msg":"...","error_code":"4","error_data":"BAD_REQUEST"}'
                if "error_msg" in result:
                    logger.error(result)
                    raise MaxBotError(message=result.get["error_msg"], code=result.get("error_code"), response=result)

                match uploadType:
                    case UploadType.IMAGE:
                        return UploadedPhoto(uploadEndpoint=uploadInfo, payload=PhotoUploadResult.from_dict(result))
                    case _:
                        logger.error(f"Unsupported UploadType {uploadType}, result: {result}")
                        return UploadedAttachment(uploadEndpoint=uploadInfo, api_kwargs=result)

        except httpx.HTTPStatusError as e:
            raise MaxBotError(f"Upload failed: {e}")
        except Exception as e:
            raise MaxBotError(f"Upload error: {e}")

    async def downloadAttachmentPayload(self, attachmentPayload: AttachmentPayload | str) -> Optional[bytes]:
        # TODO: Properly process Video
        url = attachmentPayload if isinstance(attachmentPayload, str) else attachmentPayload.url

        try:
            client = self._getHttpClient()

            # Remove content-type header for multipart uploads
            client.headers.pop("Content-Type", None)
            client.headers.pop("Accept", None)
            client.headers.pop("Authorization", None)

            logger.debug(f"Downloading attachment payload from {url}")
            ret = await client.get(url)

            # logger.debug(ret)
            # logger.debug(ret.headers)
            # logger.debug(ret.encoding)
            # logger.debug(ret.charset_encoding)

            return ret.content
        except Exception as e:
            logger.error(f"Failed to download attachment: {type(e).__name__}#{e}")
            logger.exception(e)
            return None

    # Keyboard Helper Methods
    def createInlineKeyboard(self, buttons: List[List[Button]]) -> InlineKeyboardAttachment:
        """Create an inline keyboard attachment.

        Creates an inline keyboard attachment from a 2D array of button dictionaries.

        Args:
            buttons: 2D array of button dictionaries representing keyboard layout

        Returns:
            Inline keyboard attachment dictionary

        Example:
            >>> client = MaxBotClient("token")
            >>> keyboard = client.createInlineKeyboard([
            ...     [
            ...         {"type": "callback", "text": "Button 1", "payload": "btn1"},
            ...         {"type": "callback", "text": "Button 2", "payload": "btn2"}
            ...     ],
            ...     [
            ...         {"type": "link", "text": "Open Google", "url": "https://google.com"}
            ...     ]
            ... ])
        """
        return InlineKeyboardAttachment(payload=Keyboard(buttons=buttons))

    def createReplyKeyboard(
        self,
        buttons: List[List[Button]],
        oneTime: bool = False,
        resize: bool = False,
    ) -> ReplyKeyboardAttachment:
        """Create a reply keyboard attachment.

        Creates a reply keyboard attachment from a 2D array of button dictionaries.

        Args:
            buttons: 2D array of button dictionaries representing keyboard layout
            oneTime: Whether to hide keyboard after first use (default: False)
            resize: Whether to resize keyboard to fit buttons (default: False)

        Returns:
            Reply keyboard attachment dictionary

        Example:
            >>> client = MaxBotClient("token")
            >>> keyboard = client.createReplyKeyboard([
            ...     [
            ...         {"type": "reply", "text": "Option 1"},
            ...         {"type": "reply", "text": "Option 2"}
            ...     ],
            ...     [
            ...         {"type": "request_contact", "text": "Share Contact"}
            ...     ]
            ... ], oneTime=True)
        """
        return ReplyKeyboardAttachment(
            payload=Keyboard(
                buttons=buttons,
                one_time_keyboard=oneTime,
                resize_keyboard=resize,
            )
        )

    def removeKeyboard(self) -> ReplyKeyboardAttachment:
        """Create a keyboard removal attachment.

        Creates an attachment that removes the current reply keyboard.

        Returns:
            Keyboard removal attachment dictionary

        Example:
            >>> client = MaxBotClient("token")
            >>> remove_kb = client.removeKeyboard()
            >>> await client.sendMessage(chatId=12345, text="Keyboard removed", keyboard=remove_kb)
        """
        return ReplyKeyboardAttachment(payload=Keyboard(buttons=[], remove_keyboard=True))
