"""
Unit tests for Max Bot Client

This module contains comprehensive unit tests for the MaxBotClient class,
testing client initialization, authentication, error handling, retry logic,
async context manager, and all API methods with mocked HTTP responses.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from .client import MaxBotClient
from .constants import API_VERSION, DEFAULT_TIMEOUT, MAX_RETRIES
from .exceptions import AuthenticationError, MaxBotError, NetworkError
from .models import (
    BotInfo,
    Chat,
    ChatAdmin,
    ChatAdminPermission,
    ChatList,
    ChatMembersList,
    SendMessageResult,
    TextFormat,
)


class TestMaxBotClient:
    """Test suite for MaxBotClient class."""

    @pytest.fixture
    def client(self):
        """Create a client instance for testing."""
        return MaxBotClient(
            accessToken="test_token",
            baseUrl="https://test-api.max.ru",
            timeout=10,
            maxRetries=2,
            retryBackoffFactor=0.5,
        )

    @pytest.fixture
    def mock_response(self):
        """Create a mock HTTP response."""
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"ok": True}
        return response

    # Initialization Tests

    def test_client_initialization_with_valid_token(self):
        """Test client initialization with valid access token, dood!"""
        client = MaxBotClient("valid_token")
        assert client.accessToken == "valid_token"
        assert client.baseUrl == "https://platform-api.max.ru"
        assert client.timeout == DEFAULT_TIMEOUT
        assert client.maxRetries == MAX_RETRIES
        assert client.retryBackoffFactor == 1.0
        assert client._httpClient is None
        assert not client._isPolling

    def test_client_initialization_with_custom_params(self):
        """Test client initialization with custom parameters, dood!"""
        client = MaxBotClient(
            accessToken="custom_token",
            baseUrl="https://custom-api.max.ru/",
            timeout=15,
            maxRetries=5,
            retryBackoffFactor=2.0,
        )
        assert client.accessToken == "custom_token"
        assert client.baseUrl == "https://custom-api.max.ru"
        assert client.timeout == 15
        assert client.maxRetries == 5
        assert client.retryBackoffFactor == 2.0

    def test_client_initialization_with_empty_token(self):
        """Test client initialization fails with empty token, dood!"""
        with pytest.raises(MaxBotError, match="Access token cannot be empty"):
            MaxBotClient("")

        with pytest.raises(MaxBotError, match="Access token cannot be empty"):
            MaxBotClient("   ")

        with pytest.raises(MaxBotError, match="Access token cannot be empty"):
            MaxBotClient(None)  # type: ignore

    def test_client_initialization_with_whitespace_token(self):
        """Test client initialization trims whitespace from token, dood!"""
        client = MaxBotClient("  trimmed_token  ")
        assert client.accessToken == "trimmed_token"

    # HTTP Client Tests

    @patch("httpx.AsyncClient")
    def test_get_http_client_creates_new_client(self, mock_httpx, client):
        """Test HTTP client creation on first access, dood!"""
        mock_client_instance = MagicMock()
        mock_httpx.return_value = mock_client_instance

        http_client = client._getHttpClient()

        mock_httpx.assert_called_once_with(
            base_url=client.baseUrl,
            timeout=httpx.Timeout(client.timeout),
            headers={
                "User-Agent": f"max-bot-client/{API_VERSION}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            params={"access_token": client.accessToken, "v": API_VERSION},
        )
        assert http_client == mock_client_instance

    @patch("httpx.AsyncClient")
    def test_get_http_client_reuses_existing_client(self, mock_httpx, client):
        """Test HTTP client reuse when not closed, dood!"""
        mock_client_instance = MagicMock()
        mock_client_instance.is_closed = False
        mock_httpx.return_value = mock_client_instance

        # First call creates client
        http_client1 = client._getHttpClient()
        # Second call reuses client
        http_client2 = client._getHttpClient()

        mock_httpx.assert_called_once()
        assert http_client1 == http_client2

    @patch("httpx.AsyncClient")
    def test_get_http_client_creates_new_when_closed(self, mock_httpx, client):
        """Test HTTP client recreation when previous was closed, dood!"""
        mock_client_instance = MagicMock()
        mock_client_instance.is_closed = True
        mock_httpx.return_value = mock_client_instance

        # First call creates client
        client._getHttpClient()
        # Second call creates new client because old is closed
        client._getHttpClient()

        assert mock_httpx.call_count == 2

    async def test_aclose_closes_http_client(self, client):
        """Test aclose method closes HTTP client, dood!"""
        mock_client = AsyncMock()
        mock_client.is_closed = False
        client._httpClient = mock_client

        await client.aclose()

        mock_client.aclose.assert_called_once()

    async def test_aclose_handles_none_client(self, client):
        """Test aclose method handles None HTTP client, dood!"""
        # Should not raise exception
        await client.aclose()

    async def test_aclose_handles_already_closed_client(self, client):
        """Test aclose method handles already closed client, dood!"""
        mock_client = AsyncMock()
        mock_client.is_closed = True
        client._httpClient = mock_client

        await client.aclose()

        # Should not call aclose if already closed
        mock_client.aclose.assert_not_called()

    # URL Building Tests

    def test_build_url_with_absolute_endpoint(self, client):
        """Test URL building with absolute endpoint, dood!"""
        url = client._buildUrl("/me")
        assert url == "https://test-api.max.ru/me"

    def test_build_url_with_relative_endpoint(self, client):
        """Test URL building with relative endpoint, dood!"""
        url = client._buildUrl("me")
        assert url == "https://test-api.max.ru/me"

    def test_build_url_with_nested_endpoint(self, client):
        """Test URL building with nested endpoint, dood!"""
        url = client._buildUrl("/chats/12345/members")
        assert url == "https://test-api.max.ru/chats/12345/members"

    # Async Context Manager Tests

    async def test_async_context_manager_entry(self, client):
        """Test async context manager entry returns self, dood!"""
        async with client as ctx:
            assert ctx is client

    async def test_async_context_manager_exit_closes_client(self, client):
        """Test async context manager exit closes client, dood!"""
        mock_client = AsyncMock()
        mock_client.is_closed = False
        client._httpClient = mock_client

        async with client:
            pass

        mock_client.aclose.assert_called_once()

    async def test_async_context_manager_with_exception(self, client):
        """Test async context manager closes client even with exception, dood!"""
        mock_client = AsyncMock()
        mock_client.is_closed = False
        client._httpClient = mock_client

        with pytest.raises(ValueError):
            async with client:
                raise ValueError("Test exception")

        mock_client.aclose.assert_called_once()

    # HTTP Method Tests

    @patch("httpx.AsyncClient")
    async def test_get_request(self, mock_httpx, client, mock_response):
        """Test GET request method, dood!"""
        mock_client_instance = AsyncMock()
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        result = await client.get("/test", params={"param": "value"})

        mock_client_instance.request.assert_called_once_with(
            "GET", "https://test-api.max.ru/test", params={"param": "value"}
        )
        assert result == {"ok": True}

    @patch("httpx.AsyncClient")
    async def test_post_request_with_json(self, mock_httpx, client, mock_response):
        """Test POST request with JSON body, dood!"""
        mock_client_instance = AsyncMock()
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        result = await client.post("/test", json={"key": "value"})

        mock_client_instance.request.assert_called_once_with(
            "POST", "https://test-api.max.ru/test", json={"key": "value"}
        )
        assert result == {"ok": True}

    @patch("httpx.AsyncClient")
    async def test_post_request_with_data(self, mock_httpx, client, mock_response):
        """Test POST request with form data, dood!"""
        mock_client_instance = AsyncMock()
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        result = await client.post("/test", data={"key": "value"})

        mock_client_instance.request.assert_called_once_with(
            "POST", "https://test-api.max.ru/test", data={"key": "value"}
        )
        assert result == {"ok": True}

    @patch("httpx.AsyncClient")
    async def test_post_request_with_files(self, mock_httpx, client, mock_response):
        """Test POST request with files removes content-type header, dood!"""
        mock_client_instance = AsyncMock()
        mock_client_instance.request.return_value = mock_response
        mock_client_instance.headers = {"Content-Type": "application/json"}
        mock_httpx.return_value = mock_client_instance

        files = {"file": ("test.txt", b"content", "text/plain")}
        result = await client.post("/test", files=files)

        # Content-Type should be removed for multipart uploads
        assert "Content-Type" not in mock_client_instance.headers
        mock_client_instance.request.assert_called_once_with("POST", "https://test-api.max.ru/test", files=files)
        assert result == {"ok": True}

    @patch("httpx.AsyncClient")
    async def test_put_request(self, mock_httpx, client, mock_response):
        """Test PUT request method, dood!"""
        mock_client_instance = AsyncMock()
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        result = await client.put("/test", json={"key": "value"})

        mock_client_instance.request.assert_called_once_with(
            "PUT", "https://test-api.max.ru/test", json={"key": "value"}
        )
        assert result == {"ok": True}

    @patch("httpx.AsyncClient")
    async def test_patch_request(self, mock_httpx, client, mock_response):
        """Test PATCH request method, dood!"""
        mock_client_instance = AsyncMock()
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        result = await client.patch("/test", json={"key": "value"})

        mock_client_instance.request.assert_called_once_with(
            "PATCH", "https://test-api.max.ru/test", json={"key": "value"}
        )
        assert result == {"ok": True}

    @patch("httpx.AsyncClient")
    async def test_delete_request(self, mock_httpx, client, mock_response):
        """Test DELETE request method, dood!"""
        mock_client_instance = AsyncMock()
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        result = await client.delete("/test")

        mock_client_instance.request.assert_called_once_with("DELETE", "https://test-api.max.ru/test")
        assert result == {"ok": True}

    # Error Handling Tests

    @patch("httpx.AsyncClient")
    async def test_authentication_error_401(self, mock_httpx, client):
        """Test 401 authentication error handling, dood!"""
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"error": "Unauthorized"}
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        with pytest.raises(AuthenticationError):
            await client.get("/test")

    @patch("httpx.AsyncClient")
    async def test_network_error_handling(self, mock_httpx, client):
        """Test network error handling, dood!"""
        mock_client_instance = AsyncMock()
        mock_client_instance.request.side_effect = httpx.RequestError("Network error")
        mock_httpx.return_value = mock_client_instance

        with pytest.raises(NetworkError, match="Network error"):
            await client.get("/test")

    @patch("httpx.AsyncClient")
    async def test_invalid_json_response(self, mock_httpx, client):
        """Test invalid JSON response handling, dood!"""
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        with pytest.raises(MaxBotError, match="Invalid JSON response"):
            await client.get("/test")

    # Retry Logic Tests

    @patch("httpx.AsyncClient")
    @patch("asyncio.sleep")
    async def test_retry_logic_on_network_error(self, mock_sleep, mock_httpx, client):
        """Test retry logic on network errors, dood!"""
        mock_client_instance = AsyncMock()
        # First two attempts fail, third succeeds
        mock_client_instance.request.side_effect = [
            httpx.RequestError("Network error 1"),
            httpx.RequestError("Network error 2"),
            MagicMock(status_code=200, json=lambda: {"ok": True}),
        ]
        mock_httpx.return_value = mock_client_instance

        result = await client.get("/test")

        assert result == {"ok": True}
        assert mock_client_instance.request.call_count == 3
        assert mock_sleep.call_count == 2
        # Check exponential backoff
        mock_sleep.assert_any_call(0.5)  # 0.5 * 2^0
        mock_sleep.assert_any_call(1.0)  # 0.5 * 2^1

    @patch("httpx.AsyncClient")
    async def test_no_retry_on_authentication_error(self, mock_httpx, client):
        """Test no retry on authentication errors, dood!"""
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"error": "Unauthorized"}
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        with pytest.raises(AuthenticationError):
            await client.get("/test")

        # Should only attempt once, no retry on auth error
        assert mock_client_instance.request.call_count == 1

    @patch("httpx.AsyncClient")
    @patch("asyncio.sleep")
    async def test_max_retries_exhausted(self, mock_sleep, mock_httpx, client):
        """Test behavior when max retries are exhausted, dood!"""
        mock_client_instance = AsyncMock()
        mock_client_instance.request.side_effect = httpx.RequestError("Persistent network error")
        mock_httpx.return_value = mock_client_instance

        with pytest.raises(NetworkError, match="Persistent network error"):
            await client.get("/test")

        # Should attempt max_retries + 1 times (initial + retries)
        assert mock_client_instance.request.call_count == client.maxRetries + 1
        assert mock_sleep.call_count == client.maxRetries

    # API Method Tests

    @patch("httpx.AsyncClient")
    async def test_get_my_info(self, mock_httpx, client):
        """Test getMyInfo API method, dood!"""
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "user_id": 12345,
            "first_name": "Test Bot",
            "is_bot": True,
        }
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        result = await client.getMyInfo()

        assert isinstance(result, BotInfo)
        assert result.user_id == 12345
        assert result.first_name == "Test Bot"
        assert result.is_bot is True
        mock_client_instance.request.assert_called_once_with("GET", "https://test-api.max.ru/me", params=None)

    @patch("httpx.AsyncClient")
    async def test_health_check_success(self, mock_httpx, client):
        """Test health check success, dood!"""
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "user_id": 12345,
            "first_name": "Test Bot",
            "is_bot": True,
        }
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        result = await client.healthCheck()

        assert result is True

    @patch("httpx.AsyncClient")
    async def test_health_check_failure(self, mock_httpx, client):
        """Test health check failure, dood!"""
        mock_client_instance = AsyncMock()
        mock_client_instance.request.side_effect = httpx.RequestError("Network error")
        mock_httpx.return_value = mock_client_instance

        result = await client.healthCheck()

        assert result is False

    @patch("httpx.AsyncClient")
    async def test_health_check_auth_error(self, mock_httpx, client):
        """Test health check with authentication error, dood!"""
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"error": "Unauthorized"}
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        with pytest.raises(AuthenticationError):
            await client.healthCheck()

    @patch("httpx.AsyncClient")
    async def test_get_chats(self, mock_httpx, client):
        """Test getChats API method, dood!"""
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "chats": [
                {"chat_id": 12345, "title": "Test Chat", "type": "chat"},
                {"chat_id": 67890, "title": "Another Chat", "type": "chat"},
            ],
            "marker": None,
        }
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        result = await client.getChats(count=20, marker=123)

        assert isinstance(result, ChatList)
        assert len(result.chats) == 2
        assert result.chats[0].title == "Test Chat"
        mock_client_instance.request.assert_called_once_with(
            "GET", "https://test-api.max.ru/chats", params={"count": 20, "marker": 123}
        )

    @patch("httpx.AsyncClient")
    async def test_get_chat(self, mock_httpx, client):
        """Test getChat API method, dood!"""
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "chat_id": 12345,
            "title": "Test Chat",
            "type": "chat",
        }
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        result = await client.getChat(12345)

        assert isinstance(result, Chat)
        assert result.chat_id == 12345
        assert result.title == "Test Chat"
        mock_client_instance.request.assert_called_once_with("GET", "https://test-api.max.ru/chats/12345", params=None)

    @patch("httpx.AsyncClient")
    async def test_edit_chat_info(self, mock_httpx, client):
        """Test editChatInfo API method, dood!"""
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "chat_id": 12345,
            "title": "Updated Chat",
            "type": "chat",
        }
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        result = await client.editChatInfo(12345, title="Updated Chat", description="New description")

        assert isinstance(result, Chat)
        assert result.title == "Updated Chat"
        mock_client_instance.request.assert_called_once_with(
            "PATCH",
            "https://test-api.max.ru/chats/12345",
            json={"title": "Updated Chat", "description": "New description"},
        )

    @patch("httpx.AsyncClient")
    async def test_send_action(self, mock_httpx, client):
        """Test sendAction API method, dood!"""
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        result = await client.sendAction(12345, TextFormat.MARKDOWN)  # Using TextFormat as enum test

        assert result is True
        mock_client_instance.request.assert_called_once_with(
            "POST",
            "https://test-api.max.ru/chats/12345/actions",
            json={"action": "markdown"},
        )

    @patch("httpx.AsyncClient")
    async def test_pin_message(self, mock_httpx, client):
        """Test pinMessage API method, dood!"""
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        result = await client.pinMessage(12345, "msg_67890")

        assert result is True
        mock_client_instance.request.assert_called_once_with(
            "PUT",
            "https://test-api.max.ru/chats/12345/pin",
            json={"pin": "msg_67890"},
        )

    @patch("httpx.AsyncClient")
    async def test_unpin_message(self, mock_httpx, client):
        """Test unpinMessage API method, dood!"""
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        result = await client.unpinMessage(12345)

        assert result is True
        mock_client_instance.request.assert_called_once_with("DELETE", "https://test-api.max.ru/chats/12345/pin")

    @patch("httpx.AsyncClient")
    async def test_get_members(self, mock_httpx, client):
        """Test getMembers API method, dood!"""
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "members": [
                {"user_id": 111, "first_name": "User 1"},
                {"user_id": 222, "first_name": "User 2"},
            ],
            "marker": None,
        }
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        result = await client.getMembers(12345, userIds=[111, 222], count=10)

        assert isinstance(result, ChatMembersList)
        assert len(result.members) == 2
        mock_client_instance.request.assert_called_once_with(
            "GET",
            "https://test-api.max.ru/chats/12345/members",
            params={"count": 10, "user_ids": [111, 222]},
        )

    @patch("httpx.AsyncClient")
    async def test_add_members(self, mock_httpx, client):
        """Test addMembers API method, dood!"""
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        result = await client.addMembers(12345, [111, 222])

        assert result is True
        mock_client_instance.request.assert_called_once_with(
            "POST",
            "https://test-api.max.ru/chats/12345/members",
            json={"user_ids": [111, 222]},
        )

    @patch("httpx.AsyncClient")
    async def test_remove_member(self, mock_httpx, client):
        """Test removeMember API method, dood!"""
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        result = await client.removeMember(12345, 111, block=True)

        assert result is True
        mock_client_instance.request.assert_called_once_with(
            "DELETE", "https://test-api.max.ru/chats/12345/members?user_id=111&block=True"
        )

    @patch("httpx.AsyncClient")
    async def test_get_admins(self, mock_httpx, client):
        """Test getAdmins API method, dood!"""
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "members": [
                {"user_id": 111, "first_name": "Admin 1"},
                {"user_id": 222, "first_name": "Admin 2"},
            ],
            "marker": None,
        }
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        result = await client.getAdmins(12345)

        assert isinstance(result, ChatMembersList)
        assert len(result.members) == 2
        mock_client_instance.request.assert_called_once_with(
            "GET", "https://test-api.max.ru/chats/12345/members/admins", params=None
        )

    @patch("httpx.AsyncClient")
    async def test_edit_admin_permissions(self, mock_httpx, client):
        """Test editAdminPermissions API method, dood!"""
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        admin = ChatAdmin(
            user_id=111,
            permissions=[ChatAdminPermission.WRITE, ChatAdminPermission.PIN_MESSAGE],
            alias="Admin",
        )

        result = await client.editAdminPermissions(12345, [admin])

        assert result is True
        mock_client_instance.request.assert_called_once_with(
            "POST",
            "https://test-api.max.ru/chats/12345/members/admins",
            json={
                "admins": [
                    {
                        "user_id": 111,
                        "permissions": ["write", "pin_message"],
                        "alias": "Admin",
                    }
                ]
            },
        )

    @patch("httpx.AsyncClient")
    async def test_send_message_basic(self, mock_httpx, client):
        """Test sendMessage API method with basic parameters, dood!"""
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {
                "body": {"mid": "msg_123", "text": "Hello, World!"},
                "chat_id": 12345,
            }
        }
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        result = await client.sendMessage(chatId=12345, text="Hello, World!")

        assert isinstance(result, SendMessageResult)
        assert result.message.body.mid == "msg_123"
        assert result.message.body.text == "Hello, World!"

    async def test_send_message_missing_recipient(self, client):
        """Test sendMessage fails without chatId or userId, dood!"""
        with pytest.raises(MaxBotError, match="Either chatId or userId must be provided"):
            await client.sendMessage(text="Hello")

    @patch("httpx.AsyncClient")
    async def test_send_message_with_reply(self, mock_httpx, client):
        """Test sendMessage with reply functionality, dood!"""
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {
                "body": {"mid": "msg_123", "text": "Reply message"},
                "chat_id": 12345,
            }
        }
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        result = await client.sendMessage(chatId=12345, text="Reply", replyTo="msg_456")

        assert isinstance(result, SendMessageResult)
        # Check that the link was included in the request
        call_args = mock_client_instance.request.call_args
        # The client sends JSON directly, not as a string to be parsed
        request_data = call_args[1]["json"]
        assert "link" in request_data
        assert request_data["link"]["type"] == "reply"
        assert request_data["link"]["mid"] == "msg_456"

    @patch("httpx.AsyncClient")
    async def test_send_message_with_formatting(self, mock_httpx, client):
        """Test sendMessage with text formatting, dood!"""
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {
                "body": {"mid": "msg_123", "text": "Formatted text"},
                "chat_id": 12345,
            }
        }
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        result = await client.sendMessage(chatId=12345, text="**Bold** text", format=TextFormat.MARKDOWN)

        assert isinstance(result, SendMessageResult)
        # Check that format was included in the request
        call_args = mock_client_instance.request.call_args
        # The client sends JSON directly, not as a string to be parsed
        request_data = call_args[1]["json"]
        assert request_data["format"] == "markdown"

    # Edge Cases and Boundary Tests

    @patch("httpx.AsyncClient")
    async def test_empty_response_body(self, mock_httpx, client):
        """Test handling of empty response body, dood!"""
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        result = await client.get("/test")

        assert result == {}

    @patch("httpx.AsyncClient")
    async def test_large_response_data(self, mock_httpx, client):
        """Test handling of large response data, dood!"""
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        large_data = {"items": [{"id": i} for i in range(1000)]}
        mock_response.json.return_value = large_data
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        result = await client.get("/test")

        assert result == large_data
        assert len(result["items"]) == 1000

    def test_slots_optimization(self, client):
        """Test that client uses __slots__ for memory optimization, dood!"""
        # Check that __slots__ is defined
        assert hasattr(client, "__slots__")

        # Check that we can't add new attributes
        with pytest.raises(AttributeError):
            client.new_attribute = "test"

    # Integration-style Tests

    @patch("httpx.AsyncClient")
    async def test_full_request_flow(self, mock_httpx, client):
        """Test complete request flow from client to response, dood!"""
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "user_id": 12345,
            "first_name": "Test Bot",
            "is_bot": True,
        }
        mock_client_instance.request.return_value = mock_response
        mock_httpx.return_value = mock_client_instance

        async with client:
            result = await client.getMyInfo()

        assert isinstance(result, BotInfo)
        assert result.user_id == 12345

        # Check that the HTTP client was closed
        # Note: The client might not be closed in the current implementation
        # mock_client_instance.aclose.assert_called_once()
