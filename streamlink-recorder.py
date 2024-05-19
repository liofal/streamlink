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

class AppConfig:
    def __init__(self, args):
        self.timer = args.timer
        self.user = args.user
        self.quality = args.quality
        self.client_id = args.clientid
        self.client_secret = args.clientsecret
        self.game_list = args.gamelist
        self.slack_id = args.slackid
        self.telegram_bot_token = args.telegrambottoken
        self.telegram_chat_id = args.telegramchatid

def loop_check(config):
    twitch_manager = TwitchManager(config)
    streamlink_manager = StreamlinkManager(config)
    notifier_manager = NotificationManager(config)

    while True:
        stream_status, title = twitch_manager.check_user(config.user)
        if stream_status == StreamStatus.ONLINE:
            safe_title = re.sub(r"[^\w\s._:-]", "", title)
            safe_title = os.path.basename(safe_title)
            filename = f"{config.user} - {datetime.datetime.now().strftime('%Y-%m-%d %H-%M-%S')} - {safe_title}.mp4"
            recorded_filename = os.path.join("./download/", filename)
            message = f"Recording {config.user} ..."
            notifier_manager.notify_all(message)
            logger.info(message)
            streamlink_manager.run_streamlink(config.user, recorded_filename)
            message = f"Stream {config.user} is done. File saved as {filename}. Going back to checking.."
            logger.info(message)
            notifier_manager.notify_all(message)
        time.sleep(config.timer)

def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("-timer", type=int, default=240, help="Stream check interval (less than 15s are not recommended)")
    parser.add_argument("-user", required=True, help="Twitch user that we are checking")
    parser.add_argument("-quality", default="720p60,720p,best", help="Recording quality")
    parser.add_argument("-clientid", required=True, help="Your Twitch app client id")
    parser.add_argument("-clientsecret", required=True, help="Your Twitch app client secret")
    parser.add_argument("-slackid", help="Your slack app client id")
    parser.add_argument("-gamelist", default="", help="The game list to be recorded")
    parser.add_argument("-telegrambottoken", help="Your Telegram bot token")
    parser.add_argument("-telegramchatid", help="Your Telegram chat ID where the bot will send messages")
    args = parser.parse_args()

    return AppConfig(args)

def main():
    config = parse_arguments()
    logger.info(f"Checking for {config.user} every {config.timer} seconds. Record with {config.quality} quality.")
    loop_check(config)

if __name__ == "__main__":
    main()
