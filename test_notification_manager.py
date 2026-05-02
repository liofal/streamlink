import unittest
from unittest.mock import MagicMock

import requests

from notification_manager import redact_url, log_http_error


class TestNotificationManager(unittest.TestCase):
    def test_redact_url_redacts_telegram_bot_token(self):
        url = "https://api.telegram.org/bot123456:secret/sendMessage"
        self.assertEqual(redact_url(url), "https://api.telegram.org/bot<redacted>/sendMessage")

    def test_redact_url_redacts_slack_webhook_secret(self):
        url = "https://hooks.slack.com/services/T000/B000/SECRET"
        self.assertEqual(redact_url(url), "https://hooks.slack.com/services/<redacted>")

    def test_log_http_error_does_not_log_secret_url(self):
        response = MagicMock()
        response.status_code = 401
        response.reason = "Unauthorized"
        response.url = "https://api.telegram.org/bot123456:secret/sendMessage"
        exc = requests.exceptions.HTTPError(response=response)

        with self.assertLogs("notification_manager", level="ERROR") as captured:
            log_http_error("Telegram", exc)

        rendered = "\n".join(captured.output)
        self.assertIn("bot<redacted>", rendered)
        self.assertNotIn("123456:secret", rendered)


if __name__ == "__main__":
    unittest.main()
