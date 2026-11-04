import json
import queue
import threading
import time
import requests
from abc import ABC, abstractmethod

import logging

logger = logging.getLogger(__name__)
from enum import Enum, auto

class NotifierType(Enum):
    SLACK = auto()
    TELEGRAM = auto()

class Notifier(ABC):
    @abstractmethod
    def notify(self, message):
        raise NotImplementedError("Subclasses must implement the notify method")

def _log_notification_http_error(service_name, error):
    response = getattr(error, "response", None)
    if response is None:
        logger.error("%s notification failed with an HTTP error", service_name)
        return

    status_code = getattr(response, "status_code", "unknown")
    reason = getattr(response, "reason", "")
    if reason:
        logger.error("%s notification failed with HTTP %s %s", service_name, status_code, reason)
    else:
        logger.error("%s notification failed with HTTP %s", service_name, status_code)


def _log_notification_unexpected_error(service_name, error):
    logger.error(
        "Unexpected error occurred while sending message to %s: %s",
        service_name,
        type(error).__name__,
    )

QUEUE_MAXSIZE = 50
FLUSH_TIMEOUT_SECONDS = 5


class NotificationManager:
    """Fans messages out to the notifiers from one background daemon thread.

    notify_all() only enqueues, so a slow or down Slack/Telegram never delays
    recording. A single FIFO worker keeps messages in order. Stop signals are
    delivered to the main thread only, and the worker catches Exception only.
    """

    def __init__(self, config):
        self.config = config
        self.notifiers = []
        self._queue = queue.Queue(maxsize=QUEUE_MAXSIZE)
        self._worker = None
        self._worker_lock = threading.Lock()
        self.initialize_notifiers()

    def initialize_notifiers(self):
        slack_id = self.config.slack_id
        if slack_id:
            self.notifiers.append(NotifierFactory.create_notifier(NotifierType.SLACK, slack_id=slack_id))

        telegram_bot_token = self.config.telegram_bot_token
        telegram_chat_id = self.config.telegram_chat_id
        if telegram_bot_token and telegram_chat_id:
            self.notifiers.append(NotifierFactory.create_notifier(NotifierType.TELEGRAM, bot_token=telegram_bot_token, chat_id=telegram_chat_id))

    def add_notifier(self, notifier):
        self.notifiers.append(notifier)

    def notify_all(self, message):
        if not self.notifiers:
            return
        self._ensure_worker()
        try:
            self._queue.put_nowait(message)
        except queue.Full:
            logger.warning("Notification queue is full; dropping a message")

    def _ensure_worker(self):
        with self._worker_lock:
            if self._worker is None:
                self._worker = threading.Thread(target=self._run_worker, name="notifier", daemon=True)
                self._worker.start()

    def _run_worker(self):
        while True:
            message = self._queue.get()
            try:
                for notifier in list(self.notifiers):
                    try:
                        notifier.notify(message)
                    except Exception as error:  # never log the message text of the error
                        logger.error("Notifier failed: %s", type(error).__name__)
            finally:
                self._queue.task_done()

    def flush(self, timeout=FLUSH_TIMEOUT_SECONDS):
        """Wait up to timeout seconds for queued messages to be sent. True if drained."""
        deadline = time.monotonic() + timeout
        with self._queue.all_tasks_done:
            while self._queue.unfinished_tasks:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._queue.all_tasks_done.wait(remaining)
        return True

class SlackNotifier(Notifier):
    def __init__(self, slack_id):
        self.slack_id = slack_id

    def notify(self, message):
        slack_url = f"https://hooks.slack.com/services/{self.slack_id}"
        slack_data = {"text": message}

        try:
            response = requests.post(
                slack_url,
                data=json.dumps(slack_data),
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            response.raise_for_status()
        except requests.exceptions.HTTPError as error:
            _log_notification_http_error("Slack", error)
        except Exception as error:
            _log_notification_unexpected_error("Slack", error)

class TelegramNotifier(Notifier):
    def __init__(self, bot_token, chat_id):
        self.bot_token = bot_token
        self.chat_id = chat_id

    def notify(self, message):
        telegram_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        telegram_data = {
            "chat_id": self.chat_id,
            "text": message,
        }

        try:
            response = requests.post(
                telegram_url,
                data=json.dumps(telegram_data),
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            response.raise_for_status()
        except requests.exceptions.HTTPError as error:
            _log_notification_http_error("Telegram", error)
        except Exception as error:
            _log_notification_unexpected_error("Telegram", error)

class NotifierFactory:
    _notifiers = {
        NotifierType.SLACK: SlackNotifier,
        NotifierType.TELEGRAM: TelegramNotifier,
    }

    @staticmethod
    def create_notifier(notifier_type: NotifierType, *args, **kwargs):
        notifier_class = NotifierFactory._notifiers.get(notifier_type, None)
        if notifier_class:
            return notifier_class(*args, **kwargs)
        raise ValueError(f"Notifier type '{notifier_type}' is not supported.")