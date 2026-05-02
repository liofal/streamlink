import importlib.util
import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).with_name("streamlink-recorder.py")
spec = importlib.util.spec_from_file_location("streamlink_recorder", MODULE_PATH)
streamlink_recorder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(streamlink_recorder)


class TestConfigParsing(unittest.TestCase):
    def parse_with_env(self, argv, env):
        with patch.dict(os.environ, env, clear=True):
            return streamlink_recorder.parse_arguments(argv)

    def test_cli_arguments_populate_config(self):
        config = self.parse_with_env(
            [
                "-user", "cli-user",
                "-timer", "123",
                "-quality", "best",
                "-clientid", "cli-client-id",
                "-clientsecret", "cli-client-secret",
                "-slackid", "cli-slack",
                "-gamelist", "game-a,game-b",
                "-telegrambottoken", "cli-telegram-token",
                "-telegramchatid", "cli-chat",
                "-oauthtoken", "cli-oauth",
            ],
            {},
        )

        self.assertEqual(config.user, "cli-user")
        self.assertEqual(config.timer, 123)
        self.assertEqual(config.quality, "best")
        self.assertEqual(config.client_id, "cli-client-id")
        self.assertEqual(config.client_secret, "cli-client-secret")
        self.assertEqual(config.slack_id, "cli-slack")
        self.assertEqual(config.game_list, "game-a,game-b")
        self.assertEqual(config.telegram_bot_token, "cli-telegram-token")
        self.assertEqual(config.telegram_chat_id, "cli-chat")
        self.assertEqual(config.oauth_token, "cli-oauth")

    def test_cli_arguments_override_environment_values(self):
        config = self.parse_with_env(
            [
                "-user", "cli-user",
                "-timer", "321",
                "-quality", "cli-quality",
                "-clientid", "cli-client-id",
                "-clientsecret", "cli-client-secret",
                "-oauthtoken", "cli-oauth",
            ],
            {
                "TWITCH_USER": "env-user",
                "TIMER": "123",
                "STREAM_QUALITY": "env-quality",
                "TWITCH_CLIENT_ID": "env-client-id",
                "TWITCH_CLIENT_SECRET": "env-client-secret",
                "TWITCH_AUTH_TOKEN": "env-oauth",
            },
        )

        self.assertEqual(config.user, "cli-user")
        self.assertEqual(config.timer, 321)
        self.assertEqual(config.quality, "cli-quality")
        self.assertEqual(config.client_id, "cli-client-id")
        self.assertEqual(config.client_secret, "cli-client-secret")
        self.assertEqual(config.oauth_token, "cli-oauth")

    def test_modern_environment_fallback_populates_config(self):
        config = self.parse_with_env(
            [],
            {
                "TWITCH_USER": "env-user",
                "TIMER": "456",
                "STREAM_QUALITY": "1080p60",
                "TWITCH_CLIENT_ID": "env-client-id",
                "TWITCH_CLIENT_SECRET": "env-client-secret",
                "SLACK_ID": "env-slack",
                "GAME_LIST": "game-1",
                "TELEGRAM_BOT_TOKEN": "env-telegram-token",
                "TELEGRAM_CHAT_ID": "env-chat",
                "TWITCH_AUTH_TOKEN": "env-oauth",
            },
        )

        self.assertEqual(config.user, "env-user")
        self.assertEqual(config.timer, 456)
        self.assertEqual(config.quality, "1080p60")
        self.assertEqual(config.client_id, "env-client-id")
        self.assertEqual(config.client_secret, "env-client-secret")
        self.assertEqual(config.slack_id, "env-slack")
        self.assertEqual(config.game_list, "game-1")
        self.assertEqual(config.telegram_bot_token, "env-telegram-token")
        self.assertEqual(config.telegram_chat_id, "env-chat")
        self.assertEqual(config.oauth_token, "env-oauth")

    def test_legacy_lowercase_environment_fallback_populates_config(self):
        config = self.parse_with_env(
            [],
            {
                "user": "legacy-user",
                "timer": "789",
                "quality": "720p",
                "clientid": "legacy-client-id",
                "clientsecret": "legacy-client-secret",
                "slackid": "legacy-slack",
                "gamelist": "legacy-game",
                "telegrambottoken": "legacy-telegram-token",
                "telegramchatid": "legacy-chat",
                "oauthtoken": "legacy-oauth",
            },
        )

        self.assertEqual(config.user, "legacy-user")
        self.assertEqual(config.timer, 789)
        self.assertEqual(config.quality, "720p")
        self.assertEqual(config.client_id, "legacy-client-id")
        self.assertEqual(config.client_secret, "legacy-client-secret")
        self.assertEqual(config.slack_id, "legacy-slack")
        self.assertEqual(config.game_list, "legacy-game")
        self.assertEqual(config.telegram_bot_token, "legacy-telegram-token")
        self.assertEqual(config.telegram_chat_id, "legacy-chat")
        self.assertEqual(config.oauth_token, "legacy-oauth")

    def test_twitch_oauth_token_env_alias_is_supported(self):
        config = self.parse_with_env(
            [],
            {
                "TWITCH_USER": "env-user",
                "TWITCH_CLIENT_ID": "env-client-id",
                "TWITCH_CLIENT_SECRET": "env-client-secret",
                "TWITCH_OAUTH_TOKEN": "env-oauth-alias",
            },
        )

        self.assertEqual(config.oauth_token, "env-oauth-alias")

    def test_missing_required_config_fails_clearly(self):
        stderr = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, "stderr", stderr):
            with self.assertRaises(SystemExit) as raised:
                streamlink_recorder.parse_arguments([])

        self.assertNotEqual(raised.exception.code, 0)
        self.assertIn("Missing required configuration: user", stderr.getvalue())
        self.assertIn("TWITCH_USER", stderr.getvalue())

    def test_invalid_environment_timer_fails_clearly(self):
        stderr = io.StringIO()
        env = {
            "TWITCH_USER": "env-user",
            "TIMER": "not-an-int",
            "TWITCH_CLIENT_ID": "env-client-id",
            "TWITCH_CLIENT_SECRET": "env-client-secret",
        }
        with patch.dict(os.environ, env, clear=True), patch.object(sys, "stderr", stderr):
            with self.assertRaises(SystemExit) as raised:
                streamlink_recorder.parse_arguments([])

        self.assertNotEqual(raised.exception.code, 0)
        self.assertIn("Invalid integer for timer", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
