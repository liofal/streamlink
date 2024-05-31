import os
import streamlink

class StreamlinkManager:
    def __init__(self, config):
        self.config = config

    def run_streamlink(self, user, recorded_filename):
        session = streamlink.Streamlink()
        session.set_option("twitch-disable-hosting", True)
        session.set_option("twitch-disable-ads", True)
        session.set_option("retry-max", 5)
        session.set_option("retry-streams", 60)

        if self.config.oauth_token:
            session.set_option("http-headers", f"Authorization=OAuth {self.config.oauth_token}")
        quality = self.config.quality
        streams = session.streams(f"twitch.tv/{user}")
        if quality not in streams:
            quality = "best"
        stream = streams[quality]
        fd = stream.open()
        with open(recorded_filename, 'wb') as f:
            while True:
                data = fd.read(1024)
                if not data:
                    break
                f.write(data)
        fd.close()
