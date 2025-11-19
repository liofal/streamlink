
import unittest
from unittest.mock import MagicMock, patch
from streamlink_manager import StreamlinkManager

class TestStreamlinkManager(unittest.TestCase):
    def setUp(self):
        self.config = MagicMock()
        self.config.oauth_token = "test_token"
        self.config.quality = "best"
        self.manager = StreamlinkManager(self.config)

    def test_get_stream_extension_with_url_attr(self):
        # Mock stream with .url (Streamlink 8.0.0 style)
        stream = MagicMock()
        stream.url = "http://example.com/playlist.m3u8"
        del stream.to_manifest_url # Ensure this doesn't exist
        
        ext = self.manager.get_stream_extension(stream)
        self.assertEqual(ext, "ts")

    def test_get_stream_extension_with_mp4(self):
        # Mock stream with .url but not m3u8
        stream = MagicMock()
        stream.url = "http://example.com/video.mp4"
        del stream.to_manifest_url 
        
        ext = self.manager.get_stream_extension(stream)
        self.assertEqual(ext, "mp4")

    def test_get_stream_extension_legacy_fallback(self):
        # Mock stream with to_manifest_url (Legacy style)
        stream = MagicMock()
        del stream.url # Ensure .url doesn't exist (or at least check priority)
        stream.to_manifest_url.return_value = "http://example.com/playlist.m3u8"
        
        ext = self.manager.get_stream_extension(stream)
        self.assertEqual(ext, "ts")

    @patch('streamlink_manager.streamlink.Streamlink')
    def test_run_streamlink_initialization(self, mock_streamlink_cls):
        mock_session = mock_streamlink_cls.return_value
        mock_streams = MagicMock()
        mock_session.streams.return_value = mock_streams
        
        # We mock streams["best"] to return a stream that has .url
        mock_stream = MagicMock()
        mock_stream.url = "http://example.com/playlist.m3u8"
        mock_streams.__getitem__.return_value = mock_stream
        
        # Mock open() to return a file-like object so it enters the read loop
        mock_fd = MagicMock()
        mock_fd.read.side_effect = [b'data', b''] # Read once then EOF
        mock_stream.open.return_value = mock_fd

        # We need to mock open() built-in to avoid writing to disk
        with patch('builtins.open', unittest.mock.mock_open()) as mock_file:
             self.manager.run_streamlink("testuser", "testfile")

        # Verify deprecated options are NOT called
        # set_option is called for retry-max, retry-streams, http-headers
        # We want to ensure "twitch-disable-ads" and "twitch-disable-hosting" are NOT called
        
        calls = mock_session.set_option.call_args_list
        args_list = [call[0][0] for call in calls]
        
        self.assertNotIn("twitch-disable-ads", args_list)
        self.assertNotIn("twitch-disable-hosting", args_list)
        self.assertIn("retry-max", args_list)
        self.assertIn("retry-streams", args_list)
        self.assertIn("http-headers", args_list)

if __name__ == '__main__':
    unittest.main()
