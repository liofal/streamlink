
import unittest
from unittest.mock import MagicMock, patch
import streamlink_manager
from streamlink_manager import AuthValidationStatus, StreamlinkManager

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
        self.assertNotIn("retry-max", args_list)
        self.assertNotIn("retry-streams", args_list)
        self.assertNotIn("http-headers", args_list)

    @patch('streamlink_manager.streamlink.Streamlink')
    def test_run_streamlink_passes_token_as_api_header_only(self, mock_streamlink_cls):
        mock_session = mock_streamlink_cls.return_value
        mock_session.streams.return_value = {}
        with self.assertRaises(streamlink_manager.NoStreamsAvailable):
            self.manager.run_streamlink("testuser", "testfile")
        kwargs = mock_session.streams.call_args.kwargs
        self.assertEqual(kwargs["options"].get("api-header"), [("Authorization", "OAuth test_token")])
        self.assertNotIn("http-headers", [c[0][0] for c in mock_session.set_option.call_args_list])

    def test_plugin_options_none_without_token(self):
        self.config.oauth_token = None
        self.assertIsNone(self.manager.plugin_options())

    def test_real_twitch_plugin_sends_token_only_in_api_headers(self):
        import streamlink
        session = streamlink.Streamlink()
        _, plugin_cls, url = session.resolve_url("twitch.tv/testuser")
        plugin = plugin_cls(session, url, self.manager.plugin_options())
        self.assertEqual(plugin.api.headers["Authorization"], "OAuth test_token")
        self.assertNotIn("Authorization", session.http.headers)

    @patch('streamlink_manager.streamlink.Streamlink')
    def test_empty_streams_raise_no_streams_available_without_file(self, mock_streamlink_cls):
        mock_streamlink_cls.return_value.streams.return_value = {}
        on_start = MagicMock()
        with patch('builtins.open', unittest.mock.mock_open()) as mock_file:
            with self.assertRaises(streamlink_manager.NoStreamsAvailable):
                self.manager.run_streamlink("testuser", "testfile", on_start=on_start)
        mock_file.assert_not_called()
        on_start.assert_not_called()

    @patch('streamlink_manager.streamlink.Streamlink')
    def test_on_start_called_after_stream_opens(self, mock_streamlink_cls):
        stream = MagicMock(url="http://example.com/playlist.m3u8")
        fd = MagicMock()
        fd.read.side_effect = [b'data', b'']
        stream.open.return_value = fd
        mock_streamlink_cls.return_value.streams.return_value = {"best": stream}
        order = []
        stream.open.side_effect = lambda: order.append("open") or fd
        with patch('builtins.open', unittest.mock.mock_open()), patch('streamlink_manager.shutil.move'), \
                patch('streamlink_manager.os.path.exists', return_value=True):
            self.manager.run_streamlink("testuser", "testfile", on_start=lambda: order.append("start"))
        self.assertEqual(order, ["open", "start"])

    def test_is_invalid_twitch_auth_error_detects_authorization_token_error(self):
        error = Exception('Unauthorized: The "Authorization" token is invalid.')

        self.assertTrue(self.manager.is_invalid_twitch_auth_error(error))

    def test_is_invalid_twitch_auth_error_ignores_unrelated_errors(self):
        error = Exception("Network timeout while opening stream")

        self.assertFalse(self.manager.is_invalid_twitch_auth_error(error))

    def test_validate_oauth_token_not_configured(self):
        self.config.oauth_token = None

        status = self.manager.validate_oauth_token("testuser")

        self.assertEqual(status, AuthValidationStatus.NOT_CONFIGURED)

    @patch('streamlink_manager.streamlink.Streamlink')
    def test_validate_oauth_token_valid_or_not_rejected(self, mock_streamlink_cls):
        mock_session = mock_streamlink_cls.return_value
        mock_session.streams.return_value = {}

        status = self.manager.validate_oauth_token("testuser")

        self.assertEqual(status, AuthValidationStatus.VALID_OR_NOT_REJECTED)
        args, kwargs = mock_session.streams.call_args
        self.assertEqual(args, ("twitch.tv/testuser",))
        self.assertEqual(kwargs["options"].get("api-header"), [("Authorization", "OAuth test_token")])

    @patch('streamlink_manager.streamlink.Streamlink')
    def test_validate_oauth_token_invalid(self, mock_streamlink_cls):
        mock_session = mock_streamlink_cls.return_value
        mock_session.streams.side_effect = Exception('Unauthorized: The "Authorization" token is invalid.')

        status = self.manager.validate_oauth_token("testuser")

        self.assertEqual(status, AuthValidationStatus.INVALID)

    @patch('streamlink_manager.streamlink.Streamlink')
    def test_validate_oauth_token_unknown(self, mock_streamlink_cls):
        mock_session = mock_streamlink_cls.return_value
        mock_session.streams.side_effect = RuntimeError("temporary network failure")

        status = self.manager.validate_oauth_token("testuser")

        self.assertEqual(status, AuthValidationStatus.UNKNOWN)



