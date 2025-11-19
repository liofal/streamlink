import os
import streamlink
import shutil
import signal
import sys

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
        session = streamlink.Streamlink()
        session.set_option("retry-max", 5)
        session.set_option("retry-streams", 60)

        if self.config.oauth_token:
            session.set_option("http-headers", f"Authorization=OAuth {self.config.oauth_token}")
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
