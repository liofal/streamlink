import asyncio
import logging
from twitchAPI.twitch import Twitch
from twitchAPI.helper import first
from enum import Enum, auto

logger = logging.getLogger(__name__)

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
        logger.info(f'my new app token is: {token}')

    async def get_from_twitch_async(self, operation, **kwargs):
        if self.twitch is None:
            self.twitch = await Twitch(self.config.client_id, self.config.client_secret)
            self.twitch.app_auth_refresh_callback = self.app_refresh

        result = await first(getattr(self.twitch, operation)(**kwargs))
        return result

    def get_from_twitch(self, operation, **kwargs):
        return asyncio.run(self.get_from_twitch_async(operation, **kwargs))

    def check_user(self, user):
        try:
            user_info = self.get_from_twitch('get_users', logins=user)
            if not user_info:
                return StreamStatus.OFFLINE, ""

            stream_info = self.get_from_twitch('get_streams', user_id=user_info.id)
            if not stream_info:
                return StreamStatus.OFFLINE, ""

            game_id, title = stream_info.game_id, stream_info.title
            if self.config.game_list and game_id not in self.config.game_list.split(","):
                return StreamStatus.UNDESIRED_GAME, title

            return StreamStatus.ONLINE, title
        except Exception as e:
            logger.error(f"An unexpected error occurred while checking user status: {e}")
            return StreamStatus.ERROR, ""
