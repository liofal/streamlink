import logging
import os
import streamlink
from streamlink.options import Options
import shutil
import signal
import time
from contextlib import contextmanager
from enum import Enum, auto

logger = logging.getLogger(__name__)

INCOMPLETE_SUFFIX = ".incomplete"

# Liveness heartbeat: the Helm chart's exec probe restarts the pod when this file
# is older than its threshold (default max(timer, 600) + 300 seconds). The loop
# beats every iteration and the recording beats every HEARTBEAT_INTERVAL_SECONDS.
HEARTBEAT_FILE = "/tmp/streamlink-recorder.heartbeat"
HEARTBEAT_INTERVAL_SECONDS = 30


def beat():
    """Touch the heartbeat file. Never raises: a missing /tmp must not stop the recorder."""
    try:
        with open(HEARTBEAT_FILE, "a"):
            pass
        os.utime(HEARTBEAT_FILE)
    except OSError:
        pass


class NoStreamsAvailable(Exception):
    """Twitch reports the channel live but streamlink found no playable stream yet."""


class StopRequested(KeyboardInterrupt):
    """Raised by the signal handler to unwind the recorder.

    A KeyboardInterrupt subclass so `except Exception` blocks don't swallow it
    and asyncio (Handle._run, Task.__step) re-raises it instead of logging it.
    """


_state = {"signum": None, "shield": 0, "pending": False}


def _handle_stop_signal(signum, frame):
    _state["signum"] = signum
    if _state["shield"]:
        _state["pending"] = True
        return
    raise StopRequested(signum)


def stop_requested():
    """True once a stop signal has arrived (even if its exception was swallowed)."""
    return _state["signum"] is not None


@contextmanager
def _shielded():
    """Defer a stop signal until the block is done (e.g. while renaming a recording)."""
    _state["shield"] += 1
    try:
        yield
    finally:
        _state["shield"] -= 1
    if not _state["shield"] and _state["pending"]:
        _state["pending"] = False
        raise StopRequested(_state["signum"])


def install_signal_handlers():
    """Install SIGTERM/SIGINT handlers once, from the main thread."""
    _state.update(signum=None, shield=0, pending=False)
    signal.signal(signal.SIGTERM, _handle_stop_signal)
    signal.signal(signal.SIGINT, _handle_stop_signal)


class AuthValidationStatus(Enum):
    NOT_CONFIGURED = auto()
    VALID_OR_NOT_REJECTED = auto()
    INVALID = auto()
    UNKNOWN = auto()


def select_quality(preferences, streams):
    """Return the first preferred quality present in streams, else "best".

    preferences is a comma-separated fallback list such as "720p60,720p,best".
    """
    if isinstance(preferences, str):
        for entry in preferences.split(","):
            entry = entry.strip()
            if entry and entry in streams:
                return entry
    return "best"


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

    def finalize(self, fd, temp_filename, final_filename, complete):
        """Close the stream and settle the output file. Call after the output file is closed.

        complete: rename to the final name. Otherwise keep the data under
        "<final>.incomplete" (ignored by the ffmpeg sidecar, which globs *.ts),
        or drop the file if nothing was written.
        """
        with _shielded():
            try:
                fd.close()
            except Exception as error:
                logger.warning("Closing stream failed: %s", type(error).__name__)
            if not os.path.exists(temp_filename):
                return
            if complete:
                shutil.move(temp_filename, final_filename)
            elif os.path.getsize(temp_filename) == 0:
                os.remove(temp_filename)
            else:
                shutil.move(temp_filename, f"{final_filename}{INCOMPLETE_SUFFIX}")

    def run_streamlink(self, user, recorded_filename, on_start=None):
        """Record until the stream ends. on_start() is called once the stream is open."""
        session = self.create_session()
        streams = session.streams(f"twitch.tv/{user}", options=self.plugin_options())
        if not streams:
            raise NoStreamsAvailable
        quality = select_quality(self.config.quality, streams)
        stream = streams[quality]
        extension = self.get_stream_extension(stream)
        temp_filename = f"{recorded_filename}.part"
        final_filename = f"{recorded_filename}.{extension}"

        fd = stream.open()
        complete = False
        try:
            try:
                if on_start is not None:
                    on_start()
                with open(temp_filename, 'wb') as f:
                    last_beat = time.monotonic()
                    while True:
                        data = fd.read(1024)
                        if not data:
                            break
                        f.write(data)
                        if time.monotonic() - last_beat >= HEARTBEAT_INTERVAL_SECONDS:
                            beat()
                            last_beat = time.monotonic()
                complete = True
            except StopRequested:
                # Shutdown: the data written so far is a valid recording.
                complete = True
                raise
        finally:
            # The output file is closed here; any other exception leaves complete False.
            # A stop signal can land after the body exits but before finalize()
            # enters its shield; finalize is idempotent, so retry until it ran.
            stop = None
            while True:
                try:
                    self.finalize(fd, temp_filename, final_filename, complete)
                    break
                except StopRequested as error:
                    stop = error
            if stop is not None:
                raise stop

    def create_session(self):
        # No retry options here: retry-max/retry-streams are streamlink_cli-only and
        # the library ignores them. Start retries are handled by the recorder loop.
        return streamlink.Streamlink()

    def plugin_options(self):
        """Options for the Twitch plugin, or None without a token.

        The token goes in the plugin's api-header option, so it is only sent on Twitch
        API (GQL) requests. A session-wide http-headers option would also send it to
        the HLS/CDN hosts.
        """
        token = self.config.oauth_token
        if not token:
            return None
        return Options({"api-header": [("Authorization", f"OAuth {token}")]})

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
        try:
            session.streams(f"twitch.tv/{user}", options=self.plugin_options())
            return AuthValidationStatus.VALID_OR_NOT_REJECTED
        except Exception as error:
            if self.is_invalid_twitch_auth_error(error):
                return AuthValidationStatus.INVALID
            logger.warning("Unable to validate Twitch auth token: %s", type(error).__name__)
            return AuthValidationStatus.UNKNOWN
