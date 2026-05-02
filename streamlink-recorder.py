"""
This script checks if a user on twitch is currently streaming and 
then records the stream via streamlink
"""
import datetime
import argparse
import os
import re
import time
import logging
import sys

from twitch_manager import TwitchManager, StreamStatus
from streamlink_manager import StreamlinkManager
from notification_manager import NotificationManager

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

def env_or_arg(args, arg_name, *env_names, default=None):
    value = getattr(args, arg_name)
    if value not in (None, ""):
        return value

    for env_name in env_names:
        value = os.getenv(env_name)
        if value not in (None, ""):
            return value

    return default


class AppConfig:
    def __init__(self, args):
        self.timer = int(env_or_arg(args, "timer", "timer", "TIMER", default=240))
        self.user = env_or_arg(args, "user", "user", "TWITCH_USER")
        self.quality = env_or_arg(args, "quality", "quality", "STREAM_QUALITY", default="720p60,720p,best")
        self.client_id = env_or_arg(args, "clientid", "clientid", "TWITCH_CLIENT_ID")
        self.client_secret = env_or_arg(args, "clientsecret", "clientsecret", "TWITCH_CLIENT_SECRET")
        self.game_list = env_or_arg(args, "gamelist", "gamelist", "GAME_LIST", default="")
        self.slack_id = env_or_arg(args, "slackid", "slackid", "SLACK_ID")
        self.telegram_bot_token = env_or_arg(args, "telegrambottoken", "telegrambottoken", "TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = env_or_arg(args, "telegramchatid", "telegramchatid", "TELEGRAM_CHAT_ID")
        self.oauth_token = env_or_arg(args, "oauthtoken", "oauthtoken", "TWITCH_OAUTH_TOKEN")

def loop_check(config):
    twitch_manager = TwitchManager(config)
    streamlink_manager = StreamlinkManager(config)
    notifier_manager = NotificationManager(config)

    while True:
        stream_status, title = twitch_manager.check_user(config.user)
        if stream_status == StreamStatus.ONLINE:
            safe_title = re.sub(r"[^\w\s._-]|[<>:\"/\\|?*]", "", title)
            safe_title = os.path.basename(safe_title)
            filename = f"{config.user} - {datetime.datetime.now().strftime('%Y-%m-%d %H-%M-%S')} - {safe_title}"
            recorded_filename = os.path.join("./download/", filename)
            message = f"Recording {config.user} ..."
            notifier_manager.notify_all(message)
            logger.info(message)
            try:
                streamlink_manager.run_streamlink(config.user, recorded_filename)
            except Exception as exc:
                logger.exception("Failed to record %s: %s", config.user, exc)
                notifier_manager.notify_all(f"Failed to record {config.user}. Going back to checking...")
            else:
                message = f"Stream {config.user} is done. File saved as {filename}. Going back to checking.."
                logger.info(message)
                notifier_manager.notify_all(message)
        time.sleep(config.timer)

def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("-timer", type=int, help="Stream check interval (less than 15s are not recommended)")
    parser.add_argument("-user", help="Twitch user that we are checking")
    parser.add_argument("-quality", help="Recording quality")
    parser.add_argument("-clientid", help="Your Twitch app client id")
    parser.add_argument("-clientsecret", help="Your Twitch app client secret")
    parser.add_argument("-slackid", help="Your slack app client id")
    parser.add_argument("-gamelist", help="The game list to be recorded")
    parser.add_argument("-telegrambottoken", help="Your Telegram bot token")
    parser.add_argument("-telegramchatid", help="Your Telegram chat ID where the bot will send messages")
    parser.add_argument("-oauthtoken", help="Your OAuth token for Twitch API")
    args = parser.parse_args()
    config = AppConfig(args)

    missing = []
    if not config.user:
        missing.append("user")
    if not config.client_id:
        missing.append("clientid/TWITCH_CLIENT_ID")
    if not config.client_secret:
        missing.append("clientsecret/TWITCH_CLIENT_SECRET")
    if missing:
        parser.error(f"missing required configuration: {', '.join(missing)}")

    return config

def main():
    config = parse_arguments()
    logger.info(f"Checking for {config.user} every {config.timer} seconds. Record with {config.quality} quality.")
    loop_check(config)

if __name__ == "__main__":
    main()
