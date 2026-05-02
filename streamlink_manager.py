import logging
import os
import streamlink
import shutil
import signal
import sys
from enum import Enum, auto

logger = logging.getLogger(__name__)


class AuthValidationStatus(Enum):
    NOT_CONFIGURED = auto()
    VALID_OR_NOT_REJECTED = auto()
    INVALID = auto()
    UNKNOWN = auto()


class StreamlinkManager:
    def __init__(self, config):
        self.config = config

    M3U8_EXTENSIONS = ['m3u8']

    def get_stream_extension(self, stream):
        # In Streamlink 8.x, to_manifest_url is removed and .url should be used.
        # We check for .url first, or fall back to legacy behavior if needed.
        if hasattr(stream, 'url'):
            url = stream.url
            file_extension = url.split('?')[0].split('.')[-1]
            if file_extension in self.M3U8_EXTENSIONS:
                return 'ts'
        
        if hasattr(stream, 'to_manifest_url'):
            url = stream.to_manifest_url()
            file_extension = url.split('?')[0].split('.')[-1]
            if file_extension in self.M3U8_EXTENSIONS:
                return 'ts'
        
        return 'mp4'

    def cleanup(self, fd, temp_filename, final_filename, *args):
        """
        Cleanup function to close the file descriptor and move the temporary file
        to its final destination.
        """
        fd.close()
        if os.path.exists(temp_filename):
            shutil.move(temp_filename, final_filename)

    def run_streamlink(self, user, recorded_filename):
        session = self.create_session()
        self.configure_session_auth(session)
        quality = self.config.quality
        streams = session.streams(f"twitch.tv/{user}")
        if quality not in streams:
            quality = "best"
        stream = streams[quality]
        extension = self.get_stream_extension(stream)
        temp_filename = f"{recorded_filename}.part"
        final_filename = f"{recorded_filename}.{extension}"
        
        # Open the stream
        fd = stream.open()

        # Register signal handlers for SIGTERM and SIGINT to ensure cleanup
        signal.signal(signal.SIGTERM, lambda *args: self.cleanup(fd, temp_filename, final_filename, *args))
        signal.signal(signal.SIGINT, lambda *args: self.cleanup(fd, temp_filename, final_filename, *args))

        try:
            with open(temp_filename, 'wb') as f:
                while True:
                    data = fd.read(1024)
                    if not data:
                        break
                    f.write(data)
        finally:
            # Ensure cleanup is called when the try block exits
            self.cleanup(fd, temp_filename, final_filename)

    def create_session(self):
        session = streamlink.Streamlink()
        session.set_option("retry-max", 5)
        session.set_option("retry-streams", 60)
        return session

    def configure_session_auth(self, session, oauth_token=None):
        token = self.config.oauth_token if oauth_token is None else oauth_token
        if token:
            session.set_option("http-headers", f"Authorization=OAuth {token}")

    def is_invalid_twitch_auth_error(self, error):
        message = str(error)
        return (
            "Authorization" in message
            and "token" in message.lower()
            and any(fragment in message.lower() for fragment in ("invalid", "unauthorized"))
        )

    def validate_oauth_token(self, user):
        if not self.config.oauth_token:
            return AuthValidationStatus.NOT_CONFIGURED

        session = self.create_session()
        self.configure_session_auth(session)
        try:
            session.streams(f"twitch.tv/{user}")
            return AuthValidationStatus.VALID_OR_NOT_REJECTED
        except Exception as error:
            if self.is_invalid_twitch_auth_error(error):
                return AuthValidationStatus.INVALID
            logger.warning("Unable to validate Twitch auth token: %s", type(error).__name__)
            return AuthValidationStatus.UNKNOWN