class TestSelectQuality(unittest.TestCase):
    def sel(self, prefs, keys):
        return streamlink_manager.select_quality(prefs, {k: object() for k in keys})

    def test_comma_list_picks_first_available(self):
        self.assertEqual(self.sel("720p60,720p,best", ["720p", "best"]), "720p")

    def test_comma_list_first_entry_present(self):
        self.assertEqual(self.sel("720p60,720p,best", ["720p60", "720p", "best"]), "720p60")

    def test_whitespace_and_empty_entries(self):
        self.assertEqual(self.sel(" 720p60 , ,720p ", ["720p"]), "720p")

    def test_missing_quality_falls_back_to_best(self):
        self.assertEqual(self.sel("1080p,480p", ["best", "720p"]), "best")

    def test_single_quality_present(self):
        self.assertEqual(self.sel("720p", ["720p", "best"]), "720p")

    def test_single_quality_absent(self):
        self.assertEqual(self.sel("480p", ["720p", "best"]), "best")

    @patch('streamlink_manager.streamlink.Streamlink')
    def test_run_streamlink_uses_comma_preference(self, mock_streamlink_cls):
        config = MagicMock()
        config.oauth_token = "t"
        config.quality = "720p60,720p,best"
        wanted, other = MagicMock(), MagicMock()
        for s in (wanted, other):
            s.url = "http://example.com/playlist.m3u8"
            fd = MagicMock()
            fd.read.side_effect = [b'data', b'']
            s.open.return_value = fd
        mock_streamlink_cls.return_value.streams.return_value = {"720p": wanted, "best": other}
        with patch('builtins.open', unittest.mock.mock_open()):
            StreamlinkManager(config).run_streamlink("u", "f")
        wanted.open.assert_called_once()
        other.open.assert_not_called()

    @patch('streamlink_manager.streamlink.Streamlink')
    def test_stop_in_on_start_closes_fd_and_leaves_no_file(self, mock_streamlink_cls):
        stream = MagicMock(url="http://example.com/playlist.m3u8")
        fd = stream.open.return_value
        mock_streamlink_cls.return_value.streams.return_value = {"best": stream}

        def on_start():
            raise streamlink_manager.StopRequested(15)

        with patch('builtins.open', unittest.mock.mock_open()) as mock_file, \
                patch('streamlink_manager.shutil.move') as move, patch('streamlink_manager.os.remove') as remove:
            with self.assertRaises(streamlink_manager.StopRequested):
                StreamlinkManager(MagicMock(quality="best", oauth_token=None)).run_streamlink("u", "f", on_start=on_start)
        fd.close.assert_called_once()
        mock_file.assert_not_called()
        move.assert_not_called()
        remove.assert_not_called()

    @patch('streamlink_manager.streamlink.Streamlink')
    def test_on_start_error_closes_fd(self, mock_streamlink_cls):
        stream = MagicMock(url="http://example.com/playlist.m3u8")
        fd = stream.open.return_value
        mock_streamlink_cls.return_value.streams.return_value = {"best": stream}
        with patch('builtins.open', unittest.mock.mock_open()):
            with self.assertRaises(ValueError):
                StreamlinkManager(MagicMock(quality="best", oauth_token=None)).run_streamlink("u", "f", on_start=MagicMock(side_effect=ValueError))
        fd.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
