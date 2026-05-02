import json
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

class NotificationManager:
    def __init__(self, config):
        self.config = config
        self.notifiers = []
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
        for notifier in self.notifiers:
            notifier.notify(message)

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