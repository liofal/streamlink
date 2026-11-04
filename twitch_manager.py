import asyncio
import logging
import re
from twitchAPI.twitch import Twitch
from twitchAPI.helper import first
from twitchAPI.type import TwitchAuthorizationException
from enum import Enum, auto

logger = logging.getLogger(__name__)

# Upper bound for one Twitch call (client creation included), so a stuck call cannot hang the recorder.
TWITCH_CALL_TIMEOUT = 30

_AUTH_STATUS_RE = re.compile(r"Authentication failed with code (\d{3})\b")


def _twitch_error_summary(exc):
    """Describe a Twitch error without its message, which can embed the client secret."""
    summary = type(exc).__name__
    if isinstance(exc, TwitchAuthorizationException):
        match = _AUTH_STATUS_RE.match(str(exc))
        if match:
            summary += f" (HTTP {match.group(1)})"
    return summary

def parse_game_list(value):
    """Split a comma-separated game id list, stripping blanks and dropping empty entries."""
    return [game.strip() for game in (value or "").split(",") if game.strip()]


class StreamStatus(Enum):
    ONLINE = auto()
    UNDESIRED_GAME = auto()
    OFFLINE = auto()
    ERROR = auto()

class TwitchManager:
    def __init__(self, config):
        self.config = config
        self.twitch = None

    async def app_refresh(self, token: str):
        logger.info("Twitch app token refreshed")

    async def _call_twitch(self, operation, **kwargs):
        if self.twitch is None:
            self.twitch = await Twitch(self.config.client_id, self.config.client_secret)
            self.twitch.app_auth_refresh_callback = self.app_refresh

        return await first(getattr(self.twitch, operation)(**kwargs))

    async def get_from_twitch_async(self, operation, **kwargs):
        try:
            return await asyncio.wait_for(self._call_twitch(operation, **kwargs), TWITCH_CALL_TIMEOUT)
        except BaseException:
            # twitchAPI leaves its app-token refresh lock set when a refresh fails, which would
            # hang every later call on this instance, so always rebuild the client after a failure.
            self.twitch = None
            raise

    def get_from_twitch(self, operation, **kwargs):
        return asyncio.run(self.get_from_twitch_async(operation, **kwargs))

    def check_user(self, user):
        try:
            # Known limitation: twitchAPI waits out a Helix 429 and then returns an empty
            # result without exposing the status, so a rate-limited poll reads as OFFLINE.
            user_info = self.get_from_twitch('get_users', logins=user)
            if not user_info:
                return StreamStatus.OFFLINE, ""

            stream_info = self.get_from_twitch('get_streams', user_id=user_info.id)
            if not stream_info:
                return StreamStatus.OFFLINE, ""

            game_id, title = stream_info.game_id, stream_info.title
            games = parse_game_list(self.config.game_list)
            if games and game_id not in games:
                return StreamStatus.UNDESIRED_GAME, title

            return StreamStatus.ONLINE, title
        except Exception as e:
            logger.error("An unexpected error occurred while checking user status: %s", _twitch_error_summary(e))
            return StreamStatus.ERROR, ""
