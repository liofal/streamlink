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


class TestTwitchClientReset(unittest.TestCase):
    def test_failed_refresh_does_not_hang_next_call(self):
        # Real twitchAPI lock: a failed app-token refresh leaves _app_token_refresh_lock set on
        # that instance, so a second refresh on the same instance would wait on it forever.
        from twitchAPI.twitch import Twitch

        async def scenario():
            manager = TwitchManager(_config())
            generate_calls = {"n": 0}

            async def flaky_generate(self_twitch, *args, **kwargs):
                generate_calls["n"] += 1
                if generate_calls["n"] == 2:  # 1 = client construction, 2 = first refresh
                    raise TwitchAuthorizationException("token endpoint down")

            async def refresh_via_library(_iterator):
                await manager.twitch._refresh_app_token()
                return "ok"

            with patch.object(Twitch, "_generate_app_token", flaky_generate), \
                    patch("twitch_manager.first", refresh_via_library):
                with self.assertRaises(TwitchAuthorizationException):
                    await manager.get_from_twitch_async("get_users", logins="x")
                self.assertIsNone(manager.twitch)
                self.assertEqual(await manager.get_from_twitch_async("get_users", logins="x"), "ok")

        # Outer guard so a regression fails instead of hanging the suite.
        asyncio.run(asyncio.wait_for(scenario(), 5))

    def test_hung_call_times_out_and_resets_client(self):
        manager = TwitchManager(_config())
        manager.twitch = MagicMock()

        async def never(**kw):
            await asyncio.Event().wait()
            yield  # pragma: no cover

        manager.twitch.get_users = never
        with patch("twitch_manager.TWITCH_CALL_TIMEOUT", 0.2), \
                self.assertLogs("twitch_manager", level="INFO") as captured:
            status, _ = manager.check_user("someone")

        self.assertEqual(status, StreamStatus.ERROR)
        self.assertIsNone(manager.twitch)
        logs = "\n".join(captured.output)
        self.assertIn("TimeoutError", logs)
        self.assertNotIn(CANARY, logs)

    def test_client_rebuilt_after_generic_failure(self):
        manager = TwitchManager(_config())
        created = []

        class FakeTwitch:
            def __init__(self, *a, **k):
                created.append(self)

            def __await__(self):
                async def ready():
                    return self
                return ready().__await__()

            def get_users(self, **kw):
                raise RuntimeError(f"boom {CANARY}")

        with patch("twitch_manager.Twitch", FakeTwitch):
            with self.assertRaises(RuntimeError):
                manager.get_from_twitch("get_users", logins="x")
            self.assertIsNone(manager.twitch)
            with self.assertRaises(RuntimeError):
                manager.get_from_twitch("get_users", logins="x")
        self.assertEqual(len(created), 2)


if __name__ == "__main__":
    unittest.main()
