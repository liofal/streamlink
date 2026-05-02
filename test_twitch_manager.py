import asyncio
import unittest
from unittest.mock import MagicMock

from twitch_manager import TwitchManager


class TestTwitchManagerSecurity(unittest.TestCase):
    def test_app_refresh_does_not_log_token_value(self):
        manager = TwitchManager(MagicMock())
        secret_token = "secret-refresh-token-value"

        with self.assertLogs("twitch_manager", level="INFO") as captured:
            asyncio.run(manager.app_refresh(secret_token))

        logs = "\n".join(captured.output)
        self.assertIn("Twitch app token refreshed", logs)
        self.assertNotIn(secret_token, logs)


if __name__ == "__main__":
    unittest.main()
