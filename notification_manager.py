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
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error occurred: {e}")
        except Exception as e:
            logger.error(f"Unexpected error occurred while sending message to Slack: {e}")

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
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error occurred: {e}")
        except Exception as exc:
            logger.error(f"Unexpected error occurred while sending message to Telegram: {exc}")

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