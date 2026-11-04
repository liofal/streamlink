import asyncio
import unittest
from unittest.mock import MagicMock, patch

from twitchAPI.type import TwitchAuthorizationException

from twitch_manager import StreamStatus, TwitchManager

CANARY = "FAKE_SECRET_CANARY_123"


def _config():
    config = MagicMock()
    config.client_id = "FAKECLIENTID"
    config.client_secret = CANARY
    config.game_list = ""
    return config


class _FakeResponse:
    status = 503

    def __init__(self, url):
        self.url = url  # real ClientResponse reprs include the request URL

    async def text(self):
        return ""

    def __repr__(self):
        return f"<ClientResponse({self.url}) [503]>"

    async def json(self):
        return {}


class TestTwitchManagerSecurity(unittest.TestCase):
    def test_app_refresh_does_not_log_token_value(self):
        manager = TwitchManager(MagicMock())
        secret_token = "secret-refresh-token-value"

        with self.assertLogs("twitch_manager", level="INFO") as captured:
            asyncio.run(manager.app_refresh(secret_token))

        logs = "\n".join(captured.output)
        self.assertIn("Twitch app token refreshed", logs)
        self.assertNotIn(secret_token, logs)

    def _assert_no_leak(self, logs):
        self.assertNotIn(CANARY, logs)
        self.assertNotIn("client_secret", logs)
        self.assertNotIn("FAKECLIENTID", logs)

    def test_failing_token_request_does_not_log_client_secret(self):
        # Real twitchAPI raise path (twitch.py token generation); only the HTTP layer is faked.
        async def fake_post(self_session, url, *args, **kwargs):
            self.assertIn(CANARY, url)  # the URL really carries the secret
            return _FakeResponse(url)

        manager = TwitchManager(_config())
        with patch("aiohttp.ClientSession.post", fake_post), \
                self.assertLogs("twitch_manager", level="INFO") as captured:
            status, _ = manager.check_user("someone")

        self.assertEqual(status, StreamStatus.ERROR)
        logs = "\n".join(captured.output)
        self.assertIn("TwitchAuthorizationException", logs)
        self.assertIn("503", logs)
        self._assert_no_leak(logs)

    def test_auth_exception_with_secret_url_in_message_is_redacted(self):
        class Resp:
            def text(self):
                pass

        message = (
            "Authentication failed with code 503 "
            f"(<bound method of https://id.twitch.tv/oauth2/token?client_secret={CANARY}> {Resp().text})"
        )
        manager = TwitchManager(_config())
        manager.get_from_twitch = MagicMock(side_effect=TwitchAuthorizationException(message))
        with self.assertLogs("twitch_manager", level="INFO") as captured:
            status, _ = manager.check_user("someone")

        self.assertEqual(status, StreamStatus.ERROR)
        logs = "\n".join(captured.output)
        self.assertIn("TwitchAuthorizationException", logs)
        self.assertIn("503", logs)
        self._assert_no_leak(logs)

    def test_non_auth_exception_logs_only_type(self):
        manager = TwitchManager(_config())
        manager.get_from_twitch = MagicMock(side_effect=RuntimeError(f"boom {CANARY}"))
        with self.assertLogs("twitch_manager", level="INFO") as captured:
            manager.check_user("someone")

        logs = "\n".join(captured.output)
        self.assertIn("RuntimeError", logs)
        self._assert_no_leak(logs)
        self.assertNotIn("boom", logs)

    def test_auth_exception_with_unparseable_message_logs_only_type(self):
        manager = TwitchManager(_config())
        manager.get_from_twitch = MagicMock(
            side_effect=TwitchAuthorizationException(f"something new client_secret={CANARY}")
        )
        with self.assertLogs("twitch_manager", level="INFO") as captured:
            manager.check_user("someone")

        logs = "\n".join(captured.output)
        self.assertIn("TwitchAuthorizationException", logs)
        self._assert_no_leak(logs)
        self.assertNotIn("something new", logs)


if __name__ == "__main__":
    unittest.main()
