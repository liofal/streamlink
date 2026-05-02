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
from dataclasses import dataclass

from twitch_manager import TwitchManager, StreamStatus
from streamlink_manager import AuthValidationStatus, StreamlinkManager
from notification_manager import NotificationManager

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

class AppConfig:
    def __init__(
        self,
        timer,
        user,
        quality,
        client_id,
        client_secret,
        game_list,
        slack_id,
        telegram_bot_token,
        telegram_chat_id,
        oauth_token,
        auth_invalid_policy,
        auth_validation_interval,
    ):
        self.timer = timer
        self.user = user
        self.quality = quality
        self.client_id = client_id
        self.client_secret = client_secret
        self.game_list = game_list
        self.slack_id = slack_id
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.oauth_token = oauth_token
        self.auth_invalid_policy = auth_invalid_policy
        self.auth_validation_interval = auth_validation_interval


def first_config_value(cli_value, env_names, default=None):
    if cli_value not in (None, ""):
        return cli_value

    for env_name in env_names:
        env_value = os.environ.get(env_name)
        if env_value not in (None, ""):
            return env_value

    return default


def require_config(parser, value, field_name, cli_arg, env_names):
    if value not in (None, ""):
        return value

    env_hint = ", ".join(env_names)
    parser.error(f"Missing required configuration: {field_name} (set {cli_arg}, {env_hint})")


def parse_timer_value(parser, value):
    try:
        return int(value)
    except (TypeError, ValueError):
        parser.error("Invalid integer for timer; set -timer/TIMER to a whole number")


def parse_auth_validation_interval(parser, value):
    try:
        return int(value)
    except (TypeError, ValueError):
        parser.error("Invalid integer for auth validation interval; set -authvalidationinterval/TWITCH_AUTH_VALIDATION_INTERVAL to a whole number")


def parse_auth_invalid_policy(parser, value):
    policy = str(value).lower()
    if policy not in ("exit", "notify"):
        parser.error("Invalid auth invalid token policy; expected exit or notify")
    return policy


@dataclass
class RecorderState:
    auth_status: AuthValidationStatus = AuthValidationStatus.NOT_CONFIGURED
    last_auth_validation_time: float = 0
    invalid_auth_notified: bool = False


def invalid_auth_message(config):
    return f"Twitch playback auth token is invalid for {config.user}. Renew oauthtoken/TWITCH_AUTH_TOKEN and restart the recorder."


def apply_invalid_auth_policy(config, notifier_manager, state):
    message = invalid_auth_message(config)
    logger.error(message)
    if not state.invalid_auth_notified:
        notifier_manager.notify_all(message)
        state.invalid_auth_notified = True
    state.auth_status = AuthValidationStatus.INVALID
    if config.auth_invalid_policy == "exit":
        raise SystemExit(1)
    return state


def validate_auth_or_apply_policy(config, streamlink_manager, notifier_manager, state=None, force_notify=False):
    state = state or RecorderState()
    status = streamlink_manager.validate_oauth_token(config.user)
    state.last_auth_validation_time = time.time()

    if status == AuthValidationStatus.INVALID:
        if force_notify:
            state.invalid_auth_notified = False
        return apply_invalid_auth_policy(config, notifier_manager, state)

    if status == AuthValidationStatus.VALID_OR_NOT_REJECTED:
        if state.invalid_auth_notified:
            notifier_manager.notify_all(f"Twitch playback auth token validation recovered for {config.user}. Recording is enabled again.")
        state.invalid_auth_notified = False
        state.auth_status = status
        return state

    if status == AuthValidationStatus.UNKNOWN:
        logger.warning("Unable to validate Twitch playback auth token for %s; will retry later", config.user)
        if state.auth_status != AuthValidationStatus.INVALID:
            state.auth_status = status
        return state

    state.auth_status = status
    return state


def should_validate_auth(config, state):
    if not config.oauth_token:
        return False
    return time.time() - state.last_auth_validation_time >= config.auth_validation_interval


def should_attempt_recording(config, state):
    return not (config.auth_invalid_policy == "notify" and state.auth_status == AuthValidationStatus.INVALID)


def handle_recording_error(config, streamlink_manager, notifier_manager, error, state=None):
    state = state or RecorderState()
    if streamlink_manager.is_invalid_twitch_auth_error(error):
        return apply_invalid_auth_policy(config, notifier_manager, state)

    message = f"Recording {config.user} failed: {type(error).__name__}. Recorder will continue checking."
    logger.error(message)
    notifier_manager.notify_all(message)
    return state


