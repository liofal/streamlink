import unittest
from unittest.mock import MagicMock, patch

import requests

from notification_manager import SlackNotifier, TelegramNotifier


class TestNotificationManagerSecurity(unittest.TestCase):
    def _mock_http_error_response(self, status_code, reason):
        response = MagicMock()
        response.status_code = status_code
        response.reason = reason
        response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            f"{status_code} Client Error: {reason} for url: https://example.invalid/secret-token",
            response=response,
        )
        return response

    @patch("notification_manager.requests.post")
    def test_slack_http_error_does_not_log_webhook_secret(self, mock_post):
        webhook_secret = "T00000000/B00000000/super-secret-slack-token"
        mock_post.return_value = self._mock_http_error_response(403, "Forbidden")

        notifier = SlackNotifier(webhook_secret)

        with self.assertLogs("notification_manager", level="ERROR") as captured:
            notifier.notify("hello")

        logs = "\n".join(captured.output)
        self.assertIn("Slack notification failed with HTTP 403 Forbidden", logs)
        self.assertNotIn(webhook_secret, logs)
        self.assertNotIn("super-secret-slack-token", logs)
        self.assertNotIn("hooks.slack.com", logs)

    @patch("notification_manager.requests.post")
    def test_telegram_http_error_does_not_log_bot_token(self, mock_post):
        bot_token = "123456789:super-secret-telegram-token"
        mock_post.return_value = self._mock_http_error_response(401, "Unauthorized")

        notifier = TelegramNotifier(bot_token, "123456")

        with self.assertLogs("notification_manager", level="ERROR") as captured:
            notifier.notify("hello")

        logs = "\n".join(captured.output)
        self.assertIn("Telegram notification failed with HTTP 401 Unauthorized", logs)
        self.assertNotIn(bot_token, logs)
        self.assertNotIn("super-secret-telegram-token", logs)
        self.assertNotIn("api.telegram.org", logs)


if __name__ == "__main__":
    unittest.main()
