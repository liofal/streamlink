"""
This script checks if a user on twitch is currently streaming and 
then records the stream via streamlink
"""
import datetime
import argparse
import os
import re
import time
import unicodedata
import logging
import sys
from dataclasses import dataclass

from twitch_manager import TwitchManager, StreamStatus
from streamlink_manager import AuthValidationStatus, StopRequested, StreamlinkManager, install_signal_handlers, stop_requested
from notification_manager import NotificationManager

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_TWITCH_ERROR_THRESHOLD = 5
MAX_ERROR_BACKOFF_SECONDS = 600


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
        twitch_error_threshold=DEFAULT_TWITCH_ERROR_THRESHOLD,
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
        self.twitch_error_threshold = twitch_error_threshold


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


def parse_twitch_error_threshold(parser, value):
    try:
        return int(value)
    except (TypeError, ValueError):
        parser.error("Invalid integer for Twitch error threshold; set -twitcherrorthreshold/TWITCH_ERROR_NOTIFY_THRESHOLD to a whole number")


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
    consecutive_twitch_errors: int = 0
    twitch_errors_notified: bool = False


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


def error_backoff_seconds(timer, consecutive_errors):
    """Sleep time after a Twitch ERROR: the timer for the first one, doubling up to a cap."""
    cap = max(timer, MAX_ERROR_BACKOFF_SECONDS)
    return min(timer * 2 ** max(consecutive_errors - 1, 0), cap)


def track_twitch_status(config, notifier_manager, stream_status, state):
    if stream_status == StreamStatus.ERROR:
        state.consecutive_twitch_errors += 1
        if state.consecutive_twitch_errors >= config.twitch_error_threshold and not state.twitch_errors_notified:
            notifier_manager.notify_all(
                f"Twitch API checks for {config.user} have failed {state.consecutive_twitch_errors} times in a row. "
                "Recordings may be missed. Check the Twitch client id/secret and Twitch status."
            )
            state.twitch_errors_notified = True
        return state

    if state.twitch_errors_notified:
        notifier_manager.notify_all(f"Twitch API checks for {config.user} recovered. Stream checks are working again.")
    state.consecutive_twitch_errors = 0
    state.twitch_errors_notified = False
    return state


NAME_MAX_BYTES = 255
# run_streamlink appends ".part" (5 bytes) or ".<ext>" (ts/mp4/m3u8-family); keep spare room.
SUFFIX_RESERVE = 16
MAX_USER_CHARS = 25  # Twitch login limit
_RESERVED_CHARS = re.compile(r'[<>:"/\\|?*]')


def _truncate_utf8(text, max_bytes):
    """Cut text to at most max_bytes UTF-8 bytes without splitting a character."""
    if max_bytes <= 0:
        return ""
    return text.encode("utf-8")[:max_bytes].decode("utf-8", "ignore")


def _sanitize_component(text):
    """Make text safe as part of a filename.

    Order matters: reserved path characters are replaced with "_" first, then
    anything outside [\\w\\s._-] is removed, then control/format characters are
    dropped and whitespace runs (incl. newlines) collapse to one space.
    """
    text = unicodedata.normalize("NFC", text or "")
    text = _RESERVED_CHARS.sub("_", text)
    text = re.sub(r"[^\w\s._-]", "", text)
    text = "".join(c for c in text if c.isspace() or not unicodedata.category(c).startswith("C"))
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .")


def _sanitize_user(user):
    """Reduce user to the Twitch login charset [A-Za-z0-9_], max 25 chars, else "unknown"."""
    text = re.sub(r"[^A-Za-z0-9_]+", "_", user or "")
    text = re.sub(r"_+", "_", text).strip("_")[:MAX_USER_CHARS].strip("_")
    return text or "unknown"


def build_recording_basename(user, title, now):
    """Return "<user> - <YYYY-mm-dd HH-MM-SS> - <title>", capped for the filesystem."""
    budget = NAME_MAX_BYTES - SUFFIX_RESERVE
    safe_user = _sanitize_user(user)
    prefix = f"{safe_user} - {now.strftime('%Y-%m-%d %H-%M-%S')}"
    title_budget = budget - len(prefix.encode("utf-8")) - len(" - ")
    safe_title = _truncate_utf8(_sanitize_component(title), title_budget).strip(" .")
    return f"{prefix} - {safe_title}" if safe_title else prefix


def loop_check(config):
    twitch_manager = TwitchManager(config)
    streamlink_manager = StreamlinkManager(config)
    notifier_manager = NotificationManager(config)

    state = validate_auth_or_apply_policy(config, streamlink_manager, notifier_manager, force_notify=True)

    while True:
        if stop_requested():
            raise StopRequested()  # a stop whose exception was swallowed upstream
        if should_validate_auth(config, state):
            state = validate_auth_or_apply_policy(config, streamlink_manager, notifier_manager, state=state)
        stream_status, title = twitch_manager.check_user(config.user)
        state = track_twitch_status(config, notifier_manager, stream_status, state)
        if stream_status == StreamStatus.ERROR:
            time.sleep(error_backoff_seconds(config.timer, state.consecutive_twitch_errors))
            continue
        if stream_status == StreamStatus.ONLINE:
            if not should_attempt_recording(config, state):
                logger.error("Skipping recording for %s because Twitch playback auth token is invalid", config.user)
                time.sleep(config.timer)
                continue
            filename = build_recording_basename(config.user, title, datetime.datetime.now())
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
    parser.add_argument("-twitcherrorthreshold", help="Consecutive Twitch API failures before a notification is sent")
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

    twitch_error_threshold = parse_twitch_error_threshold(
        parser,
        first_config_value(args.twitcherrorthreshold, ("TWITCH_ERROR_NOTIFY_THRESHOLD", "twitcherrorthreshold"), DEFAULT_TWITCH_ERROR_THRESHOLD),
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
        twitch_error_threshold=twitch_error_threshold,
    )

def main():
    config = parse_arguments()
    logger.info(f"Checking for {config.user} every {config.timer} seconds. Record with {config.quality} quality.")
    install_signal_handlers()
    try:
        loop_check(config)
    except StopRequested:
        logger.info("Stop requested, exiting.")

if __name__ == "__main__":
    main()
