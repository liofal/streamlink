import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import requests

import notification_manager
from notification_manager import NotificationManager, SlackNotifier, TelegramNotifier


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


class Recorder:
    def __init__(self):
        self.messages = []

    def notify(self, message):
        self.messages.append(message)


def make_manager(*notifiers):
    manager = NotificationManager(MagicMock(slack_id=None, telegram_bot_token=None, telegram_chat_id=None))
    for notifier in notifiers:
        manager.add_notifier(notifier)
    return manager


class TestAsyncDispatch(unittest.TestCase):
    def test_notify_all_returns_immediately_with_blocking_notifier(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        blocker = MagicMock()
        blocker.notify.side_effect = lambda m: gate.wait(10)
        manager = make_manager(blocker)
        start = time.monotonic()
        for i in range(3):
            manager.notify_all(f"m{i}")
        self.assertLess(time.monotonic() - start, 1)

    def test_order_preserved_and_flush_drains(self):
        rec = Recorder()
        manager = make_manager(rec)
        for i in range(20):
            manager.notify_all(f"m{i}")
        self.assertTrue(manager.flush(timeout=5))
        self.assertEqual(rec.messages, [f"m{i}" for i in range(20)])

    def test_full_queue_drops_without_raising(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        blocker = MagicMock()
        blocker.notify.side_effect = lambda m: gate.wait(10)
        manager = make_manager(blocker)
        with self.assertLogs("notification_manager", level="WARNING") as logs:
            for i in range(notification_manager.QUEUE_MAXSIZE + 10):
                manager.notify_all(f"m{i}")
        self.assertIn("dropping", "\n".join(logs.output))
        self.assertNotIn("m0", "\n".join(logs.output))

    def test_flush_is_bounded_when_worker_is_stuck(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        blocker = MagicMock()
        blocker.notify.side_effect = lambda m: gate.wait(10)
        manager = make_manager(blocker)
        manager.notify_all("x")
        start = time.monotonic()
        self.assertFalse(manager.flush(timeout=0.2))
        self.assertLess(time.monotonic() - start, 2)

    def test_worker_survives_raising_notifier(self):
        bad = MagicMock()
        bad.notify.side_effect = RuntimeError("https://x?client_secret=abc")
        rec = Recorder()
        manager = make_manager(bad, rec)
        with self.assertLogs("notification_manager", level="ERROR") as logs:
            manager.notify_all("a")
            manager.notify_all("b")
            self.assertTrue(manager.flush(timeout=5))
        self.assertEqual(rec.messages, ["a", "b"])
        self.assertNotIn("client_secret", "\n".join(logs.output))

    def test_worker_is_daemon_and_flush_on_empty_is_instant(self):
        manager = make_manager(Recorder())
        self.assertTrue(manager.flush(timeout=0.1))
        manager.notify_all("a")
        self.assertTrue(manager._worker.daemon)