def loop_check(config):
    twitch_manager = TwitchManager(config)
    streamlink_manager = StreamlinkManager(config)
    notifier_manager = NotificationManager(config)

    state = validate_auth_or_apply_policy(config, streamlink_manager, notifier_manager, force_notify=True)

    while True:
        if should_validate_auth(config, state):
            state = validate_auth_or_apply_policy(config, streamlink_manager, notifier_manager, state=state)
        stream_status, title = twitch_manager.check_user(config.user)
        if stream_status == StreamStatus.ONLINE:
            if not should_attempt_recording(config, state):
                logger.error("Skipping recording for %s because Twitch playback auth token is invalid", config.user)
                time.sleep(config.timer)
                continue
            safe_title = re.sub(r"[^\w\s._-]|[<>:\"/\\|?*]", "", title)
            safe_title = os.path.basename(safe_title)
            filename = f"{config.user} - {datetime.datetime.now().strftime('%Y-%m-%d %H-%M-%S')} - {safe_title}"
            recorded_filename = os.path.join("./download/", filename)
            message = f"Recording {config.user} ..."
            notifier_manager.notify_all(message)
            logger.info(message)
            try:
                streamlink_manager.run_streamlink(config.user, recorded_filename)
            except Exception as error:
                state = handle_recording_error(config, streamlink_manager, notifier_manager, error, state=state)
                time.sleep(config.timer)
                continue
            message = f"Stream {config.user} is done. File saved as {filename}. Going back to checking.."
            logger.info(message)
            notifier_manager.notify_all(message)
        time.sleep(config.timer)

def parse_arguments(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("-timer", help="Stream check interval (less than 15s are not recommended)")
    parser.add_argument("-user", help="Twitch user that we are checking")
    parser.add_argument("-quality", help="Recording quality")
    parser.add_argument("-clientid", help="Your Twitch app client id")
    parser.add_argument("-clientsecret", help="Your Twitch app client secret")
    parser.add_argument("-slackid", help="Your slack app client id")
    parser.add_argument("-gamelist", help="The game list to be recorded")
    parser.add_argument("-telegrambottoken", help="Your Telegram bot token")
    parser.add_argument("-telegramchatid", help="Your Telegram chat ID where the bot will send messages")
    parser.add_argument("-oauthtoken", help="Your OAuth token for Twitch API")
    parser.add_argument("-authinvalidpolicy", help="What to do when Twitch playback auth token is invalid: exit or notify")
    parser.add_argument("-authvalidationinterval", help="Seconds between Twitch playback auth token validation checks")
    args = parser.parse_args(argv)

    user = require_config(
        parser,
        first_config_value(args.user, ("TWITCH_USER", "user")),
        "user",
        "-user",
        ("TWITCH_USER", "user"),
    )
    client_id = require_config(
        parser,
        first_config_value(args.clientid, ("TWITCH_CLIENT_ID", "clientid")),
        "clientid",
        "-clientid",
        ("TWITCH_CLIENT_ID", "clientid"),
    )
    client_secret = require_config(
        parser,
        first_config_value(args.clientsecret, ("TWITCH_CLIENT_SECRET", "clientsecret")),
        "clientsecret",
        "-clientsecret",
        ("TWITCH_CLIENT_SECRET", "clientsecret"),
    )

    timer = parse_timer_value(parser, first_config_value(args.timer, ("TIMER", "timer"), 240))

    auth_invalid_policy = parse_auth_invalid_policy(
        parser,
        first_config_value(args.authinvalidpolicy, ("TWITCH_AUTH_INVALID_TOKEN_POLICY", "authinvalidpolicy"), "exit"),
    )
    auth_validation_interval = parse_auth_validation_interval(
        parser,
        first_config_value(args.authvalidationinterval, ("TWITCH_AUTH_VALIDATION_INTERVAL", "authvalidationinterval"), 3600),
    )

    return AppConfig(
        timer=timer,
        user=user,
        quality=first_config_value(args.quality, ("STREAM_QUALITY", "quality"), "720p60,720p,best"),
        client_id=client_id,
        client_secret=client_secret,
        game_list=first_config_value(args.gamelist, ("GAME_LIST", "gamelist"), ""),
        slack_id=first_config_value(args.slackid, ("SLACK_ID", "slackid")),
        telegram_bot_token=first_config_value(args.telegrambottoken, ("TELEGRAM_BOT_TOKEN", "telegrambottoken")),
        telegram_chat_id=first_config_value(args.telegramchatid, ("TELEGRAM_CHAT_ID", "telegramchatid")),
        oauth_token=first_config_value(args.oauthtoken, ("TWITCH_AUTH_TOKEN", "TWITCH_OAUTH_TOKEN", "oauthtoken")),
        auth_invalid_policy=auth_invalid_policy,
        auth_validation_interval=auth_validation_interval,
    )

def main():
    config = parse_arguments()
    logger.info(f"Checking for {config.user} every {config.timer} seconds. Record with {config.quality} quality.")
    loop_check(config)

if __name__ == "__main__":
    main()
